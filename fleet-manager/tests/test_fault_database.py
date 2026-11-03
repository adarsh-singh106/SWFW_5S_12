"""Database, scheduler, and crash-recovery fault injection and resilience tests.

Covers:
- Scenario A: SQLite exclusive-lock timeout and StorageError classification.
- Scenario B: ConnectivityService storage failure under lock contention and SSH ordering.
- Scenario C: Interrupted SQLite transaction recovery (DELETE journal and WAL experiment).
- Scenario D: ConnectivityScheduler loop exception recovery and telemetry increment.
- Scenario E: Startup reconciliation of abandoned in-flight RUNNING operations.
- Scenario F: Pre-restore safety snapshot (.pre_restore.bak) preservation and recovery.
"""

from __future__ import annotations

import asyncio
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from scripts.backup_restore import perform_backup, perform_restore

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.executor import SSHCheckExecutor
from fleet_manager.connectivity.models import (
    ConnectivityObservation,
    ConnectivityOutcome,
)
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.scheduler import ConnectivityScheduler
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.errors import StorageError
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.main import create_app
from fleet_manager.metrics.registry import Counter, Gauge
from fleet_manager.metrics.telemetry import Telemetry
from fleet_manager.operations.models import (
    OperationFailureCategory,
    OperationOutcome,
    OperationRecord,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository

# ---------------------------------------------------------------------------
# Telemetry helper
# ---------------------------------------------------------------------------


def get_metric_value(
    metric: Counter | Gauge,
    labels: dict[str, str] | None = None,
) -> float | None:
    """Extract the scalar value from a Counter or Gauge matching optional labels."""
    expected_labels = labels or {}
    for sample in metric.collect():
        if sample.labels == expected_labels:
            return sample.value
    return None


# ---------------------------------------------------------------------------
# Scenario A: SQLite exclusive-lock timeout
# ---------------------------------------------------------------------------


def test_sqlite_exclusive_lock_timeout_inventory_add_node(tmp_path: Path) -> None:
    """An exclusive transaction lock causes add_node to fail with StorageError after ~5.0s."""
    db_path = tmp_path / "scenario_a_inventory.db"
    repo = SQLiteNodeRepository(db_path)
    repo.initialize()

    initial_node = repo.add_node(NewNode("initial-srv", "192.168.1.10", 22))
    assert initial_node.id is not None

    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def lock_holder() -> None:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            conn.execute("BEGIN EXCLUSIVE")
            lock_acquired.set()
            release_lock.wait()
            conn.rollback()
        finally:
            conn.close()

    holder_thread = threading.Thread(target=lock_holder, daemon=True)
    holder_thread.start()

    assert lock_acquired.wait(timeout=5.0), "Exclusive lock holder failed to acquire lock"

    start_mono = time.monotonic()
    try:
        with pytest.raises(StorageError) as exc_info:
            repo.add_node(NewNode("blocked-srv", "192.168.1.20", 22))

        elapsed = time.monotonic() - start_mono

        # The repository connection has timeout=5.0 configured.
        # Ensure bounded time window: between 4.0s and 12.0s.
        assert 4.0 <= elapsed <= 12.0, f"Expected ~5s timeout, took {elapsed:.3f}s"
        assert isinstance(exc_info.value.__cause__, sqlite3.OperationalError)
        assert "database is locked" in str(exc_info.value.__cause__).lower()

    finally:
        release_lock.set()
        holder_thread.join(timeout=5.0)

    # Verify no partial record was committed
    with sqlite3.connect(db_path) as verify_conn:
        rows = verify_conn.execute("SELECT name FROM nodes WHERE name = 'blocked-srv'").fetchall()
        assert len(rows) == 0

    # Verify subsequent write succeeds after lock release
    unblocked = repo.add_node(NewNode("unblocked-srv", "192.168.1.30", 22))
    assert unblocked.name == "unblocked-srv"


def test_sqlite_exclusive_lock_timeout_connectivity_save(tmp_path: Path) -> None:
    """Exclusive transaction lock causes connectivity save to raise StorageError on timeout."""
    db_path = tmp_path / "scenario_a_connectivity.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()
    node = node_repo.add_node(NewNode("monitored-srv", "192.168.1.10", 22))

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def lock_holder() -> None:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            conn.execute("BEGIN EXCLUSIVE")
            lock_acquired.set()
            release_lock.wait()
            conn.rollback()
        finally:
            conn.close()

    holder_thread = threading.Thread(target=lock_holder, daemon=True)
    holder_thread.start()

    assert lock_acquired.wait(timeout=5.0), "Exclusive lock holder failed to acquire lock"

    start_mono = time.monotonic()
    try:
        with pytest.raises(StorageError) as exc_info:
            conn_repo.save(node.id, datetime.now(UTC), ConnectivityOutcome.CONNECTED)

        elapsed = time.monotonic() - start_mono
        assert 4.0 <= elapsed <= 12.0, f"Expected ~5s timeout, took {elapsed:.3f}s"
        assert isinstance(exc_info.value.__cause__, sqlite3.OperationalError)

    finally:
        release_lock.set()
        holder_thread.join(timeout=5.0)

    # Verify no partial observation was created
    assert conn_repo.latest(node.id) is None

    # Verify subsequent write succeeds
    saved = conn_repo.save(node.id, datetime.now(UTC), ConnectivityOutcome.CONNECTED)
    assert saved.outcome == ConnectivityOutcome.CONNECTED


# ---------------------------------------------------------------------------
# Scenario B: Connectivity storage failure under lock contention
# ---------------------------------------------------------------------------


class HookedSSHExecutor:
    """Test collaborator executing an explicit callback during run() to inject lock contention."""

    def __init__(
        self,
        outcome: ConnectivityOutcome = ConnectivityOutcome.CONNECTED,
        on_run: Callable[[], None] | None = None,
    ) -> None:
        self.outcome = outcome
        self.on_run = on_run
        self.dispatch_count = 0

    def run(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome:
        self.dispatch_count += 1
        if self.on_run is not None:
            self.on_run()
        return self.outcome

    def close(self) -> None:
        pass


def test_connectivity_storage_failure_under_lock_contention(tmp_path: Path) -> None:
    """Verifies SSH dispatch precedes persistence and active gauge returns to zero on error."""
    db_path = tmp_path / "scenario_b.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()
    node = node_repo.add_node(NewNode("srv-b", "192.168.1.15", 22))

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    # Pre-seed an existing observation to confirm it remains intact
    initial_timestamp = datetime.now(UTC) - timedelta(minutes=5)
    initial_obs = conn_repo.save(node.id, initial_timestamp, ConnectivityOutcome.CONNECTED)

    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def lock_holder() -> None:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            conn.execute("BEGIN EXCLUSIVE")
            lock_acquired.set()
            release_lock.wait()
            conn.rollback()
        finally:
            conn.close()

    holder_thread: threading.Thread | None = None

    def inject_lock() -> None:
        nonlocal holder_thread
        holder_thread = threading.Thread(target=lock_holder, daemon=True)
        holder_thread.start()
        assert lock_acquired.wait(timeout=5.0), "Failed to acquire exclusive lock in callback"

    executor = HookedSSHExecutor(outcome=ConnectivityOutcome.CONNECTED, on_run=inject_lock)
    settings = SSHSettings("testuser", tmp_path / "known_hosts", tmp_path / "key")
    telemetry = Telemetry()

    service = ConnectivityService(
        inventory=node_repo,
        observations=conn_repo,
        executor=executor,
        settings=settings,
        telemetry=telemetry,
    )

    try:
        with pytest.raises(StorageError) as exc_info:
            service.check(node.id)

        # 1. Verify SSH dispatch occurred before persistence failure
        assert executor.dispatch_count == 1
        assert isinstance(exc_info.value.__cause__, sqlite3.OperationalError)

        # 2. Verify active checks gauge returned to zero despite persistence failure
        assert get_metric_value(telemetry.connectivity_active_checks) == 0.0

    finally:
        release_lock.set()
        if holder_thread is not None:
            holder_thread.join(timeout=5.0)

    # 3. Verify pre-existing observation record remains intact
    latest_obs = conn_repo.latest(node.id)
    assert latest_obs is not None
    assert latest_obs.id == initial_obs.id
    assert latest_obs.observed_at == initial_obs.observed_at

    # 4. Verify subsequent healthy check succeeds
    executor.on_run = None  # remove lock hook
    subsequent_obs = service.check(node.id)
    assert subsequent_obs.id > initial_obs.id
    assert subsequent_obs.outcome == ConnectivityOutcome.CONNECTED
    assert conn_repo.latest(node.id) is not None
    assert conn_repo.latest(node.id).id == subsequent_obs.id  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Scenario C: Interrupted SQLite transaction recovery
# ---------------------------------------------------------------------------

_CHILD_UNCOMMITTED_SCRIPT = """\
import sys
import sqlite3
import time

db_path = sys.argv[1]
conn = sqlite3.connect(db_path, timeout=5.0)
conn.execute("PRAGMA foreign_keys = ON;")
conn.execute("BEGIN IMMEDIATE;")
conn.execute(
    "INSERT INTO nodes (name, address, ssh_port, observation_state) "
    "VALUES ('uncommitted-child', '192.168.99.99', 22, 'NOT_CHECKED');"
)
sys.stdout.write("READY\\n")
sys.stdout.flush()

try:
    sys.stdin.readline()
except Exception:
    time.sleep(3600)
"""


def test_interrupted_sqlite_transaction_delete_journal_recovery(tmp_path: Path) -> None:
    """Controlled child process terminated during uncommitted write rolls back under DELETE mode."""
    db_path = tmp_path / "scenario_c_delete.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()
    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()
    op_repo = SQLiteOperationsRepository(db_path)
    op_repo.initialize()

    # Verify SQLite default DELETE journal mode
    with sqlite3.connect(db_path) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert str(journal_mode).lower() == "delete"

    # Insert committed baseline node
    node_repo.add_node(NewNode("committed-srv", "192.168.1.1", 22))

    # Spawn controlled child process
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_UNCOMMITTED_SCRIPT, str(db_path)],
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        ready_line = proc.stdout.readline()
        assert ready_line.strip() == "READY", f"Unexpected child output: {ready_line}"

        # Terminate child using Windows process termination API (TerminateProcess via kill)
        proc.kill()
        proc.wait(timeout=5.0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    # Open fresh connection to verify transaction recovery
    with sqlite3.connect(db_path) as fresh_conn:
        # Integrity checks
        integrity = fresh_conn.execute("PRAGMA integrity_check;").fetchall()
        assert integrity == [("ok",)], f"Integrity check failed: {integrity}"

        fk_check = fresh_conn.execute("PRAGMA foreign_key_check;").fetchall()
        assert fk_check == [], f"Foreign key violations found: {fk_check}"

        # Verify uncommitted change is not visible and committed data remains intact
        rows = [r[0] for r in fresh_conn.execute("SELECT name FROM nodes;").fetchall()]
        assert "committed-srv" in rows
        assert "uncommitted-child" not in rows

    # Verify subsequent valid write succeeds
    post_recovery = node_repo.add_node(NewNode("post-recovery-srv", "192.168.1.2", 22))
    assert post_recovery.name == "post-recovery-srv"


def test_interrupted_sqlite_transaction_wal_behavior_experiment(tmp_path: Path) -> None:
    """SQLite behavior experiment: uncommitted write recovery under WAL mode on disposable DB."""
    db_path = tmp_path / "scenario_c_wal_experiment.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()

    # Explicitly configure WAL mode for this experiment only
    with sqlite3.connect(db_path) as conn:
        wal_mode = conn.execute("PRAGMA journal_mode = WAL;").fetchone()[0]
        assert str(wal_mode).lower() == "wal"

    node_repo.add_node(NewNode("wal-committed-srv", "192.168.2.1", 22))

    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_UNCOMMITTED_SCRIPT, str(db_path)],
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        ready_line = proc.stdout.readline()
        assert ready_line.strip() == "READY"

        proc.kill()
        proc.wait(timeout=5.0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    with sqlite3.connect(db_path) as fresh_conn:
        integrity = fresh_conn.execute("PRAGMA integrity_check;").fetchall()
        assert integrity == [("ok",)]
        fk_check = fresh_conn.execute("PRAGMA foreign_key_check;").fetchall()
        assert fk_check == []

        rows = [r[0] for r in fresh_conn.execute("SELECT name FROM nodes;").fetchall()]
        assert "wal-committed-srv" in rows
        assert "uncommitted-child" not in rows

    post_recovery = node_repo.add_node(NewNode("wal-post-recovery-srv", "192.168.2.2", 22))
    assert post_recovery.name == "wal-post-recovery-srv"


# ---------------------------------------------------------------------------
# Scenario D: Scheduler loop exception recovery
# ---------------------------------------------------------------------------


class ControlledFailingService:
    """Test collaborator whose check() raises RuntimeError on cycle 1 and succeeds on cycle 2."""

    def __init__(
        self,
        real_service: ConnectivityService,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.real_service = real_service
        self.inventory = real_service.inventory
        self.observations = real_service.observations
        self.loop = loop
        self.call_count = 0
        self.cycle1_failed_event = asyncio.Event()
        self.cycle2_succeeded_event = asyncio.Event()

    def check(self, node_id: int) -> ConnectivityObservation:
        self.call_count += 1
        if self.call_count == 1:
            self.loop.call_soon_threadsafe(self.cycle1_failed_event.set)
            raise RuntimeError("Controlled cycle 1 unexpected runtime failure")
        obs = self.real_service.check(node_id)
        self.loop.call_soon_threadsafe(self.cycle2_succeeded_event.set)
        return obs


class PassthroughExecutor(SSHCheckExecutor):
    def run(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome:
        return ConnectivityOutcome.CONNECTED

    def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_scheduler_loop_recovers_from_cycle_runtime_error(tmp_path: Path) -> None:
    """The production scheduler loop survives unexpected RuntimeError and executes cycle 2."""
    db_path = tmp_path / "scenario_d.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()
    node_repo.add_node(NewNode("sched-srv", "10.0.0.1", 22))

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    telemetry = Telemetry()
    settings = SSHSettings("testuser", tmp_path / "known_hosts", tmp_path / "key")
    real_service = ConnectivityService(
        inventory=node_repo,
        observations=conn_repo,
        executor=PassthroughExecutor(),
        settings=settings,
        telemetry=telemetry,
    )

    loop = asyncio.get_running_loop()
    failing_service = ControlledFailingService(real_service, loop)

    # Use small interval and zero jitter for bounded, deterministic testing
    scheduler = ConnectivityScheduler(
        service=failing_service,  # type: ignore[arg-type]
        interval_seconds=0.02,
        jitter_ratio=0.0,
        initial_delay_seconds=0.001,
        max_concurrent=2,
        telemetry=telemetry,
    )

    await scheduler.start()
    try:
        assert scheduler.is_running

        # 1. Wait for cycle 1 failure signal
        await asyncio.wait_for(failing_service.cycle1_failed_event.wait(), timeout=5.0)

        # Verify scheduler did NOT terminate permanently
        assert scheduler.is_running is True

        # Bounded wait for worker thread to complete error recording in scheduler
        err_val: float | None = None
        for _ in range(100):
            err_val = get_metric_value(
                telemetry.scheduler_errors_total, {"reason": "unexpected_error"}
            )
            if err_val == 1.0:
                break
            await asyncio.sleep(0.01)

        # Verify error telemetry incremented with reason="unexpected_error"
        assert err_val == 1.0

        # 2. Wait for cycle 2 success signal
        await asyncio.wait_for(failing_service.cycle2_succeeded_event.wait(), timeout=5.0)
        assert failing_service.call_count >= 2

    finally:
        await scheduler.stop(timeout=5.0)

    # 3. Clean termination verification
    assert scheduler.is_running is False
    assert get_metric_value(telemetry.scheduler_running) == 0.0
    assert len(scheduler._workers) == 0
    assert scheduler._task is None or scheduler._task.done()


# ---------------------------------------------------------------------------
# Scenario E: Abandoned RUNNING operation reconciliation
# ---------------------------------------------------------------------------


def test_startup_reconciliation_abandons_running_preserves_terminal_and_telemetry(
    tmp_path: Path,
) -> None:
    """Startup reconciliation marks RUNNING as UNCERTAIN without mutating terminal records."""
    db_path = tmp_path / "scenario_e.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()
    node = node_repo.add_node(NewNode("recon-srv", "192.168.1.50", 22))

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    op_repo = SQLiteOperationsRepository(db_path)
    op_repo.initialize()

    now = datetime.now(UTC)

    # Record 1: Abandoned RUNNING operation (simulates control-plane crash during execution)
    op_running = OperationRecord(
        id="op_abandoned_01",
        node_id=node.id,
        action="system.uptime",
        arguments={},
        requested_at=now - timedelta(minutes=10),
        started_at=now - timedelta(minutes=9),
        completed_at=None,
        outcome=OperationOutcome.RUNNING,
        failure_category=None,
        exit_code=None,
        stdout=None,
        stderr=None,
        output_truncated=False,
        audit_metadata={"operator_type": "bearer_token"},
    )
    op_repo.create(op_running)

    # Record 2: Pre-existing terminal SUCCESS operation
    op_success = OperationRecord(
        id="op_terminal_success_02",
        node_id=node.id,
        action="system.uptime",
        arguments={},
        requested_at=now - timedelta(minutes=20),
        started_at=now - timedelta(minutes=19),
        completed_at=now - timedelta(minutes=18),
        outcome=OperationOutcome.SUCCESS,
        failure_category=None,
        exit_code=0,
        stdout="up 14 days\n",
        stderr="",
        output_truncated=False,
        audit_metadata={"operator_type": "bearer_token"},
    )
    op_repo.create(op_success)

    # Record 3: Pre-existing terminal FAILURE operation
    op_failed = OperationRecord(
        id="op_terminal_failed_03",
        node_id=node.id,
        action="service.restart",
        arguments={"name": "nginx"},
        requested_at=now - timedelta(minutes=30),
        started_at=now - timedelta(minutes=29),
        completed_at=now - timedelta(minutes=28),
        outcome=OperationOutcome.FAILURE,
        failure_category=OperationFailureCategory.TIMEOUT,
        exit_code=255,
        stdout="",
        stderr="Connection timed out\n",
        output_truncated=False,
        audit_metadata={"operator_type": "bearer_token"},
    )
    op_repo.create(op_failed)

    # Simulate control-plane restart using create_app and TestClient lifespan
    app = create_app(
        database_path=db_path,
        api_token="a" * 32,
        enable_scheduler=False,
    )
    with TestClient(app):
        reconciled_repo: SQLiteOperationsRepository = app.state.operations_repository
        telemetry: Telemetry = app.state.telemetry

        # 1. Verify Record 1 was reconciled to UNCERTAIN / CONTROL_PLANE_RESTARTED
        rec1 = reconciled_repo.get("op_abandoned_01")
        assert rec1 is not None
        assert rec1.outcome == OperationOutcome.UNCERTAIN
        assert rec1.failure_category == OperationFailureCategory.CONTROL_PLANE_RESTARTED
        assert rec1.completed_at is not None

        # 2. Verify Record 2 (SUCCESS) remains untouched
        rec2 = reconciled_repo.get("op_terminal_success_02")
        assert rec2 is not None
        assert rec2.outcome == OperationOutcome.SUCCESS
        assert rec2.failure_category is None
        assert rec2.exit_code == 0
        assert rec2.completed_at == op_success.completed_at

        # 3. Verify Record 3 (FAILURE) remains untouched
        rec3 = reconciled_repo.get("op_terminal_failed_03")
        assert rec3 is not None
        assert rec3.outcome == OperationOutcome.FAILURE
        assert rec3.failure_category == OperationFailureCategory.TIMEOUT
        assert rec3.exit_code == 255
        assert rec3.completed_at == op_failed.completed_at

        # 4. Verify telemetry was not incremented as a new execution
        op_samples = telemetry.operations_total.collect()
        assert len(op_samples) > 0
        assert all(sample.value == 0.0 for sample in op_samples), (
            f"Expected all operations_total counters to be 0.0, found: {op_samples}"
        )
        active_samples = telemetry.operations_active.collect()
        assert len(active_samples) > 0
        assert all(sample.value == 0.0 for sample in active_samples), (
            f"Expected all operations_active gauges to be 0.0, found: {active_samples}"
        )


# ---------------------------------------------------------------------------
# Scenario F: Stranded restore safety snapshot
# ---------------------------------------------------------------------------


def test_restore_creates_and_preserves_safety_snapshot(tmp_path: Path) -> None:
    """Restoring over an existing target creates and preserves target_db.pre_restore.bak."""
    source_db = tmp_path / "source.db"
    src_repo = SQLiteNodeRepository(source_db)
    src_repo.initialize()
    src_repo.add_node(NewNode("source-srv", "192.168.1.10", 22))

    backup_file = tmp_path / "backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "target.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("pre-existing-srv", "192.168.1.20", 22))

    perform_restore(backup_file, target_db)

    safety_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")
    assert safety_snapshot.exists()

    # Safety snapshot holds the pre-existing state
    with sqlite3.connect(safety_snapshot) as snap_conn:
        names = [r[0] for r in snap_conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["pre-existing-srv"]

    # Target holds the newly restored state
    with sqlite3.connect(target_db) as target_conn:
        names = [r[0] for r in target_conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["source-srv"]


def test_stranded_safety_snapshot_not_deleted_by_app_startup(tmp_path: Path) -> None:
    """Application startup does not delete or overwrite an existing .pre_restore.bak snapshot."""
    target_db = tmp_path / "live_target.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("live-srv", "192.168.1.30", 22))

    stranded_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")
    snap_repo = SQLiteNodeRepository(stranded_snapshot)
    snap_repo.initialize()
    snap_repo.add_node(NewNode("stranded-backup-srv", "192.168.1.40", 22))

    assert stranded_snapshot.exists()

    app = create_app(
        database_path=target_db,
        api_token="a" * 32,
        enable_scheduler=False,
    )
    with TestClient(app):
        assert app.state.is_ready is True

    # Crucial finding: The stranded safety snapshot is preserved intact on disk
    assert stranded_snapshot.exists()
    with sqlite3.connect(stranded_snapshot) as snap_conn:
        names = [r[0] for r in snap_conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["stranded-backup-srv"]


def test_interrupted_restore_rolls_back_to_safety_snapshot(tmp_path: Path) -> None:
    """If promotion fails during restore, target_db is rolled back from safety snapshot."""
    source_db = tmp_path / "source.db"
    src_repo = SQLiteNodeRepository(source_db)
    src_repo.initialize()
    src_repo.add_node(NewNode("new-srv", "192.168.1.10", 22))

    backup_file = tmp_path / "backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "target.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("safe-srv", "192.168.1.20", 22))

    from scripts import backup_restore

    orig_atomic_replace = backup_restore._atomic_replace

    def fail_on_temp_restore(source: Path, target: Path) -> None:
        if str(source).endswith(".restoring.tmp"):
            raise OSError("Injected simulated I/O failure during database promotion")
        orig_atomic_replace(source, target)

    with patch("scripts.backup_restore._atomic_replace", side_effect=fail_on_temp_restore):
        with pytest.raises(OSError, match="Injected simulated I/O failure"):
            perform_restore(backup_file, target_db)

    # Verify rollback: target database retains safe-srv
    with sqlite3.connect(target_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["safe-srv"]
