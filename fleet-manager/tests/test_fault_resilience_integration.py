"""End-to-end resilience integration test suite.

Validates combined recovery paths under disposable databases and controlled
loopback infrastructure across five resilience scenarios:
- Scenario A: Transport disconnect after dispatch -> UNCERTAIN -> same-node recovery
- Scenario B: Forced worker termination -> UNCERTAIN reconciliation -> same-node recovery
- Scenario C: Scheduler unexpected cycle failure -> error telemetry -> cycle 2 success & stop
- Scenario D: SQLite exclusive-lock contention -> StorageError -> release -> valid write
- Scenario E: Restore safety snapshot collision -> fail-closed PreRestoreSnapshotExistsError
"""

from __future__ import annotations

import asyncio
import socket
import sqlite3
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import paramiko
import pytest
from paramiko.common import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED,
    OPEN_SUCCEEDED,
)
from scripts.backup_restore import (
    PreRestoreSnapshotExistsError,
    calculate_sha256,
    perform_backup,
    perform_restore,
)

from fleet_manager.config import OperationLimits, SSHSettings
from fleet_manager.connectivity.executor import SSHCheckExecutor
from fleet_manager.connectivity.models import (
    ConnectivityObservation,
    ConnectivityOutcome,
)
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.scheduler import ConnectivityScheduler
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.errors import OperationUnavailable, StorageError
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.metrics.registry import Counter, Gauge
from fleet_manager.metrics.telemetry import Telemetry
from fleet_manager.operations.executor import ProcessOperationExecutor
from fleet_manager.operations.models import (
    OperationFailureCategory,
    OperationOutcome,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.service import OperationService

# ---------------------------------------------------------------------------
# Test worker scripts
# ---------------------------------------------------------------------------

_SYNC_WAIT_SCRIPT = """\
import sys, json, socket, time

try:
    req = json.load(sys.stdin)
except Exception:
    pass

port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(("127.0.0.1", port))
s.sendall(b"READY\\n")

try:
    while True:
        data = s.recv(1024)
        if not data:
            break
        time.sleep(0.05)
except Exception:
    pass

while True:
    time.sleep(1.0)
"""

_SUCCESS_SCRIPT = """\
import sys, json

try:
    req = json.load(sys.stdin)
except Exception:
    pass

output = {
    "outcome": "SUCCESS",
    "failure_category": None,
    "exit_code": 0,
    "stdout": "resilience recovery healthy\\n",
    "stderr": "",
    "output_truncated": False,
}
sys.stdout.write(json.dumps(output))
sys.stdout.flush()
"""


def _make_worker_cmd(tmp_path: Path, script_content: str, *extra_args: str) -> tuple[str, ...]:
    """Write an isolated worker script and construct the command array."""
    script_path = tmp_path / f"worker_{time.time_ns()}.py"
    script_path.write_text(script_content, encoding="utf-8")
    return (sys.executable, str(script_path), *extra_args)


@contextmanager
def _readiness_listener() -> Iterator[tuple[socket.socket, int]]:
    """Bind an ephemeral IPv4 TCP listener for worker synchronization."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        yield listener, port
    finally:
        listener.close()


def _accept_worker_ready(listener: socket.socket, timeout: float = 5.0) -> socket.socket:
    """Accept connection from worker and await READY handshake with bounded timeout."""
    listener.settimeout(timeout)
    conn, _ = listener.accept()
    conn.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        chunk = conn.recv(128)
        if not chunk:
            break
        buf += chunk
    if b"READY" not in buf:
        conn.close()
        raise RuntimeError(f"Expected READY handshake, got: {buf!r}")
    return conn


def _write_known_hosts(path: Path, port: int, key: paramiko.PKey) -> None:
    """Format and write a single known_hosts entry for loopback testing."""
    path.write_text(
        f"[127.0.0.1]:{port} {key.get_name()} {key.get_base64()}\n",
        encoding="ascii",
    )


def _get_metric_val(metric: Counter | Gauge, labels: dict[str, str] | None = None) -> float | None:
    """Extract scalar sample value matching label dict."""
    target_labels = labels or {}
    for sample in metric.collect():
        if sample.labels == target_labels:
            return sample.value
    return None


# ---------------------------------------------------------------------------
# Loopback SSH Server supporting Dynamic Fault Injection
# ---------------------------------------------------------------------------


@contextmanager
def _dynamic_fault_server(
    host_key: paramiko.PKey,
    accepted_key: paramiko.PKey,
    disconnect_flag: list[bool],
    exec_landmark_event: threading.Event,
) -> Iterator[int]:
    """Paramiko loopback SSH server whose disconnect-after-dispatch behavior is dynamic."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    stop_event = threading.Event()
    transports: list[paramiko.Transport] = []
    transports_lock = threading.Lock()

    class _DynamicInterface(paramiko.ServerInterface):
        def __init__(self, transport: paramiko.Transport) -> None:
            self.transport = transport

        def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
            if username == "fleet-observer" and key == accepted_key:
                return int(AUTH_SUCCESSFUL)
            return int(AUTH_FAILED)

        def get_allowed_auths(self, _username: str) -> str:
            return "publickey"

        def check_channel_request(self, kind: str, _chanid: int) -> int:
            if kind == "session":
                return int(OPEN_SUCCEEDED)
            return int(OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED)

        def check_channel_exec_request(self, channel: paramiko.Channel, command: bytes) -> bool:
            exec_landmark_event.set()

            if disconnect_flag[0]:

                def drop_conn() -> None:
                    time.sleep(0.04)
                    self.transport.close()
                    try:
                        channel.close()
                    except Exception:
                        pass

                threading.Thread(target=drop_conn, daemon=True).start()
                return True

            def handle_success() -> None:
                try:
                    channel.send(b"up 1 day\n")
                    channel.send_exit_status(0)
                    time.sleep(0.04)
                    channel.close()
                except Exception:
                    pass

            threading.Thread(target=handle_success, daemon=True).start()
            return True

    def handle_conn(conn: socket.socket) -> None:
        with conn:
            transport = paramiko.Transport(conn)
            with transports_lock:
                transports.append(transport)
            try:
                transport.add_server_key(host_key)
                transport.start_server(server=_DynamicInterface(transport))
                chan = transport.accept(5)
                deadline = time.monotonic() + 5.0
                while transport.is_active() and time.monotonic() < deadline:
                    if chan is not None and chan.closed:
                        time.sleep(0.04)
                        break
                    time.sleep(0.02)
            except (EOFError, OSError, paramiko.SSHException):
                pass
            finally:
                transport.close()

    def serve() -> None:
        while not stop_event.is_set():
            try:
                conn, _ = listener.accept()
                threading.Thread(target=handle_conn, args=(conn,), daemon=True).start()
            except TimeoutError:
                continue
            except OSError:
                break

    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()

    try:
        yield port
    finally:
        stop_event.set()
        listener.close()
        with transports_lock:
            for t in transports:
                try:
                    t.close()
                except Exception:
                    pass
        server_thread.join(timeout=3.0)


# ---------------------------------------------------------------------------
# Scenario A: Transport failure and recovery
# ---------------------------------------------------------------------------


def test_scenario_a_transport_failure_and_recovery(tmp_path: Path) -> None:
    """Disconnect after dispatch marks UNCERTAIN; subsequent operation on same node succeeds."""
    db_path = tmp_path / "scenario_a.db"
    inv_repo = SQLiteNodeRepository(db_path)
    inv_repo.initialize()
    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()
    ops_repo = SQLiteOperationsRepository(db_path)
    ops_repo.initialize()

    telemetry = Telemetry()
    known_hosts_path = tmp_path / "known_hosts"
    private_key_path = tmp_path / "id_rsa"
    client_key = paramiko.RSAKey.generate(2048)
    client_key.write_private_key_file(str(private_key_path))

    server_key = paramiko.RSAKey.generate(2048)
    exec_landmark = threading.Event()
    disconnect_flag = [True]

    with _dynamic_fault_server(
        server_key, client_key, disconnect_flag, exec_landmark
    ) as loopback_port:
        _write_known_hosts(known_hosts_path, loopback_port, server_key)
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
        executor = ProcessOperationExecutor(OperationLimits(max_concurrent=2))
        service = OperationService(
            inventory_repository=inv_repo,
            operations_repository=ops_repo,
            executor=executor,
            ssh_settings=settings,
            telemetry=telemetry,
        )

        node = inv_repo.add_node(NewNode("scenario-a-srv", "127.0.0.1", loopback_port))

        # 1. Dispatch operation 1 under forced disconnect after landmark
        record1 = service.execute(node.id, "system.uptime", {}, b"digest-scen-a-1")

        # 2. Verify dispatch landmark established & outcome UNCERTAIN
        assert exec_landmark.is_set(), "Command dispatch landmark was not triggered"
        assert record1.outcome == OperationOutcome.UNCERTAIN
        assert record1.failure_category == OperationFailureCategory.TRANSPORT_ERROR
        assert record1.exit_code is None

        # 3. Verify UNCERTAIN is durably persisted
        persisted1 = ops_repo.get(record1.id)
        assert persisted1 is not None
        assert persisted1.outcome == OperationOutcome.UNCERTAIN

        # Verify active telemetry returns to 0
        active_val1 = _get_metric_val(telemetry.operations_active, {"action": "system.uptime"})
        assert active_val1 == 0.0

        # 4. Switch server to healthy mode and execute operation 2 on the SAME node
        disconnect_flag[0] = False
        record2 = service.execute(node.id, "system.uptime", {}, b"digest-scen-a-2")

        # 5. Verify successful recovery and telemetry returning to zero
        assert record2.outcome == OperationOutcome.SUCCESS
        assert record2.failure_category is None
        assert record2.exit_code == 0
        assert "up 1 day" in (record2.stdout or "")

        persisted2 = ops_repo.get(record2.id)
        assert persisted2 is not None
        assert persisted2.outcome == OperationOutcome.SUCCESS

        active_val2 = _get_metric_val(telemetry.operations_active, {"action": "system.uptime"})
        assert active_val2 == 0.0
        assert len(executor._active) == 0


# ---------------------------------------------------------------------------
# Scenario B: Worker termination and recovery
# ---------------------------------------------------------------------------


def test_scenario_b_worker_termination_and_recovery(tmp_path: Path) -> None:
    """Forced worker kill reconciles to UNCERTAIN; subsequent operation succeeds on same node."""
    db_path = tmp_path / "scenario_b.db"
    inv_repo = SQLiteNodeRepository(db_path)
    inv_repo.initialize()
    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()
    ops_repo = SQLiteOperationsRepository(db_path)
    ops_repo.initialize()

    telemetry = Telemetry()
    settings = SSHSettings("testuser", tmp_path / "known_hosts", tmp_path / "id_rsa")
    node = inv_repo.add_node(NewNode("scenario-b-srv", "127.0.0.1", 22))

    exec_error: Exception | None = None

    with _readiness_listener() as (listener, port):
        worker_cmd = _make_worker_cmd(tmp_path, _SYNC_WAIT_SCRIPT, str(port))
        executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
        service = OperationService(
            inventory_repository=inv_repo,
            operations_repository=ops_repo,
            executor=executor,
            ssh_settings=settings,
            telemetry=telemetry,
        )

        def run_worker() -> None:
            nonlocal exec_error
            try:
                service.execute(node.id, "system.uptime", {}, b"digest-scen-b-1")
            except Exception as exc:
                exec_error = exc

        worker_thread = threading.Thread(target=run_worker, daemon=True)
        worker_thread.start()

        # 1. Await synchronization point
        conn = _accept_worker_ready(listener, timeout=5.0)
        try:
            # Confirm active worker tracked
            assert node.id in executor._active
            child_proc = executor._active[node.id]
            assert child_proc.poll() is None, "Child process must be actively running"

            # 2. Terminate child worker through captured Popen handle
            child_proc.kill()
        finally:
            try:
                conn.close()
            except OSError:
                pass

        worker_thread.join(timeout=5.0)
        assert not worker_thread.is_alive()

    # 3. Verify exception and terminal state reconciliation
    assert isinstance(exec_error, OperationUnavailable)
    records = ops_repo.list_for_node(node.id)
    assert len(records) == 1
    reconciled = records[0]
    assert reconciled.outcome == OperationOutcome.UNCERTAIN
    assert reconciled.failure_category == OperationFailureCategory.UNAVAILABLE
    assert reconciled.completed_at is not None
    assert reconciled.stderr == "Operation worker failed before a confirmed result"

    # Verify active telemetry is zero and active dict is clear
    assert _get_metric_val(telemetry.operations_active, {"action": "system.uptime"}) == 0.0
    assert node.id not in executor._active

    # 4. Execute subsequent healthy operation on the same node
    executor._command = _make_worker_cmd(tmp_path, _SUCCESS_SCRIPT)
    healthy_record = service.execute(node.id, "system.uptime", {}, b"digest-scen-b-2")

    # 5. Verify recovery
    assert healthy_record.outcome == OperationOutcome.SUCCESS
    assert healthy_record.exit_code == 0
    persisted_healthy = ops_repo.get(healthy_record.id)
    assert persisted_healthy is not None
    assert persisted_healthy.outcome == OperationOutcome.SUCCESS

    assert _get_metric_val(telemetry.operations_active, {"action": "system.uptime"}) == 0.0
    assert len(executor._active) == 0


# ---------------------------------------------------------------------------
# Scenario C: Scheduler failure and recovery
# ---------------------------------------------------------------------------


class _ControlledFailingService:
    """Collaborator raising RuntimeError on cycle 1 and succeeding on cycle 2."""

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
            raise RuntimeError("Controlled cycle 1 unexpected runtime exception")
        obs = self.real_service.check(node_id)
        self.loop.call_soon_threadsafe(self.cycle2_succeeded_event.set)
        return obs


class _MockSSHCheckExecutor(SSHCheckExecutor):
    def run(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome:
        return ConnectivityOutcome.CONNECTED

    def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_scenario_c_scheduler_failure_and_recovery(tmp_path: Path) -> None:
    """Scheduler recovers from unexpected cycle exception, completes cycle 2, and stops cleanly."""
    db_path = tmp_path / "scenario_c.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()
    node = node_repo.add_node(NewNode("scenario-c-srv", "10.0.0.1", 22))

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    telemetry = Telemetry()
    settings = SSHSettings("testuser", tmp_path / "known_hosts", tmp_path / "key")
    real_service = ConnectivityService(
        inventory=node_repo,
        observations=conn_repo,
        executor=_MockSSHCheckExecutor(),
        settings=settings,
        telemetry=telemetry,
    )

    loop = asyncio.get_running_loop()
    failing_service = _ControlledFailingService(real_service, loop)

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
        assert scheduler.is_running is True

        # 1. Wait for cycle 1 unexpected failure
        await asyncio.wait_for(failing_service.cycle1_failed_event.wait(), timeout=5.0)

        # Scheduler must survive and remain running
        assert scheduler.is_running is True

        # 2. Verify error telemetry
        err_val: float | None = None
        for _ in range(100):
            err_val = _get_metric_val(
                telemetry.scheduler_errors_total, {"reason": "unexpected_error"}
            )
            if err_val == 1.0:
                break
            await asyncio.sleep(0.01)

        assert err_val == 1.0

        # 3. Wait for scheduled cycle 2 to complete successfully
        await asyncio.wait_for(failing_service.cycle2_succeeded_event.wait(), timeout=5.0)
        assert failing_service.call_count >= 2

        obs = conn_repo.latest(node.id)
        assert obs is not None
        assert obs.outcome == ConnectivityOutcome.CONNECTED

    finally:
        # 4. Verify clean scheduler shutdown
        await scheduler.stop(timeout=5.0)

    assert scheduler.is_running is False
    assert _get_metric_val(telemetry.scheduler_running) == 0.0
    assert len(scheduler._workers) == 0
    assert scheduler._task is None or scheduler._task.done()


# ---------------------------------------------------------------------------
# Scenario D: SQLite lock and recovery
# ---------------------------------------------------------------------------


def test_scenario_d_sqlite_lock_and_recovery(tmp_path: Path) -> None:
    """Exclusive lock contention raises StorageError; release restores valid write and integrity."""
    db_path = tmp_path / "scenario_d.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()
    node = node_repo.add_node(NewNode("scenario-d-srv", "192.168.1.10", 22))

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    telemetry = Telemetry()
    settings = SSHSettings("testuser", tmp_path / "known_hosts", tmp_path / "key")
    service = ConnectivityService(
        inventory=node_repo,
        observations=conn_repo,
        executor=_MockSSHCheckExecutor(),
        settings=settings,
        telemetry=telemetry,
    )

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

    assert lock_acquired.wait(timeout=5.0), "Lock holder failed to acquire exclusive lock"

    # 1. Verify repository / service reports bounded StorageError under lock
    start_mono = time.monotonic()
    try:
        with pytest.raises(StorageError) as exc_info:
            service.check(node.id)

        elapsed = time.monotonic() - start_mono
        assert 4.0 <= elapsed <= 12.0, f"Expected bounded ~5s timeout, took {elapsed:.3f}s"
        assert isinstance(exc_info.value.__cause__, sqlite3.OperationalError)
        assert "database is locked" in str(exc_info.value.__cause__).lower()

        # Telemetry active gauge returns to zero on error
        assert _get_metric_val(telemetry.connectivity_active_checks) == 0.0

    finally:
        # 2. Release exclusive lock
        release_lock.set()
        holder_thread.join(timeout=5.0)

    # 3. Perform a valid write
    valid_obs = service.check(node.id)
    assert valid_obs.outcome == ConnectivityOutcome.CONNECTED

    # 4. Verify database integrity and telemetry
    with sqlite3.connect(db_path) as verify_conn:
        assert verify_conn.execute("PRAGMA integrity_check;").fetchall() == [("ok",)]
        assert verify_conn.execute("PRAGMA foreign_key_check;").fetchall() == []

    assert _get_metric_val(telemetry.connectivity_active_checks) == 0.0
    latest = conn_repo.latest(node.id)
    assert latest is not None
    assert latest.outcome == ConnectivityOutcome.CONNECTED


# ---------------------------------------------------------------------------
# Scenario E: Restore collision and preservation
# ---------------------------------------------------------------------------


def test_scenario_e_restore_collision_and_preservation(tmp_path: Path) -> None:
    """Pre-existing .pre_restore.bak snapshot triggers fail-closed error and preserves all files."""
    # 1. Create a valid disposable database
    source_db = tmp_path / "source.db"
    source_repo = SQLiteNodeRepository(source_db)
    source_repo.initialize()
    source_repo.add_node(NewNode("source-srv", "192.168.10.1", 22))

    backup_file = tmp_path / "valid_backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "target.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("active-target-srv", "192.168.10.2", 22))

    # 2. Create a pre-existing safety snapshot
    safety_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")
    snap_repo = SQLiteNodeRepository(safety_snapshot)
    snap_repo.initialize()
    snap_repo.add_node(NewNode("pre-existing-snapshot-srv", "192.168.10.3", 22))

    # 3. Record SHA-256 of both files
    target_sha_before = calculate_sha256(target_db)
    snap_sha_before = calculate_sha256(safety_snapshot)

    # 4. Attempt restore
    # 5. Verify PreRestoreSnapshotExistsError
    with pytest.raises(PreRestoreSnapshotExistsError) as exc_info:
        perform_restore(backup_file, target_db)

    assert "pre-restore safety snapshot already exists" in str(exc_info.value).lower()
    assert "operator inspection and recovery" in str(exc_info.value).lower()

    # 6. Verify both hashes remain strictly unchanged
    assert calculate_sha256(target_db) == target_sha_before
    assert calculate_sha256(safety_snapshot) == snap_sha_before

    # 7. Verify no staging or WAL mutation occurred
    staging_files = list(target_db.parent.glob("*.restoring.tmp"))
    assert len(staging_files) == 0

    # Verify data integrity of both files
    with sqlite3.connect(target_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["active-target-srv"]

    with sqlite3.connect(safety_snapshot) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["pre-existing-snapshot-srv"]
