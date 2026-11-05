"""Standalone checks for the controlled operation boundary."""

import logging
import subprocess
import sys
import time
from datetime import UTC
from pathlib import Path
from unittest.mock import Mock

import paramiko
import pytest

from fleet_manager.config import OperationLimits, SSHSettings
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.errors import (
    InvalidAction,
    InvalidOperationArguments,
    OperationBusy,
    OperationInProgress,
    OperationUnavailable,
    StorageError,
)
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.operations.catalog import validate_action
from fleet_manager.operations.executor import DirectOperationExecutor, ProcessOperationExecutor
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationFailureCategory,
    OperationOutcome,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.service import OperationService
from fleet_manager.operations.transport import ParamikoOperationTransport


@pytest.fixture
def settings(tmp_path: Path) -> SSHSettings:
    return SSHSettings("observer", tmp_path / "known_hosts", tmp_path / "key")


def test_catalog_compiles_only_four_fixed_actions() -> None:
    assert validate_action("system.uptime", None).remote_command == "uptime"
    assert validate_action("system.memory", {}).remote_command == "free -m"
    assert (
        validate_action("system.disk", {"path": " /var/log "}).remote_command
        == "df -h -P -- /var/log"
    )
    assert (
        validate_action("service.status", {"service_name": "ssh.service"}).remote_command
        == "systemctl --no-pager status -- ssh.service"
    )


@pytest.mark.parametrize(
    ("action", "arguments", "error"),
    [
        ("system.reboot", {}, InvalidAction),
        ("system.uptime", {"extra": 1}, InvalidOperationArguments),
        ("system.memory", {"extra": 1}, InvalidOperationArguments),
        ("system.disk", {}, InvalidOperationArguments),
        ("system.disk", {"path": ""}, InvalidOperationArguments),
        ("system.disk", {"path": "/tmp;id"}, InvalidOperationArguments),
        ("system.disk", {"path": "/tmp/../etc"}, InvalidOperationArguments),
        ("system.disk", {"path": "/tmp/a b"}, InvalidOperationArguments),
        ("system.disk", {"path": "/tmp/'x'"}, InvalidOperationArguments),
        ("system.disk", {"path": "/tmp", "extra": 1}, InvalidOperationArguments),
        ("service.status", {}, InvalidOperationArguments),
        ("service.status", {"service_name": ""}, InvalidOperationArguments),
        ("service.status", {"service_name": "-ssh"}, InvalidOperationArguments),
        ("service.status", {"service_name": "ssh;id"}, InvalidOperationArguments),
        ("service.status", {"service_name": "ssh service"}, InvalidOperationArguments),
        ("service.status", {"service_name": "'ssh'"}, InvalidOperationArguments),
        ("service.status", {"service_name": "ssh", "extra": 1}, InvalidOperationArguments),
    ],
)
def test_catalog_rejects_unsafe_or_unexpected_input(
    action: str, arguments: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        validate_action(action, arguments)


class FakeTransport:
    def __init__(self, result: OperationExecutionResult) -> None:
        self.result = result
        self.calls: list[tuple[int, str, float, int]] = []

    def execute(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        self.calls.append((node.id, command, timeout_seconds, max_output_bytes))
        return self.result


def result(
    outcome: OperationOutcome = OperationOutcome.SUCCESS,
    category: OperationFailureCategory | None = None,
    exit_code: int | None = 0,
    stdout: str | None = "ok",
    stderr: str | None = "",
    truncated: bool = False,
) -> OperationExecutionResult:
    return OperationExecutionResult(outcome, category, exit_code, stdout, stderr, truncated)


@pytest.fixture
def service_parts(
    tmp_path: Path, settings: SSHSettings
) -> tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node]:
    database = tmp_path / "inventory.db"
    inventory = SQLiteNodeRepository(database)
    inventory.initialize()
    SQLiteConnectivityRepository(database).initialize()
    operations = SQLiteOperationsRepository(database)
    operations.initialize()
    node = inventory.add_node(NewNode("node", "192.0.2.1", 22))
    transport = FakeTransport(result())
    executor = DirectOperationExecutor(transport)
    return OperationService(inventory, operations, executor, settings), transport, operations, node


def test_service_rejects_unknown_action_before_dispatch_or_record(
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
) -> None:
    service, transport, repository, node = service_parts
    with pytest.raises(InvalidAction):
        service.execute(node.id, "system.reboot", {}, b"digest")
    assert transport.calls == []
    assert repository.list_for_node(node.id) == []


def test_service_persists_success_failure_uncertainty_and_sequential_requests(
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, transport, repository, node = service_parts
    with caplog.at_level(logging.DEBUG):
        first = service.execute(node.id, "system.uptime", {}, b"digest")
        transport.result = result(
            OperationOutcome.FAILURE, OperationFailureCategory.COMMAND_ERROR, 1, "", "failed"
        )
        second = service.execute(node.id, "system.uptime", {}, b"digest")
        transport.result = result(
            OperationOutcome.UNCERTAIN, OperationFailureCategory.TRANSPORT_ERROR, None, None, None
        )
        third = service.execute(node.id, "system.uptime", {}, b"digest")
    assert [first.outcome, second.outcome, third.outcome] == [
        OperationOutcome.SUCCESS,
        OperationOutcome.FAILURE,
        OperationOutcome.UNCERTAIN,
    ]
    assert len({first.id, second.id, third.id}) == 3
    assert all(row.started_at and row.completed_at for row in (first, second, third))
    assert repository.get(second.id) == second
    assert len(repository.list_for_node(node.id)) == 3
    assert transport.calls == [(node.id, "uptime", 15.0, 65536)] * 3
    assert "digest" not in caplog.text and "failed" not in caplog.text


def test_service_storage_failure_prevents_dispatch(
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, transport, repository, node = service_parts
    monkeypatch.setattr(repository, "create", Mock(side_effect=StorageError("write failed")))
    with pytest.raises(StorageError):
        service.execute(node.id, "system.uptime", {}, b"digest")
    assert transport.calls == []


def test_started_operation_is_recorded_as_uncertain_after_executor_error(
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, repository, node = service_parts

    def fail_after_start(node: Node, command: str, settings: SSHSettings, on_start: object) -> None:
        assert callable(on_start)
        on_start()
        raise OperationUnavailable("worker communication failed")

    monkeypatch.setattr(service.executor, "run", fail_after_start)
    with pytest.raises(OperationUnavailable):
        service.execute(node.id, "system.uptime", {}, b"digest")
    records = repository.list_for_node(node.id)
    assert len(records) == 1
    assert records[0].outcome == OperationOutcome.UNCERTAIN
    assert records[0].completed_at is not None
    assert records[0].failure_category == OperationFailureCategory.UNAVAILABLE


def test_direct_executor_releases_admission_when_start_callback_fails(
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
    settings: SSHSettings,
) -> None:
    _, transport, _, node = service_parts
    executor = DirectOperationExecutor(transport)
    with pytest.raises(StorageError):
        executor.run(
            node, "uptime", settings, on_start=lambda: (_ for _ in ()).throw(StorageError("db"))
        )
    assert executor.run(node, "uptime", settings).outcome == OperationOutcome.SUCCESS


class FakeProcess:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.returncode: int | None = None
        self.killed = False
        self.waited = False

    def communicate(
        self, input: str | None = None, timeout: float | None = None
    ) -> tuple[str, str]:
        if self.failure is not None:
            raise self.failure
        self.returncode = 0
        return ('{"outcome":"SUCCESS","exit_code":0,"stdout":"ok","stderr":""}', "")

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        assert timeout is not None
        return self.returncode or 0


@pytest.mark.parametrize(
    "failure", [OSError("broken pipe"), subprocess.TimeoutExpired("worker", 1)]
)
def test_process_executor_kills_and_reaps_on_communication_failure(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
    settings: SSHSettings,
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
) -> None:
    process = FakeProcess(failure)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    executor = ProcessOperationExecutor(OperationLimits())
    node = service_parts[3]
    if isinstance(failure, subprocess.TimeoutExpired):
        assert executor.run(node, "uptime", settings).outcome == OperationOutcome.TIMEOUT
    else:
        with pytest.raises(OperationUnavailable):
            executor.run(node, "uptime", settings)
    assert process.killed and process.waited
    assert executor._active == {}


def test_process_executor_reaps_when_start_record_fails(
    monkeypatch: pytest.MonkeyPatch,
    settings: SSHSettings,
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
) -> None:
    process = FakeProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    executor = ProcessOperationExecutor(OperationLimits())
    with pytest.raises(StorageError):
        executor.run(
            service_parts[3],
            "uptime",
            settings,
            on_start=lambda: (_ for _ in ()).throw(StorageError("db")),
        )
    assert process.killed and process.waited
    assert executor._active == {}


def test_process_executor_spawn_failure_leaves_no_active_node(
    monkeypatch: pytest.MonkeyPatch,
    settings: SSHSettings,
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
) -> None:
    def cannot_spawn(*args: object, **kwargs: object) -> None:
        raise OSError("spawn denied")

    monkeypatch.setattr(subprocess, "Popen", cannot_spawn)
    executor = ProcessOperationExecutor(OperationLimits())
    with pytest.raises(OperationUnavailable):
        executor.run(service_parts[3], "uptime", settings)
    assert executor._active == {}


def test_real_child_is_terminated_at_overall_deadline(
    settings: SSHSettings,
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
) -> None:
    executor = ProcessOperationExecutor(
        OperationLimits(total_timeout_seconds=1.0),
        worker_command=(sys.executable, "-c", "import time; time.sleep(10)"),
    )
    started = time.monotonic()
    execution = executor.run(service_parts[3], "uptime", settings)
    assert execution.outcome == OperationOutcome.TIMEOUT
    assert time.monotonic() - started < 3.0
    assert executor._active == {}


def test_executor_close_reaps_active_child_and_rejects_new_work(
    settings: SSHSettings,
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
) -> None:
    process = FakeProcess()
    executor = ProcessOperationExecutor(OperationLimits())
    node = service_parts[3]
    executor._active[node.id] = process  # type: ignore[assignment]
    executor.close()
    assert process.killed and process.waited
    with pytest.raises(OperationUnavailable):
        executor.run(node, "uptime", settings)


def test_transport_marks_lost_post_dispatch_result_uncertain_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
    settings: SSHSettings,
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
) -> None:
    class BrokenChannel:
        def settimeout(self, seconds: float) -> None:
            assert seconds == 10.0

        def exec_command(self, command: str) -> None:
            assert command == "uptime"

        def recv_ready(self) -> bool:
            raise OSError("connection lost")

    class ActiveTransport:
        def is_active(self) -> bool:
            return True

        def open_session(self) -> BrokenChannel:
            return BrokenChannel()

    class Client:
        closed = False

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *args: object) -> None:
            self.closed = True

        def load_host_keys(self, path: str) -> None:
            pass

        def get_host_keys(self) -> paramiko.HostKeys:
            return paramiko.HostKeys()

        def set_missing_host_key_policy(self, policy: object) -> None:
            pass

        def connect(self, **kwargs: object) -> None:
            assert kwargs["allow_agent"] is False
            assert kwargs["look_for_keys"] is False

        def get_transport(self) -> ActiveTransport:
            return ActiveTransport()

    client = Client()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda path: Mock())
    result_value = ParamikoOperationTransport().execute(service_parts[3], "uptime", settings)
    assert result_value.outcome == OperationOutcome.UNCERTAIN
    assert result_value.failure_category == OperationFailureCategory.TRANSPORT_ERROR
    assert client.closed


def test_same_node_concurrent_admission_and_restart_reconciliation(
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
    settings: SSHSettings,
) -> None:
    service, transport, repository, node = service_parts
    executor = DirectOperationExecutor(transport)
    executor._active.add(node.id)
    with pytest.raises(OperationInProgress):
        executor.run(node, "uptime", settings)
    executor._active.clear()
    record = service.execute(node.id, "system.uptime", {}, b"digest")
    assert record.requested_at.tzinfo == UTC
    assert repository.reconcile_in_flight() == 0


def test_capacity_applies_across_nodes_without_blocking_sequential_repeat(
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
    settings: SSHSettings,
) -> None:
    service, transport, _, node = service_parts
    other = service.inventory_repository.add_node(NewNode("other", "192.0.2.2", 22))
    executor = DirectOperationExecutor(transport, OperationLimits(max_concurrent=1))
    executor._active.add(node.id)
    with pytest.raises(OperationBusy):
        executor.run(other, "uptime", settings)
    executor._active.clear()
    assert executor.run(other, "uptime", settings).outcome == OperationOutcome.SUCCESS
    assert executor.run(other, "uptime", settings).outcome == OperationOutcome.SUCCESS


def test_repository_reconciles_running_after_restart(
    service_parts: tuple[OperationService, FakeTransport, SQLiteOperationsRepository, Node],
) -> None:
    service, _, repository, node = service_parts
    record = service.execute(node.id, "system.uptime", {}, b"digest")
    with repository._connect() as connection:
        connection.execute(
            "UPDATE operation_executions SET outcome='RUNNING', completed_at=NULL WHERE id=?",
            (record.id,),
        )
    assert repository.reconcile_in_flight() == 1
    recovered = repository.get(record.id)
    assert recovered is not None
    assert recovered.outcome == OperationOutcome.UNCERTAIN
    assert recovered.failure_category == OperationFailureCategory.CONTROL_PLANE_RESTARTED
    assert recovered.completed_at is not None
