"""Standalone observation, service, and scheduler checks without HTTP composition."""

import asyncio
import logging
import sqlite3
import threading
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.freshness import DisplayStatus
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.scheduler import ConnectivityScheduler
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.errors import ConnectivityBusy, StorageError
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeExecutor:
    def __init__(self) -> None:
        self.outcomes: dict[int, list[ConnectivityOutcome | Exception]] = defaultdict(list)
        self.calls: list[int] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False
        self._lock = threading.Lock()

    def run(self, node: Node, _settings: SSHSettings) -> ConnectivityOutcome:
        with self._lock:
            self.calls.append(node.id)
            pending = self.outcomes[node.id]
            result = pending.pop(0) if pending else ConnectivityOutcome.CONNECTED
            self.started.set()
        if self.block and not self.release.wait(timeout=3):
            raise RuntimeError("test worker was not released")
        if isinstance(result, Exception):
            raise result
        return result

    def close(self) -> None:
        self.release.set()


@pytest.fixture
def setup_monitoring(
    tmp_path: Path,
) -> tuple[SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService]:
    database = tmp_path / "inventory.db"
    inventory = SQLiteNodeRepository(database)
    inventory.initialize()
    observations = SQLiteConnectivityRepository(database)
    observations.initialize()
    executor = FakeExecutor()
    service = ConnectivityService(
        inventory,
        observations,
        executor,
        SSHSettings("observer", tmp_path / "hosts", tmp_path / "key"),
        observation_ttl=timedelta(seconds=180),
    )
    return inventory, observations, executor, service


def test_latest_observation_is_utc_and_new_failure_supersedes_old_success(
    setup_monitoring: tuple[
        SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService
    ],
) -> None:
    inventory, observations, _, service = setup_monitoring
    node = inventory.add_node(NewNode("n1", "192.0.2.10", 22))
    assert service.latest(node.id) is None
    assert service.fleet_status().nodes[0].display_status is DisplayStatus.NOT_CHECKED

    old = observations.save(
        node.id,
        datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        ConnectivityOutcome.CONNECTED,
    )
    assert old.observed_at == datetime(2026, 1, 1, 6, 30, tzinfo=UTC)
    assert old.observed_at.tzinfo is UTC
    assert (
        service.fleet_status(as_of=old.observed_at + timedelta(seconds=181)).nodes[0].display_status
        is DisplayStatus.STALE
    )

    failed = observations.save(
        node.id, old.observed_at + timedelta(seconds=182), ConnectivityOutcome.CONNECTION_REFUSED
    )
    assert service.latest(node.id) == failed
    status = service.fleet_status(as_of=failed.observed_at).nodes[0]
    assert status.display_status is DisplayStatus.UNREACHABLE
    assert status.reason == "CONNECTION_REFUSED"
    with sqlite3.connect(observations.database_path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM connectivity_observations").fetchone()[0] == 2
        )
    assert inventory.get_node(node.id).observation_state == node.observation_state


def test_naive_timestamp_is_rejected_before_storage(
    setup_monitoring: tuple[
        SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService
    ],
) -> None:
    inventory, observations, _, _ = setup_monitoring
    node = inventory.add_node(NewNode("n1", "192.0.2.11", 22))
    with pytest.raises(ValueError, match="timezone"):
        observations.save(node.id, datetime(2026, 1, 1), ConnectivityOutcome.CONNECTED)
    assert observations.latest(node.id) is None


def test_repository_sql_error_is_not_a_saved_observation(
    setup_monitoring: tuple[
        SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, observations, _, _ = setup_monitoring
    node = inventory.add_node(NewNode("n1", "192.0.2.17", 22))

    def fail_connect() -> None:
        raise sqlite3.OperationalError("storage unavailable")

    monkeypatch.setattr(observations, "_connect", fail_connect)
    with pytest.raises(StorageError, match="Could not save"):
        observations.save(node.id, datetime(2026, 1, 1, tzinfo=UTC), ConnectivityOutcome.CONNECTED)


def test_service_recovery_and_storage_failure(
    setup_monitoring: tuple[
        SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, observations, executor, service = setup_monitoring
    node = inventory.add_node(NewNode("n1", "192.0.2.12", 22))
    executor.outcomes[node.id] = [
        ConnectivityOutcome.CONNECTION_TIMEOUT,
        ConnectivityOutcome.CONNECTED,
    ]
    failed = service.check(node.id)
    assert failed.observed_at.utcoffset() == timedelta(0)
    assert (
        service.fleet_status(as_of=failed.observed_at).nodes[0].display_status
        is DisplayStatus.UNREACHABLE
    )
    recovered = service.check(node.id)
    assert recovered.id > failed.id
    assert (
        service.fleet_status(as_of=recovered.observed_at).nodes[0].display_status
        is DisplayStatus.REACHABLE
    )

    def fail_save(
        _node_id: int, _at: datetime, _outcome: ConnectivityOutcome, _revision=None
    ) -> None:
        raise StorageError("disk unavailable")

    monkeypatch.setattr(observations, "save", fail_save)
    with pytest.raises(StorageError):
        service.check(node.id)
    assert observations.latest(node.id) == recovered


@pytest.mark.anyio
async def test_scheduler_checks_multiple_nodes_and_skips_same_node_overlap(
    setup_monitoring: tuple[
        SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService
    ],
) -> None:
    inventory, _, executor, service = setup_monitoring
    first = inventory.add_node(NewNode("n1", "192.0.2.13", 22))
    second = inventory.add_node(NewNode("n2", "192.0.2.14", 22))
    executor.block = True
    scheduler = ConnectivityScheduler(service, max_concurrent=2)
    first_cycle = asyncio.create_task(scheduler.run_cycle())
    assert await asyncio.to_thread(
        lambda: any(threading.Event().wait(0.05) or len(executor.calls) >= 2 for _ in range(40))
    )
    second_cycle = asyncio.create_task(scheduler.run_cycle())
    try:
        await asyncio.wait_for(second_cycle, timeout=2)
        assert set(executor.calls) == {first.id, second.id}
        assert len(executor.calls) == 2
    finally:
        executor.release.set()
        await asyncio.wait_for(first_cycle, timeout=2)
    assert all(
        item.display_status is DisplayStatus.REACHABLE for item in service.fleet_status().nodes
    )


@pytest.mark.anyio
async def test_scheduled_failure_then_recovery_uses_latest_observation(
    setup_monitoring: tuple[
        SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService
    ],
) -> None:
    inventory, observations, executor, service = setup_monitoring
    node = inventory.add_node(NewNode("n1", "192.0.2.18", 22))
    executor.outcomes[node.id] = [
        ConnectivityOutcome.CONNECTION_REFUSED,
        ConnectivityOutcome.CONNECTED,
    ]
    scheduler = ConnectivityScheduler(service)

    await scheduler.run_cycle()
    first = observations.latest(node.id)
    assert first is not None
    assert (
        service.fleet_status(as_of=first.observed_at).nodes[0].display_status
        is DisplayStatus.UNREACHABLE
    )
    await scheduler.run_cycle()
    second = observations.latest(node.id)
    assert second is not None and second.id > first.id
    assert (
        service.fleet_status(as_of=second.observed_at).nodes[0].display_status
        is DisplayStatus.REACHABLE
    )


@pytest.mark.anyio
async def test_scheduler_reports_task_failures_instead_of_discarding_them(
    setup_monitoring: tuple[
        SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService
    ],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    inventory, _, _, service = setup_monitoring
    inventory.add_node(NewNode("n1", "192.0.2.19", 22))
    scheduler = ConnectivityScheduler(service)

    async def fail_task(_node: Node) -> None:
        raise RuntimeError("task failed")

    monkeypatch.setattr(scheduler, "_check_node_bounded", fail_task)
    with caplog.at_level(logging.ERROR):
        await scheduler.run_cycle()
    assert "scheduled check task failed" in caplog.text.lower()


def test_scheduler_delay_uses_configured_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fleet_manager.connectivity.scheduler.random.uniform", lambda _a, b: b)
    scheduler = ConnectivityScheduler(object(), interval_seconds=60.0, jitter_ratio=0.1)  # type: ignore[arg-type]
    assert scheduler.calculate_delay() == 66.0


@pytest.mark.anyio
async def test_scheduler_skips_local_busy_and_logs_inventory_failure(
    setup_monitoring: tuple[
        SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService
    ],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    inventory, observations, executor, service = setup_monitoring
    node = inventory.add_node(NewNode("n1", "192.0.2.15", 22))
    executor.outcomes[node.id] = [ConnectivityBusy()]
    scheduler = ConnectivityScheduler(service)
    with caplog.at_level(logging.WARNING):
        await scheduler.run_cycle()
    assert observations.latest(node.id) is None
    assert "capacity exhausted" in caplog.text.lower()

    def fail_list() -> list[Node]:
        raise StorageError("inventory unavailable")

    monkeypatch.setattr(inventory, "list_nodes", fail_list)
    with caplog.at_level(logging.ERROR):
        await scheduler.run_cycle()
    assert "could not list nodes" in caplog.text.lower()


@pytest.mark.anyio
async def test_shutdown_keeps_in_flight_guard_until_thread_finishes(
    setup_monitoring: tuple[
        SQLiteNodeRepository, SQLiteConnectivityRepository, FakeExecutor, ConnectivityService
    ],
) -> None:
    inventory, _, executor, service = setup_monitoring
    node = inventory.add_node(NewNode("n1", "192.0.2.16", 22))
    executor.block = True
    scheduler = ConnectivityScheduler(service, initial_delay_seconds=0)
    await scheduler.start()
    assert await asyncio.to_thread(executor.started.wait, 2)
    try:
        await scheduler.stop(timeout=0.01)
        assert not scheduler.is_running
        assert node.id in scheduler._in_flight
        assert executor.calls == [node.id]
    finally:
        executor.release.set()
        if scheduler._workers:
            await asyncio.wait_for(asyncio.gather(*scheduler._workers), timeout=2)
    assert node.id not in scheduler._in_flight
