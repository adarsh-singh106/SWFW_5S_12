"""Standalone collector and HTTP exposition checks; no application composition."""

import json
import sqlite3
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Never
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.freshness import DisplayStatus
from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.schemas import FleetStatusResponse
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.errors import (
    InvalidAction,
    OperationInProgress,
    OperationUnavailable,
    StorageError,
)
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.metrics.router import router
from fleet_manager.metrics.telemetry import Telemetry
from fleet_manager.operations.catalog import ALLOWED_ACTIONS
from fleet_manager.operations.executor import DirectOperationExecutor
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationFailureCategory,
    OperationOutcome,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.service import OperationService

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
SUCCESS = 'fleet_collector_success{collector="fleet_status"}'
ERRORS = 'fleet_collector_errors_total{collector="fleet_status"}'
LAST_SUCCESS = 'fleet_collector_last_success_timestamp_seconds{collector="fleet_status"}'
SENSITIVE = "private-host.example /private/database.db token=fake-sensitive-value"


@dataclass
class Clock:
    now: float = NOW.timestamp()
    calls: int = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.now


class UnusedExecutor:
    def run(self, _node: Node, _settings: SSHSettings) -> ConnectivityOutcome:
        raise AssertionError("A metrics scrape must never execute an SSH check")

    def close(self) -> None:
        pass


@pytest.fixture
def service(tmp_path: Path) -> ConnectivityService:
    database = tmp_path / "inventory.db"
    inventory = SQLiteNodeRepository(database)
    inventory.initialize()
    observations = SQLiteConnectivityRepository(database)
    observations.initialize()
    inventory.add_node(NewNode("private-node", "private-host.example", 22))
    return ConnectivityService(inventory, observations, UnusedExecutor())


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def telemetry(service: ConnectivityService, clock: Clock) -> Telemetry:
    return Telemetry(service, clock=clock)


@pytest.fixture
def client(telemetry: Telemetry) -> Iterator[TestClient]:
    app = FastAPI()
    app.state.telemetry = telemetry
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def samples(body: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for line in body.splitlines():
        if line and not line.startswith("#"):
            name, value = line.rsplit(" ", 1)
            assert name not in result, f"Duplicate metric sample: {name}"
            result[name] = float(value)
    return result


def test_successful_collection_reports_health_in_the_same_scrape(
    client: TestClient, clock: Clock
) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "version=0.0.4" in response.headers["content-type"]
    assert response.text.endswith("\n")
    observed = samples(response.text)
    assert observed['fleet_nodes_by_status{status="NOT_CHECKED"}'] == 1
    assert observed[SUCCESS] == 1
    assert observed[ERRORS] == 0
    assert observed[LAST_SUCCESS] == clock.now
    assert clock.calls == 1
    for name, kind in (
        ("fleet_collector_success", "gauge"),
        ("fleet_collector_errors_total", "counter"),
        ("fleet_collector_last_success_timestamp_seconds", "gauge"),
        ("fleet_nodes_by_status", "gauge"),
    ):
        assert response.text.count(f"# HELP {name} ") == 1
        assert response.text.count(f"# TYPE {name} {kind}\n") == 1


@pytest.mark.parametrize("repository", ["inventory", "observations"])
def test_repository_failure_omits_counts_and_exposes_collector_health(
    client: TestClient, service: ConnectivityService, tmp_path: Path, repository: str, clock: Clock
) -> None:
    # A real SQLite query against an empty database raises a repository StorageError.
    getattr(service, repository).database_path = tmp_path / "missing-schema.db"
    response = client.get("/metrics")
    assert response.status_code == 200
    observed = samples(response.text)
    assert not any(name.startswith("fleet_nodes_by_status") for name in observed)
    assert observed[SUCCESS] == 0
    assert observed[ERRORS] == 1
    assert observed[LAST_SUCCESS] == 0
    assert clock.calls == 0


def test_success_failure_and_recovery_preserve_timestamp_and_count_each_failure_once(
    client: TestClient, service: ConnectivityService, tmp_path: Path, clock: Clock
) -> None:
    initial = samples(client.get("/metrics").text)
    assert initial[SUCCESS] == 1
    assert initial[ERRORS] == 0
    assert initial[LAST_SUCCESS] == clock.now
    database = service.inventory.database_path
    service.inventory.database_path = tmp_path / "missing-schema.db"

    for failures in (1, 2):
        clock.now += 10
        response = client.get("/metrics")
        assert response.status_code == 200
        failed = samples(response.text)
        assert failed[SUCCESS] == 0
        assert failed[ERRORS] == failures
        assert failed[LAST_SUCCESS] == initial[LAST_SUCCESS]
        assert not any(name.startswith("fleet_nodes_by_status") for name in failed)
    assert clock.calls == 1

    service.inventory.database_path = database
    clock.now += 10
    recovered = samples(client.get("/metrics").text)
    assert recovered[SUCCESS] == 1
    assert recovered[ERRORS] == 2
    assert recovered[LAST_SUCCESS] == clock.now
    assert recovered['fleet_nodes_by_status{status="NOT_CHECKED"}'] == 1
    assert clock.calls == 2


def test_repeated_successful_scrapes_leave_application_events_unchanged(
    client: TestClient,
    telemetry: Telemetry,
    service: ConnectivityService,
    monkeypatch: pytest.MonkeyPatch,
    clock: Clock,
) -> None:
    telemetry.connectivity_checks_total.inc(2, labels={"outcome": "CONNECTED"})
    telemetry.connectivity_check_duration_seconds.observe(0.5, labels={"outcome": "CONNECTED"})
    telemetry.scheduler_cycles_total.inc(3)
    telemetry.scheduler_checks_skipped_total.inc(labels={"reason": "busy"})
    telemetry.scheduler_errors_total.inc(labels={"reason": "storage_error"})
    original = service.fleet_status
    calls = 0

    def collect() -> FleetStatusResponse:
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(service, "fleet_status", collect)
    baseline: dict[str, float] | None = None
    for _ in range(5):
        clock.now += 10
        response = client.get("/metrics")
        assert response.status_code == 200
        observed = samples(response.text)
        assert observed[SUCCESS] == 1
        assert observed[ERRORS] == 0
        assert observed[LAST_SUCCESS] == clock.now
        events = {
            name: value
            for name, value in observed.items()
            if name.startswith(("fleet_connectivity_", "fleet_scheduler_"))
        }
        if baseline is None:
            baseline = events
        assert events == baseline
        assert events['fleet_connectivity_checks_total{outcome="CONNECTED"}'] == 2
        assert events['fleet_connectivity_check_duration_seconds_count{outcome="CONNECTED"}'] == 1
        assert events["fleet_scheduler_cycles_total"] == 3
    assert calls == 5


def test_success_timestamp_is_recorded_after_collection(
    client: TestClient, service: ConnectivityService, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = service.fleet_status

    def collect() -> FleetStatusResponse:
        result = original()
        clock.now += 10
        return result

    monkeypatch.setattr(service, "fleet_status", collect)
    observed = samples(client.get("/metrics").text)
    assert observed[LAST_SUCCESS] == NOW.timestamp() + 10


def test_status_counts_cover_all_derived_states_without_exposing_nodes(
    client: TestClient, service: ConnectivityService, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index, (outcome, age) in enumerate(
        (
            (ConnectivityOutcome.CONNECTED, 0),
            (ConnectivityOutcome.CONNECTION_REFUSED, 0),
            (ConnectivityOutcome.AUTH_FAILED, 0),
            (ConnectivityOutcome.CONNECTED, 181),
        )
    ):
        node = service.inventory.add_node(NewNode(f"private-{index}", f"node-{index}.example", 22))
        service.observations.save(node.id, NOW - timedelta(seconds=age), outcome)
    original = service.fleet_status
    monkeypatch.setattr(service, "fleet_status", lambda: original(as_of=NOW))
    response = client.get("/metrics")
    observed = samples(response.text)
    assert observed[SUCCESS] == 1  # Unreachable nodes do not mean the collector failed.
    assert observed[ERRORS] == 0
    assert {
        name: value for name, value in observed.items() if name.startswith("fleet_nodes_by_status")
    } == {f'fleet_nodes_by_status{{status="{state.value}"}}': 1 for state in DisplayStatus}
    assert "private-" not in response.text
    assert ".example" not in response.text


def test_successful_empty_inventory_has_genuine_zero_counts(
    client: TestClient, service: ConnectivityService, tmp_path: Path
) -> None:
    empty_inventory = SQLiteNodeRepository(tmp_path / "empty.db")
    empty_inventory.initialize()
    service.inventory = empty_inventory
    observed = samples(client.get("/metrics").text)
    assert observed[SUCCESS] == 1
    assert observed[ERRORS] == 0
    assert {
        name: value for name, value in observed.items() if name.startswith("fleet_nodes_by_status")
    } == {f'fleet_nodes_by_status{{status="{state.value}"}}': 0 for state in DisplayStatus}


def test_late_repository_failure_does_not_publish_partial_counts(
    client: TestClient, service: ConnectivityService, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = service.inventory.list_nodes()[0]
    second = service.inventory.add_node(NewNode("another-private-node", "another.example", 22))
    original = service.observations.latest
    visited: list[int] = []

    def latest(node_id: int) -> ConnectivityObservation | None:
        visited.append(node_id)
        if node_id == second.id:
            raise StorageError(SENSITIVE)
        return original(node_id)

    monkeypatch.setattr(service.observations, "latest", latest)
    response = client.get("/metrics")
    assert response.status_code == 200
    observed = samples(response.text)
    assert observed[SUCCESS] == 0
    assert observed[ERRORS] == 1
    assert "fleet_nodes_by_status" not in response.text
    assert visited == [first.id, second.id]


@pytest.mark.parametrize("failure", [sqlite3.OperationalError, StorageError, RuntimeError])
def test_collection_exceptions_never_expose_sensitive_details(
    client: TestClient,
    service: ConnectivityService,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: type[Exception],
) -> None:
    def fail() -> FleetStatusResponse:
        raise failure(SENSITIVE)

    monkeypatch.setattr(service, "fleet_status", fail)
    caplog.set_level("DEBUG")
    response = client.get("/metrics")
    assert response.status_code == 200
    observed = samples(response.text)
    assert observed[SUCCESS] == 0
    assert observed[ERRORS] == 1
    assert observed[LAST_SUCCESS] == 0
    assert "fleet_nodes_by_status" not in response.text
    for value in SENSITIVE.split():
        assert value not in response.text
        assert value not in caplog.text


def test_metric_labels_are_bounded_and_ignore_request_values(client: TestClient) -> None:
    response = client.get("/metrics", params={"collector": "untrusted", "node_id": "999999"})
    observed = samples(response.text)
    assert {name for name in observed if name.startswith("fleet_collector_")} == {
        SUCCESS,
        ERRORS,
        LAST_SUCCESS,
    }
    for name in observed:
        if "{" in name:
            for label in name.split("{", 1)[1].removesuffix("}").split(","):
                assert label.split("=", 1)[0] in {
                    "outcome",
                    "reason",
                    "status",
                    "le",
                    "collector",
                    "action",
                }
    for value in ("untrusted", "999999", "private-node", "private-host.example"):
        assert value not in response.text


@pytest.mark.parametrize("failure_at", ["telemetry", "registry", "sample", "callback"])
def test_complete_exposition_failure_returns_sanitized_http_500(
    client: TestClient,
    telemetry: Telemetry,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure_at: str,
) -> None:
    def fail() -> Never:
        raise RuntimeError(SENSITIVE)

    if failure_at == "telemetry":
        monkeypatch.setattr(telemetry, "render", fail)
    elif failure_at == "registry":
        monkeypatch.setattr(telemetry.registry, "render", fail)
    elif failure_at == "sample":
        monkeypatch.setattr(telemetry.connectivity_checks_total, "collect", fail)
    else:
        telemetry.registry.register_collector(fail)
    caplog.set_level("DEBUG")
    response = client.get("/metrics")
    assert response.status_code == 500
    assert response.text == "Metrics exposition failed\n"
    assert "version=0.0.4" not in response.headers["content-type"]
    for value in SENSITIVE.split():
        assert value not in response.text
        assert value not in caplog.text


def test_independent_telemetry_instances_do_not_share_collector_state(
    service: ConnectivityService, clock: Clock, tmp_path: Path
) -> None:
    first = Telemetry(service, clock=clock)
    database = service.inventory.database_path
    service.inventory.database_path = tmp_path / "missing-schema.db"
    assert samples(first.render())[ERRORS] == 1
    service.inventory.database_path = database
    second = Telemetry(service, clock=clock)
    assert samples(second.render())[ERRORS] == 0
    assert samples(first.render())[ERRORS] == 1


def test_unconfigured_service_makes_no_attempt_and_supports_later_attachment(
    service: ConnectivityService, clock: Clock
) -> None:
    telemetry = Telemetry(clock=clock)
    for _ in range(2):
        observed = samples(telemetry.render())
        assert observed[SUCCESS] == 0
        assert observed[ERRORS] == 0
        assert observed[LAST_SUCCESS] == 0
        assert not any(name.startswith("fleet_nodes_by_status") for name in observed)
    assert clock.calls == 0
    telemetry.service = service
    assert samples(telemetry.render())[SUCCESS] == 1


def test_concurrent_scrapes_each_report_their_own_failed_attempt(
    telemetry: Telemetry, service: ConnectivityService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> FleetStatusResponse:
        raise StorageError(SENSITIVE)

    monkeypatch.setattr(service, "fleet_status", fail)
    start = Barrier(8)

    def scrape(_: int) -> dict[str, float]:
        start.wait(timeout=5)
        return samples(telemetry.render())

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(scrape, range(8)))
    assert sorted(result[ERRORS] for result in results) == list(range(1, 9))
    assert all(result[SUCCESS] == 0 and result[LAST_SUCCESS] == 0 for result in results)


@dataclass
class MonotonicClock:
    current: float = 100.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class FakeOperationTransport:
    def __init__(self, result_value: OperationExecutionResult | None = None) -> None:
        self.result = result_value or OperationExecutionResult(
            outcome=OperationOutcome.SUCCESS,
            failure_category=None,
            exit_code=0,
            stdout="ok\n",
            stderr="",
            output_truncated=False,
        )
        self.calls: list[tuple[int, str]] = []
        self.on_execute: Callable[[], None] | None = None

    def execute(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        self.calls.append((node.id, command))
        if self.on_execute is not None:
            self.on_execute()
        return self.result


@dataclass
class OperationTestContext:
    service: OperationService
    transport: FakeOperationTransport
    telemetry: Telemetry
    node: Node
    mono_clock: MonotonicClock
    settings: SSHSettings
    client: TestClient
    operations_repo: SQLiteOperationsRepository


@pytest.fixture
def op_ctx(tmp_path: Path) -> Iterator[OperationTestContext]:
    db = tmp_path / "op_inventory.db"
    inventory = SQLiteNodeRepository(db)
    inventory.initialize()
    connectivity = SQLiteConnectivityRepository(db)
    connectivity.initialize()
    operations = SQLiteOperationsRepository(db)
    operations.initialize()
    node = inventory.add_node(NewNode("op-node", "op-host.example", 22))

    transport = FakeOperationTransport()
    executor = DirectOperationExecutor(transport)
    settings = SSHSettings("observer", tmp_path / "hosts", tmp_path / "key")
    mono_clock = MonotonicClock()
    telemetry = Telemetry()

    service = OperationService(
        inventory_repository=inventory,
        operations_repository=operations,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
        monotonic_clock=mono_clock,
    )

    app = FastAPI()
    app.state.telemetry = telemetry
    app.include_router(router)

    with TestClient(app) as test_client:
        yield OperationTestContext(
            service=service,
            transport=transport,
            telemetry=telemetry,
            node=node,
            mono_clock=mono_clock,
            settings=settings,
            client=test_client,
            operations_repo=operations,
        )


def test_each_registered_operation_action_produces_only_allowed_action_labels(
    op_ctx: OperationTestContext,
) -> None:
    op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    op_ctx.service.execute(op_ctx.node.id, "system.memory", {}, b"digest")
    op_ctx.service.execute(op_ctx.node.id, "system.disk", {"path": "/var/log"}, b"digest")
    op_ctx.service.execute(
        op_ctx.node.id, "service.status", {"service_name": "ssh.service"}, b"digest"
    )

    observed = samples(op_ctx.client.get("/metrics").text)
    action_labels: set[str] = set()
    for name in observed:
        if name.startswith(("fleet_operations_total{", "fleet_operations_active{")):
            for part in name.split("{")[1].rstrip("}").split(","):
                k, v = part.split("=")
                if k == "action":
                    action_labels.add(v.strip('"'))
    assert action_labels == ALLOWED_ACTIONS


def test_successful_execution_increments_outcome_counter_exactly_once(
    op_ctx: OperationTestContext,
) -> None:
    initial = samples(op_ctx.client.get("/metrics").text)
    assert initial['fleet_operations_total{action="system.uptime",outcome="SUCCESS"}'] == 0.0

    op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")

    after = samples(op_ctx.client.get("/metrics").text)
    assert after['fleet_operations_total{action="system.uptime",outcome="SUCCESS"}'] == 1.0
    assert after['fleet_operations_total{action="system.uptime",outcome="FAILURE"}'] == 0.0
    assert after['fleet_operations_total{action="system.uptime",outcome="TIMEOUT"}'] == 0.0
    assert after['fleet_operations_total{action="system.uptime",outcome="UNCERTAIN"}'] == 0.0


def test_nonzero_exit_produces_command_error_classification_and_increments_failure(
    op_ctx: OperationTestContext,
) -> None:
    op_ctx.transport.result = OperationExecutionResult(
        outcome=OperationOutcome.FAILURE,
        failure_category=OperationFailureCategory.COMMAND_ERROR,
        exit_code=1,
        stdout="",
        stderr="unit not found",
        output_truncated=False,
    )
    record = op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    assert record.outcome == OperationOutcome.FAILURE
    assert record.failure_category == OperationFailureCategory.COMMAND_ERROR

    observed = samples(op_ctx.client.get("/metrics").text)
    assert observed['fleet_operations_total{action="system.uptime",outcome="FAILURE"}'] == 1.0
    assert observed['fleet_operations_total{action="system.uptime",outcome="SUCCESS"}'] == 0.0


def test_post_dispatch_connection_loss_produces_uncertain(op_ctx: OperationTestContext) -> None:
    op_ctx.transport.result = OperationExecutionResult(
        outcome=OperationOutcome.UNCERTAIN,
        failure_category=OperationFailureCategory.TRANSPORT_ERROR,
        exit_code=None,
        stdout=None,
        stderr="transport dropped",
        output_truncated=False,
    )
    record = op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    assert record.outcome == OperationOutcome.UNCERTAIN
    assert record.failure_category == OperationFailureCategory.TRANSPORT_ERROR

    observed = samples(op_ctx.client.get("/metrics").text)
    assert observed['fleet_operations_total{action="system.uptime",outcome="UNCERTAIN"}'] == 1.0


def test_overall_executor_deadline_uses_timeout_classification(
    op_ctx: OperationTestContext,
) -> None:
    op_ctx.transport.result = OperationExecutionResult(
        outcome=OperationOutcome.TIMEOUT,
        failure_category=OperationFailureCategory.TIMEOUT,
        exit_code=None,
        stdout=None,
        stderr="timed out",
        output_truncated=False,
    )
    record = op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    assert record.outcome == OperationOutcome.TIMEOUT
    assert record.failure_category == OperationFailureCategory.TIMEOUT

    observed = samples(op_ctx.client.get("/metrics").text)
    assert observed['fleet_operations_total{action="system.uptime",outcome="TIMEOUT"}'] == 1.0


def test_invalid_actions_do_not_increment_operation_counters(op_ctx: OperationTestContext) -> None:
    with pytest.raises(InvalidAction):
        op_ctx.service.execute(op_ctx.node.id, "system.reboot", {}, b"digest")

    observed = samples(op_ctx.client.get("/metrics").text)
    assert all(
        val == 0.0 for key, val in observed.items() if key.startswith("fleet_operations_total")
    )


def test_rejected_same_node_concurrent_execution_does_not_corrupt_active_counts(
    op_ctx: OperationTestContext,
) -> None:
    concurrent_checked = False

    def during_execution() -> None:
        nonlocal concurrent_checked
        with pytest.raises(OperationInProgress):
            op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
        during_metrics = samples(op_ctx.client.get("/metrics").text)
        assert during_metrics['fleet_operations_active{action="system.uptime"}'] == 1.0
        concurrent_checked = True

    op_ctx.transport.on_execute = during_execution
    op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    assert concurrent_checked

    after_metrics = samples(op_ctx.client.get("/metrics").text)
    assert after_metrics['fleet_operations_active{action="system.uptime"}'] == 0.0
    assert after_metrics['fleet_operations_total{action="system.uptime",outcome="SUCCESS"}'] == 1.0


def test_active_gauge_increments_and_decrements_correctly(op_ctx: OperationTestContext) -> None:
    observed_active_during = 0.0

    def during() -> None:
        nonlocal observed_active_during
        observed_active_during = samples(op_ctx.client.get("/metrics").text)[
            'fleet_operations_active{action="system.uptime"}'
        ]

    op_ctx.transport.on_execute = during
    op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")

    assert observed_active_during == 1.0
    assert (
        samples(op_ctx.client.get("/metrics").text)[
            'fleet_operations_active{action="system.uptime"}'
        ]
        == 0.0
    )


def test_active_gauge_returns_to_zero_after_exceptions_and_startup_failure(
    op_ctx: OperationTestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Transport exception
    def fail_transport() -> None:
        raise OSError("transport disconnected")

    op_ctx.transport.on_execute = fail_transport
    with pytest.raises(OSError):
        op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    assert (
        samples(op_ctx.client.get("/metrics").text)[
            'fleet_operations_active{action="system.uptime"}'
        ]
        == 0.0
    )

    # 2. Worker startup failure
    def fail_startup(*args: object, **kwargs: object) -> None:
        raise OperationUnavailable("failed to spawn worker")

    monkeypatch.setattr(op_ctx.service.executor, "run", fail_startup)
    with pytest.raises(OperationUnavailable):
        op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    assert (
        samples(op_ctx.client.get("/metrics").text)[
            'fleet_operations_active{action="system.uptime"}'
        ]
        == 0.0
    )

    # 3. Storage error during result completion
    op_ctx.transport.on_execute = None
    monkeypatch.undo()
    monkeypatch.setattr(
        op_ctx.operations_repo, "update_completion", Mock(side_effect=StorageError("db failed"))
    )
    with pytest.raises(StorageError):
        op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    assert (
        samples(op_ctx.client.get("/metrics").text)[
            'fleet_operations_active{action="system.uptime"}'
        ]
        == 0.0
    )


def test_duration_histogram_observes_actual_elapsed_execution_time(
    op_ctx: OperationTestContext,
) -> None:
    def advance_monotonic() -> None:
        op_ctx.mono_clock.advance(1.5)

    op_ctx.transport.on_execute = advance_monotonic
    op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")

    observed = samples(op_ctx.client.get("/metrics").text)
    assert (
        observed['fleet_operation_duration_seconds_count{action="system.uptime",outcome="SUCCESS"}']
        == 1.0
    )
    assert (
        observed['fleet_operation_duration_seconds_sum{action="system.uptime",outcome="SUCCESS"}']
        == 1.5
    )
    assert (
        observed[
            'fleet_operation_duration_seconds_bucket{action="system.uptime",le="1.0",outcome="SUCCESS"}'
        ]
        == 0.0
    )
    assert (
        observed[
            'fleet_operation_duration_seconds_bucket{action="system.uptime",le="2.5",outcome="SUCCESS"}'
        ]
        == 1.0
    )
    assert (
        observed[
            'fleet_operation_duration_seconds_bucket{action="system.uptime",le="+Inf",outcome="SUCCESS"}'
        ]
        == 1.0
    )


def test_repeated_metrics_scrapes_do_not_increment_operation_event_counters(
    op_ctx: OperationTestContext,
) -> None:
    op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    baseline = {
        name: value
        for name, value in samples(op_ctx.client.get("/metrics").text).items()
        if name.startswith("fleet_operations_")
    }

    for _ in range(5):
        current = {
            name: value
            for name, value in samples(op_ctx.client.get("/metrics").text).items()
            if name.startswith("fleet_operations_")
        }
        assert current == baseline


def test_per_instance_telemetry_registries_remain_isolated(tmp_path: Path) -> None:
    db = tmp_path / "isolated.db"
    inventory = SQLiteNodeRepository(db)
    inventory.initialize()
    connectivity = SQLiteConnectivityRepository(db)
    connectivity.initialize()
    operations = SQLiteOperationsRepository(db)
    operations.initialize()
    node = inventory.add_node(NewNode("node", "10.0.0.1", 22))

    settings = SSHSettings("observer", tmp_path / "hosts", tmp_path / "key")
    t1 = Telemetry()
    t2 = Telemetry()
    s1 = OperationService(
        inventory,
        operations,
        DirectOperationExecutor(FakeOperationTransport()),
        ssh_settings=settings,
        telemetry=t1,
    )
    s2 = OperationService(
        inventory,
        operations,
        DirectOperationExecutor(FakeOperationTransport()),
        ssh_settings=settings,
        telemetry=t2,
    )

    s1.execute(node.id, "system.uptime", {}, b"digest")
    assert (
        samples(t1.render())['fleet_operations_total{action="system.uptime",outcome="SUCCESS"}']
        == 1.0
    )
    assert (
        samples(t2.render())['fleet_operations_total{action="system.uptime",outcome="SUCCESS"}']
        == 0.0
    )

    s2.execute(node.id, "system.memory", {}, b"digest")
    assert (
        samples(t2.render())['fleet_operations_total{action="system.memory",outcome="SUCCESS"}']
        == 1.0
    )
    assert (
        samples(t1.render())['fleet_operations_total{action="system.memory",outcome="SUCCESS"}']
        == 0.0
    )


def test_no_sensitive_node_host_command_or_output_in_metric_labels(
    op_ctx: OperationTestContext,
) -> None:
    secret_payload = "super-secret-auth-token-12345"
    op_ctx.transport.result = OperationExecutionResult(
        outcome=OperationOutcome.SUCCESS,
        failure_category=None,
        exit_code=0,
        stdout=f"stdout-{secret_payload}",
        stderr=f"stderr-{secret_payload}",
        output_truncated=False,
    )
    op_ctx.service.execute(op_ctx.node.id, "system.disk", {"path": f"/{secret_payload}"}, b"digest")
    body = op_ctx.client.get("/metrics").text

    assert secret_payload not in body
    assert "op-host.example" not in body
    assert "op-node" not in body


def test_outcome_label_values_remain_finite_and_bounded(op_ctx: OperationTestContext) -> None:
    op_ctx.service.execute(op_ctx.node.id, "system.uptime", {}, b"digest")
    observed = samples(op_ctx.client.get("/metrics").text)

    found_outcomes: set[str] = set()
    for name in observed:
        if name.startswith("fleet_operations_total{"):
            labels = name.split("{")[1].rstrip("}")
            for item in labels.split(","):
                k, v = item.split("=")
                if k == "outcome":
                    found_outcomes.add(v.strip('"'))

    assert found_outcomes == {"SUCCESS", "FAILURE", "TIMEOUT", "UNCERTAIN"}


def test_monitoring_dashboard_json_structure_and_datasource_uid() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "monitoring" / "grafana" / "dashboards" / "fleet-monitoring.json"
    datasource_path = (
        repo_root / "monitoring" / "grafana" / "provisioning" / "datasources" / "prometheus.yaml"
    )
    dashboards_provider_path = (
        repo_root / "monitoring" / "grafana" / "provisioning" / "dashboards" / "dashboards.yaml"
    )

    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    assert dashboard["uid"] == "fleet-manager-overview"
    assert dashboard["editable"] is False

    ds_text = datasource_path.read_text(encoding="utf-8")
    assert "uid: prometheus" in ds_text
    assert "http://127.0.0.1:9090" in ds_text

    provider_text = dashboards_provider_path.read_text(encoding="utf-8")
    assert "allowUiUpdates: false" in provider_text
    assert "editable: false" in provider_text

    for panel in dashboard.get("panels", []):
        if panel.get("type") == "row":
            continue
        ds = panel.get("datasource")
        if ds and isinstance(ds, dict):
            assert ds.get("uid") == "prometheus"


def test_dashboard_queries_refer_only_to_valid_metrics() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "monitoring" / "grafana" / "dashboards" / "fleet-monitoring.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))

    valid_prefixes = (
        "fleet_nodes_by_status",
        "fleet_connectivity_",
        "fleet_collector_",
        "fleet_operation_",
        "fleet_operations_",
        "fleet_scheduler_",
        "up",
        "node_cpu_seconds_total",
        "node_memory_",
        "node_filesystem_",
        "node_network_",
        "time()",
    )

    queries: list[str] = []
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if expr:
                queries.append(expr)

    assert len(queries) >= 15
    for expr in queries:
        assert any(prefix in expr for prefix in valid_prefixes), (
            f"Unexpected metric in query: {expr}"
        )


def test_scrape_targets_and_labels_do_not_expose_sensitive_data() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    targets_path = repo_root / "monitoring" / "prometheus" / "targets.json"
    targets_data = json.loads(targets_path.read_text(encoding="utf-8"))

    assert isinstance(targets_data, list)
    assert len(targets_data) >= 1
    for group in targets_data:
        for target in group.get("targets", []):
            assert target.startswith("127.0.0.1:")
        labels = group.get("labels", {})
        for _, v in labels.items():
            assert not any(
                secret in str(v).lower() for secret in ("pass", "token", "key", "secret", "bearer")
            )
