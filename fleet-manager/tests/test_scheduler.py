"""Tests for periodic automatic connectivity monitoring, bounds, and lifecycle."""

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fleet_manager.config import (
    MonitoringSettings,
    SSHSettings,
    load_monitoring_settings,
)
from fleet_manager.connectivity.freshness import DisplayStatus
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.scheduler import ConnectivityScheduler
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.errors import (
    ConnectivityBusy,
    ConnectivityConfigurationError,
    ConnectivityInProgress,
)
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.main import create_app


class ControllableTransport:
    def __init__(self, outcome: ConnectivityOutcome = ConnectivityOutcome.CONNECTED) -> None:
        self.outcome = outcome
        self.call_count = 0
        self.current_concurrency = 0
        self.max_observed_concurrency = 0
        self.delay: float = 0.0
        self.failure: Exception | None = None

    def verify(self, _node: Node, _settings: SSHSettings) -> ConnectivityOutcome:
        self.current_concurrency += 1
        if self.current_concurrency > self.max_observed_concurrency:
            self.max_observed_concurrency = self.current_concurrency
        try:
            self.call_count += 1
            if self.delay > 0:
                import time

                time.sleep(self.delay)
            if self.failure is not None:
                raise self.failure
            return self.outcome
        finally:
            self.current_concurrency -= 1


class FakeExecutor:
    def __init__(self, transport: ControllableTransport) -> None:
        self.transport = transport

    def run(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome:
        return self.transport.verify(node, settings)

    def close(self) -> None:
        pass


@pytest.fixture
def test_setup(
    tmp_path: Path,
) -> tuple[
    SQLiteNodeRepository, SQLiteConnectivityRepository, ControllableTransport, ConnectivityService
]:
    db = tmp_path / "test.db"
    inventory = SQLiteNodeRepository(db)
    inventory.initialize()
    observations = SQLiteConnectivityRepository(db)
    observations.initialize()
    transport = ControllableTransport()
    executor = FakeExecutor(transport)
    settings = SSHSettings("observer", tmp_path / "hosts", tmp_path / "key")
    service = ConnectivityService(
        inventory, observations, executor, settings, observation_ttl=timedelta(seconds=180)
    )
    return inventory, observations, transport, service


@pytest.mark.anyio
async def test_scheduler_cycles_registered_nodes_and_recovers(
    test_setup: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        ControllableTransport,
        ConnectivityService,
    ],
) -> None:
    inventory, _, transport, service = test_setup
    inventory.add_node(NewNode("n1", "10.0.0.1", 22))
    inventory.add_node(NewNode("n2", "10.0.0.2", 22))

    scheduler = ConnectivityScheduler(service, interval_seconds=10.0, max_concurrent=2)

    # Initial state: NOT_CHECKED
    initial_status = service.fleet_status()
    assert all(item.display_status == DisplayStatus.NOT_CHECKED for item in initial_status.nodes)

    # First cycle: Transport set to AUTH_FAILED
    transport.outcome = ConnectivityOutcome.AUTH_FAILED
    await scheduler.run_cycle()

    failed_status = service.fleet_status()
    assert len(failed_status.nodes) == 2
    for item in failed_status.nodes:
        assert item.display_status == DisplayStatus.CHECK_ERROR
        assert item.reason == "AUTH_FAILED"
        assert item.observation is not None
        assert item.observation.outcome == ConnectivityOutcome.AUTH_FAILED

    # Recovery: Transport recovered to CONNECTED
    transport.outcome = ConnectivityOutcome.CONNECTED
    await scheduler.run_cycle()

    recovered_status = service.fleet_status()
    for item in recovered_status.nodes:
        assert item.display_status == DisplayStatus.REACHABLE
        assert item.reason is None
        assert item.observation is not None
        assert item.observation.outcome == ConnectivityOutcome.CONNECTED


@pytest.mark.anyio
async def test_scheduler_bounds_concurrency(
    test_setup: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        ControllableTransport,
        ConnectivityService,
    ],
) -> None:
    inventory, _, transport, service = test_setup
    from fleet_manager.inventory.models import NewNode

    for i in range(1, 6):
        inventory.add_node(NewNode(f"node-{i}", f"10.0.0.{i}", 22))

    transport.delay = 0.05
    scheduler = ConnectivityScheduler(service, interval_seconds=10.0, max_concurrent=2)

    await scheduler.run_cycle()

    assert transport.call_count == 5
    assert transport.max_observed_concurrency <= 2


@pytest.mark.anyio
async def test_scheduler_handles_capacity_exhaustion_backpressure(
    test_setup: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        ControllableTransport,
        ConnectivityService,
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    inventory, _, transport, service = test_setup
    from fleet_manager.inventory.models import NewNode

    inventory.add_node(NewNode("n1", "10.0.0.1", 22))

    # Simulate executor capacity busy
    transport.failure = ConnectivityBusy()
    scheduler = ConnectivityScheduler(service, interval_seconds=10.0, max_concurrent=2)

    with caplog.at_level(logging.WARNING):
        await scheduler.run_cycle()

    assert "capacity exhausted" in caplog.text.lower()
    # The node should remain NOT_CHECKED because check was skipped without storing an observation
    status = service.fleet_status()
    assert status.nodes[0].display_status == DisplayStatus.NOT_CHECKED


@pytest.mark.anyio
async def test_scheduler_handles_in_progress_checks_without_overlapping(
    test_setup: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        ControllableTransport,
        ConnectivityService,
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    inventory, _, transport, service = test_setup
    from fleet_manager.inventory.models import NewNode

    inventory.add_node(NewNode("n1", "10.0.0.1", 22))

    # Simulate check already in progress (e.g. manual check)
    transport.failure = ConnectivityInProgress()
    scheduler = ConnectivityScheduler(service, interval_seconds=10.0, max_concurrent=2)

    with caplog.at_level(logging.INFO):
        await scheduler.run_cycle()

    assert "already in progress" in caplog.text.lower()
    status = service.fleet_status()
    assert status.nodes[0].display_status == DisplayStatus.NOT_CHECKED


@pytest.mark.anyio
async def test_scheduler_logs_configuration_error_without_crashing(
    test_setup: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        ControllableTransport,
        ConnectivityService,
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    inventory, _, transport, service = test_setup
    from fleet_manager.inventory.models import NewNode

    inventory.add_node(NewNode("n1", "10.0.0.1", 22))

    transport.failure = ConnectivityConfigurationError("Missing private key")
    scheduler = ConnectivityScheduler(service, interval_seconds=10.0, max_concurrent=2)

    with caplog.at_level(logging.WARNING):
        await scheduler.run_cycle()

    assert "ssh configuration unavailable" in caplog.text.lower()


@pytest.mark.anyio
async def test_scheduler_prevents_duplicate_start_within_instance(
    test_setup: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        ControllableTransport,
        ConnectivityService,
    ],
) -> None:
    _, _, _, service = test_setup
    scheduler = ConnectivityScheduler(
        service, interval_seconds=10.0, initial_delay_seconds=10.0, max_concurrent=2
    )

    await scheduler.start()
    try:
        assert scheduler.is_running
        with pytest.raises(RuntimeError, match="already running"):
            await scheduler.start()
    finally:
        await scheduler.stop()
    assert not scheduler.is_running


@pytest.mark.anyio
async def test_scheduler_stop_and_shutdown(
    test_setup: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        ControllableTransport,
        ConnectivityService,
    ],
) -> None:
    _, _, _, service = test_setup
    scheduler = ConnectivityScheduler(
        service, interval_seconds=0.05, initial_delay_seconds=0.01, max_concurrent=2
    )

    await scheduler.start()
    assert scheduler.is_running
    await asyncio.sleep(0.03)

    await scheduler.stop()
    assert not scheduler.is_running
    # Calling stop again is idempotent
    await scheduler.stop()
    assert not scheduler.is_running


def test_scheduler_jitter_distribution() -> None:
    class DummyService:
        pass

    scheduler = ConnectivityScheduler(DummyService(), interval_seconds=100.0, jitter_ratio=0.1)  # type: ignore[arg-type]
    delays = [scheduler.calculate_delay() for _ in range(50)]
    assert all(90.0 <= d <= 110.0 for d in delays)
    # Ensure there is variation (modest jitter)
    assert len(set(delays)) > 1


def test_load_monitoring_settings_validation() -> None:
    settings = load_monitoring_settings(ttl_seconds=120, interval_seconds=30.0, jitter_ratio=0.05)
    assert settings.observation_ttl_seconds == 120
    assert settings.polling_interval_seconds == 30.0
    assert settings.jitter_ratio == 0.05
    assert settings.enabled is True

    with pytest.raises(RuntimeError, match="Observation TTL"):
        load_monitoring_settings(ttl_seconds=0)

    with pytest.raises(RuntimeError, match="Monitoring interval"):
        load_monitoring_settings(interval_seconds=0.0)

    with pytest.raises(RuntimeError, match="Monitoring jitter ratio"):
        load_monitoring_settings(jitter_ratio=0.8)


def test_scheduler_lifespan_integration(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str]
) -> None:
    transport = ControllableTransport(ConnectivityOutcome.CONNECTED)
    settings = MonitoringSettings(
        observation_ttl_seconds=180,
        polling_interval_seconds=0.05,
        jitter_ratio=0.0,
        enabled=True,
    )
    app = create_app(
        tmp_path / "inventory.db",
        api_token=api_token,
        ssh_transport=transport,
        ssh_settings=SSHSettings("observer", tmp_path / "hosts", tmp_path / "key"),
        monitoring_settings=settings,
    )
    with TestClient(app) as client:
        # Scheduler should be running in app state
        assert hasattr(app.state, "connectivity_scheduler")
        scheduler = app.state.connectivity_scheduler
        assert scheduler is not None
        assert scheduler.is_running

        # Register a node
        res = client.post(
            "/api/nodes",
            json={"name": "test-node", "address": "192.168.1.50"},
            headers=auth_headers,
        )
        assert res.status_code == 201

    # After client exits, scheduler should be stopped
    assert not scheduler.is_running
