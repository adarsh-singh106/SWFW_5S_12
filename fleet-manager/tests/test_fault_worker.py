"""Fault injection test suite for worker process failure, termination, and recovery.

Validates ProcessOperationExecutor and OperationService with real Windows child
processes under abnormal termination, forced kill, IPC output corruption, timeout,
and sequential failures. Asserts durable SQLite state transitions (UNCERTAIN vs FAILURE
vs TIMEOUT), telemetry return-to-zero, child reaping, and same-node capacity recovery.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import paramiko
import pytest

from fleet_manager.config import OperationLimits, SSHSettings
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.errors import (
    ConnectivityConfigurationError,
    OperationBusy,
    OperationInProgress,
    OperationUnavailable,
)
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.metrics.telemetry import Telemetry
from fleet_manager.operations.executor import ProcessOperationExecutor
from fleet_manager.operations.models import (
    OperationFailureCategory,
    OperationOutcome,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.service import OperationService

# ---------------------------------------------------------------------------
# Test worker script templates
# ---------------------------------------------------------------------------

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
    "stdout": "all systems normal\\n",
    "stderr": "",
    "output_truncated": False,
}
sys.stdout.write(json.dumps(output))
sys.stdout.flush()
"""

_EXIT_CODE_SCRIPT = """\
import sys, json

try:
    req = json.load(sys.stdin)
except Exception:
    pass

code = int(sys.argv[1]) if len(sys.argv) > 1 else 1
sys.exit(code)
"""

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

_OUTPUT_SCRIPT = """\
import sys, json

try:
    req = json.load(sys.stdin)
except Exception:
    pass

mode = sys.argv[1] if len(sys.argv) > 1 else "empty"
if mode == "empty":
    pass
elif mode == "malformed":
    sys.stdout.write("MALFORMED_NON_JSON_OUTPUT\\n")
elif mode == "truncated":
    sys.stdout.write('{"outcome": "SUCCESS", "exit_code":')
elif mode == "missing_outcome":
    sys.stdout.write('{"exit_code": 0, "stdout": "ok"}')
elif mode == "invalid_outcome":
    sys.stdout.write('{"outcome": "NONEXISTENT_STATE"}')
sys.stdout.flush()
sys.exit(0)
"""

_HANG_SCRIPT = """\
import sys, json, time

try:
    req = json.load(sys.stdin)
except Exception:
    pass

time.sleep(10.0)
"""

_PIPE_CLOSE_SCRIPT = """\
import sys

try:
    sys.stdin.close()
    sys.stdout.close()
except Exception:
    pass
sys.exit(0)
"""


# ---------------------------------------------------------------------------
# Test helpers and fixtures
# ---------------------------------------------------------------------------


def _make_worker_cmd(tmp_path: Path, script_code: str, *extra_args: str) -> tuple[str, ...]:
    """Write an isolated test worker script and return its command-line invocation."""
    script_file = tmp_path / f"test_worker_{uuid.uuid4().hex[:8]}.py"
    script_file.write_text(script_code, encoding="utf-8")
    return (sys.executable, str(script_file), *extra_args)


@contextmanager
def _readiness_listener() -> Iterator[tuple[socket.socket, int]]:
    """Ephemeral loopback TCP listener for deterministic child process synchronization."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5.0)
    port = listener.getsockname()[1]
    try:
        yield listener, port
    finally:
        listener.close()


def _accept_worker_ready(listener: socket.socket, timeout: float = 5.0) -> socket.socket:
    """Accept TCP connection from test worker and verify its READY token."""
    listener.settimeout(timeout)
    conn, _ = listener.accept()
    conn.settimeout(timeout)
    token = conn.recv(64)
    assert token.strip() == b"READY", f"Expected READY token from worker, got {token!r}"
    return conn


@pytest.fixture
def worker_env(
    tmp_path: Path,
) -> tuple[
    SQLiteNodeRepository,
    SQLiteConnectivityRepository,
    SQLiteOperationsRepository,
    Telemetry,
    Path,
    Path,
    SSHSettings,
    Node,
]:
    """Set up disposable schema-v3 SQLite database, telemetry, credentials, and registered node."""
    db_path = tmp_path / "fault_worker_test.db"
    inv_repo = SQLiteNodeRepository(db_path)
    inv_repo.initialize()

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    ops_repo = SQLiteOperationsRepository(db_path)
    ops_repo.initialize()

    telemetry = Telemetry()

    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer_key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"
    known_hosts_path.touch()

    settings = SSHSettings("test-operator", known_hosts_path, private_key_path)
    node = inv_repo.add_node(NewNode("fault-worker-node", "127.0.0.1", 2202))

    return (
        inv_repo,
        conn_repo,
        ops_repo,
        telemetry,
        known_hosts_path,
        private_key_path,
        settings,
        node,
    )


# ---------------------------------------------------------------------------
# Scenario A: Unexpected Non-Zero Worker Exit
# ---------------------------------------------------------------------------


def test_scenario_a_worker_exit_code_42_persists_uncertain(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Unexpected child crash (exit code 42) must map to UNCERTAIN and release capacity."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    worker_cmd = _make_worker_cmd(tmp_path, _EXIT_CODE_SCRIPT, "42")
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    with pytest.raises(OperationUnavailable, match="Worker exited with code 42"):
        service.execute(node.id, "system.uptime", {}, b"digest-exit-42")

    # Durable persistence: UNCERTAIN
    records = ops_repo.list_for_node(node.id)
    assert len(records) == 1
    record = records[0]
    assert record.outcome == OperationOutcome.UNCERTAIN
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE
    assert record.started_at is not None
    assert record.started_at is not None
    assert record.completed_at is not None
    assert record.completed_at >= record.started_at
    assert record.stderr == "Operation worker failed before a confirmed result"

    # Telemetry: active returned to zero, total recorded UNCERTAIN
    active = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active.value == 0.0

    total = next(
        s
        for s in telemetry.operations_total.collect()
        if s.labels.get("action") == "system.uptime" and s.labels.get("outcome") == "UNCERTAIN"
    )
    assert total.value == 1.0

    # Node admission slot released
    assert len(executor._active) == 0


def test_scenario_a_worker_exit_code_1_persists_uncertain(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Unexpected child failure (exit code 1) must map to UNCERTAIN and release capacity."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    worker_cmd = _make_worker_cmd(tmp_path, _EXIT_CODE_SCRIPT, "1")
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    with pytest.raises(OperationUnavailable, match="Worker exited with code 1"):
        service.execute(node.id, "system.uptime", {}, b"digest-exit-1")

    record = ops_repo.list_for_node(node.id)[0]
    assert record.outcome == OperationOutcome.UNCERTAIN
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE
    assert len(executor._active) == 0

    active = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active.value == 0.0


def test_scenario_a_worker_exit_code_2_persists_failure(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Exit code 2 (configuration error) must strictly map to FAILURE (never UNCERTAIN)."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    worker_cmd = _make_worker_cmd(tmp_path, _EXIT_CODE_SCRIPT, "2")
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    with pytest.raises(
        ConnectivityConfigurationError,
        match="SSH operator configuration is unavailable",
    ):
        service.execute(node.id, "system.uptime", {}, b"digest-exit-2")

    record = ops_repo.list_for_node(node.id)[0]
    assert record.outcome == OperationOutcome.FAILURE
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE
    assert len(executor._active) == 0

    active = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active.value == 0.0

    total = next(
        s
        for s in telemetry.operations_total.collect()
        if s.labels.get("action") == "system.uptime" and s.labels.get("outcome") == "FAILURE"
    )
    assert total.value == 1.0


def test_scenario_a_production_worker_configuration_error_exits_code_2(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Verify real production worker module exits with code 2 on configuration error."""
    inv_repo, _, ops_repo, telemetry, _, _, _, node = worker_env

    # Point settings to non-existent host key files
    broken_settings = SSHSettings(
        "operator",
        tmp_path / "nonexistent_known_hosts",
        tmp_path / "nonexistent_key",
    )
    # Default worker_command runs python -m fleet_manager.operations.worker
    executor = ProcessOperationExecutor(OperationLimits())
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=broken_settings,
        telemetry=telemetry,
    )

    with pytest.raises(
        ConnectivityConfigurationError,
        match="SSH operator configuration is unavailable",
    ):
        service.execute(node.id, "system.uptime", {}, b"digest-prod-worker-cfg")

    record = ops_repo.list_for_node(node.id)[0]
    assert record.outcome == OperationOutcome.FAILURE
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE
    assert len(executor._active) == 0


# ---------------------------------------------------------------------------
# Scenario B: External Forced Worker Termination
# ---------------------------------------------------------------------------


def test_scenario_b_external_forced_worker_termination(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """External process.kill() after admission must reconcile to UNCERTAIN and reap."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

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

        def run_service() -> None:
            nonlocal exec_error
            try:
                service.execute(node.id, "system.uptime", {}, b"digest-forced-kill")
            except Exception as exc:
                exec_error = exc

        service_thread = threading.Thread(target=run_service, name="service-kill-test-thread")
        service_thread.start()

        # Deterministic readiness barrier via ephemeral socket
        conn = _accept_worker_ready(listener, timeout=5.0)
        try:
            # 1. Verify RUNNING record exists while worker is active
            running_records = ops_repo.list_for_node(node.id)
            assert len(running_records) == 1
            assert running_records[0].outcome == OperationOutcome.RUNNING
            assert running_records[0].started_at is not None
            assert running_records[0].completed_at is None

            # 2. Verify active telemetry is 1.0
            active_samples = [
                s
                for s in telemetry.operations_active.collect()
                if s.labels.get("action") == "system.uptime"
            ]
            assert len(active_samples) == 1
            assert active_samples[0].value == 1.0

            # 3. Capture real child Popen handle
            assert node.id in executor._active
            child_proc = executor._active[node.id]
            assert child_proc.poll() is None, "Child process must be actively running"

            # 4. Invoke process.kill() from controlling thread (Windows TerminateProcess)
            child_proc.kill()
        finally:
            try:
                conn.close()
            except OSError:
                pass

        # 5. Join service execution thread
        service_thread.join(timeout=5.0)
        assert not service_thread.is_alive(), (
            "Service thread did not terminate within bounded deadline"
        )

    # 6. Verify parent execution observed abnormal termination
    assert isinstance(exec_error, OperationUnavailable)
    assert "Worker exited with code" in str(exec_error)

    # 7. Verify durable operation record is reconciled to UNCERTAIN
    records = ops_repo.list_for_node(node.id)
    assert len(records) == 1
    term_record = records[0]
    assert term_record.outcome == OperationOutcome.UNCERTAIN
    assert term_record.failure_category == OperationFailureCategory.UNAVAILABLE
    assert term_record.started_at is not None
    assert term_record.completed_at is not None
    assert term_record.completed_at >= term_record.started_at
    assert term_record.stderr == "Operation worker failed before a confirmed result"

    # 8. Verify telemetry returned to baseline
    active_after = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active_after.value == 0.0

    total_samples = [
        s
        for s in telemetry.operations_total.collect()
        if s.labels.get("action") == "system.uptime" and s.labels.get("outcome") == "UNCERTAIN"
    ]
    assert len(total_samples) == 1
    assert total_samples[0].value == 1.0

    # 9. Verify executor active registry is empty
    assert len(executor._active) == 0

    # 10. Verify process handle has exited and has been waited on
    assert child_proc.poll() is not None
    assert child_proc.wait(timeout=1.0) is not None


# ---------------------------------------------------------------------------
# Scenario C: Process Output or IPC Failure
# ---------------------------------------------------------------------------


def test_scenario_c_worker_exit_without_output_persists_uncertain(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Worker exiting cleanly without producing output maps to UNCERTAIN."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    worker_cmd = _make_worker_cmd(tmp_path, _OUTPUT_SCRIPT, "empty")
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    with pytest.raises(OperationUnavailable, match="Invalid response received from worker"):
        service.execute(node.id, "system.uptime", {}, b"digest-c-empty")

    record = ops_repo.list_for_node(node.id)[0]
    assert record.outcome == OperationOutcome.UNCERTAIN
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE
    assert len(executor._active) == 0

    active = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active.value == 0.0


def test_scenario_c_worker_malformed_non_json_output(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Worker producing non-JSON output maps to UNCERTAIN and releases state."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    worker_cmd = _make_worker_cmd(tmp_path, _OUTPUT_SCRIPT, "malformed")
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    with pytest.raises(OperationUnavailable, match="Invalid response received from worker"):
        service.execute(node.id, "system.uptime", {}, b"digest-c-malformed")

    record = ops_repo.list_for_node(node.id)[0]
    assert record.outcome == OperationOutcome.UNCERTAIN
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE
    assert len(executor._active) == 0


def test_scenario_c_worker_truncated_json_output(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Worker producing incomplete truncated JSON maps to UNCERTAIN."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    worker_cmd = _make_worker_cmd(tmp_path, _OUTPUT_SCRIPT, "truncated")
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    with pytest.raises(OperationUnavailable, match="Invalid response received from worker"):
        service.execute(node.id, "system.uptime", {}, b"digest-c-truncated")

    record = ops_repo.list_for_node(node.id)[0]
    assert record.outcome == OperationOutcome.UNCERTAIN
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE
    assert len(executor._active) == 0


def test_scenario_c_worker_missing_outcome_field(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Worker output omitting mandatory 'outcome' field maps to UNCERTAIN."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    worker_cmd = _make_worker_cmd(tmp_path, _OUTPUT_SCRIPT, "missing_outcome")
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    with pytest.raises(OperationUnavailable, match="Invalid response received from worker"):
        service.execute(node.id, "system.uptime", {}, b"digest-c-missing-key")

    record = ops_repo.list_for_node(node.id)[0]
    assert record.outcome == OperationOutcome.UNCERTAIN
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE


def test_scenario_c_worker_invalid_outcome_enum(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Worker output returning unknown outcome enum string maps to UNCERTAIN."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    worker_cmd = _make_worker_cmd(tmp_path, _OUTPUT_SCRIPT, "invalid_outcome")
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    with pytest.raises(OperationUnavailable, match="Invalid response received from worker"):
        service.execute(node.id, "system.uptime", {}, b"digest-c-bad-enum")

    record = ops_repo.list_for_node(node.id)[0]
    assert record.outcome == OperationOutcome.UNCERTAIN
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE


def test_scenario_c_worker_pipe_closure_investigation_windows(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Document and verify realistic Windows pipe closure during worker execution.

    On Windows Python subprocess, when a child closes stdin/stdout and terminates,
    the OS pipe write buffer cleanly closes without raising raw BrokenPipeError.
    The parent receives empty output (EOF) and cleanly maps the result to
    OperationUnavailable with UNCERTAIN outcome.
    """
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    worker_cmd = _make_worker_cmd(tmp_path, _PIPE_CLOSE_SCRIPT)
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    with pytest.raises(OperationUnavailable, match="Invalid response received from worker"):
        service.execute(node.id, "system.uptime", {}, b"digest-pipe-close")

    record = ops_repo.list_for_node(node.id)[0]
    assert record.outcome == OperationOutcome.UNCERTAIN
    assert record.failure_category == OperationFailureCategory.UNAVAILABLE
    assert len(executor._active) == 0

    active = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active.value == 0.0


# ---------------------------------------------------------------------------
# Scenario D: Same-Node Capacity Recovery
# ---------------------------------------------------------------------------


def test_scenario_d_same_node_capacity_recovery_after_worker_crash(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Same node admits subsequent operation after an unexpected worker crash."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    crash_cmd = _make_worker_cmd(tmp_path, _EXIT_CODE_SCRIPT, "42")
    executor = ProcessOperationExecutor(OperationLimits(), worker_command=crash_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    # 1. First execution fails with abnormal worker exit
    with pytest.raises(OperationUnavailable):
        service.execute(node.id, "system.uptime", {}, b"digest-fail-1")

    # Verify no stale node ID or process remains in active registry
    assert node.id not in executor._active
    assert len(executor._active) == 0

    # 2. Reconfigure executor to use healthy test worker
    success_cmd = _make_worker_cmd(tmp_path, _SUCCESS_SCRIPT)
    executor._command = success_cmd

    # 3. Second execution against the exact same node must succeed
    rec_success = service.execute(node.id, "system.uptime", {}, b"digest-success-after-crash")
    assert rec_success.outcome == OperationOutcome.SUCCESS
    assert rec_success.exit_code == 0
    assert rec_success.stdout == "all systems normal\n"
    assert rec_success.started_at is not None
    assert rec_success.completed_at is not None
    assert rec_success.completed_at >= rec_success.started_at

    # Registry and active telemetry baseline
    assert len(executor._active) == 0
    active = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active.value == 0.0


def test_scenario_d_same_node_capacity_recovery_after_forced_kill(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Same node admits subsequent operation after external forced worker kill."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

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

        def run_failing_service() -> None:
            try:
                service.execute(node.id, "system.uptime", {}, b"digest-kill-rec")
            except OperationUnavailable:
                pass

        t = threading.Thread(target=run_failing_service, daemon=True)
        t.start()

        conn = _accept_worker_ready(listener)
        try:
            child_proc = executor._active[node.id]
            child_proc.kill()
        finally:
            conn.close()
        t.join(timeout=5.0)

    assert node.id not in executor._active
    assert len(executor._active) == 0

    # Execute subsequent healthy operation on same node
    executor._command = _make_worker_cmd(tmp_path, _SUCCESS_SCRIPT)
    rec_success = service.execute(node.id, "system.uptime", {}, b"digest-success-after-kill")
    assert rec_success.outcome == OperationOutcome.SUCCESS
    assert len(executor._active) == 0


def test_scenario_d_same_node_in_progress_exclusion_during_active_execution(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Concurrent operation on same node is rejected with OperationInProgress while active."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

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

        def run_active_op() -> None:
            try:
                service.execute(node.id, "system.uptime", {}, b"digest-active-1")
            except OperationUnavailable:
                pass

        service_thread = threading.Thread(
            target=run_active_op,
            daemon=True,
        )
        service_thread.start()

        conn = _accept_worker_ready(listener)
        try:
            # While active, second request against same node must raise OperationInProgress
            with pytest.raises(
                OperationInProgress,
                match=f"Operation already active for node {node.id}",
            ):
                service.execute(node.id, "system.uptime", {}, b"digest-active-2")

            # Verify no second record was created
            records = ops_repo.list_for_node(node.id)
            assert len(records) == 1

            # Kill the first worker
            child_proc = executor._active[node.id]
            child_proc.kill()
        finally:
            conn.close()

        service_thread.join(timeout=5.0)

    # After failure, capacity is recovered
    assert len(executor._active) == 0
    executor._command = _make_worker_cmd(tmp_path, _SUCCESS_SCRIPT)
    rec_after = service.execute(node.id, "system.uptime", {}, b"digest-after-exclusion")
    assert rec_after.outcome == OperationOutcome.SUCCESS


# ---------------------------------------------------------------------------
# Scenario E: Timeout Regression
# ---------------------------------------------------------------------------


def test_scenario_e_timeout_regression_kills_and_reaps(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Worker exceeding total timeout must be killed, reaped, and persisted as TIMEOUT."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    hang_cmd = _make_worker_cmd(tmp_path, _HANG_SCRIPT)
    limits = OperationLimits(total_timeout_seconds=0.5)
    executor = ProcessOperationExecutor(limits, worker_command=hang_cmd)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    start_time = time.monotonic()
    # Does not raise; returns TIMEOUT OperationRecord
    record = service.execute(node.id, "system.uptime", {}, b"digest-timeout-test")
    elapsed = time.monotonic() - start_time

    assert elapsed < 3.0, f"Timeout took unexpectedly long: {elapsed:.2f}s"
    assert record.outcome == OperationOutcome.TIMEOUT
    assert record.failure_category == OperationFailureCategory.TIMEOUT
    assert record.exit_code is None
    assert "Operation timed out after 0.5s" in (record.stderr or "")
    assert record.started_at is not None
    assert record.completed_at is not None
    assert record.completed_at >= record.started_at

    # Durable persistence in SQLite
    persisted = ops_repo.get(record.id)
    assert persisted is not None
    assert persisted.outcome == OperationOutcome.TIMEOUT
    assert persisted.failure_category == OperationFailureCategory.TIMEOUT

    # Telemetry verified
    active = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active.value == 0.0

    total = next(
        s
        for s in telemetry.operations_total.collect()
        if s.labels.get("action") == "system.uptime" and s.labels.get("outcome") == "TIMEOUT"
    )
    assert total.value == 1.0

    # Executor registry clear and capacity available
    assert len(executor._active) == 0
    executor._command = _make_worker_cmd(tmp_path, _SUCCESS_SCRIPT)
    rec_after = service.execute(node.id, "system.uptime", {}, b"digest-after-timeout")
    assert rec_after.outcome == OperationOutcome.SUCCESS


# ---------------------------------------------------------------------------
# Scenario F: Repeated Worker Failures
# ---------------------------------------------------------------------------


def test_scenario_f_repeated_worker_failures_bounded_cleanup(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """Run a bounded sequence of 5 distinct worker failures, tracking processes and cleanup."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    # 1. Failure 1: Exit code 1
    cmd_exit1 = _make_worker_cmd(tmp_path, _EXIT_CODE_SCRIPT, "1")
    exec_1 = ProcessOperationExecutor(OperationLimits(), worker_command=cmd_exit1)
    svc_1 = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=exec_1,
        ssh_settings=settings,
        telemetry=telemetry,
    )
    with pytest.raises(OperationUnavailable, match="Worker exited with code 1"):
        svc_1.execute(node.id, "system.uptime", {}, b"digest-seq-1")
    assert len(exec_1._active) == 0

    # 2. Failure 2: Exit code 2 (configuration error)
    cmd_exit2 = _make_worker_cmd(tmp_path, _EXIT_CODE_SCRIPT, "2")
    exec_2 = ProcessOperationExecutor(OperationLimits(), worker_command=cmd_exit2)
    svc_2 = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=exec_2,
        ssh_settings=settings,
        telemetry=telemetry,
    )
    with pytest.raises(ConnectivityConfigurationError):
        svc_2.execute(node.id, "system.uptime", {}, b"digest-seq-2")
    assert len(exec_2._active) == 0

    # 3. Failure 3: Truncated JSON
    cmd_trunc = _make_worker_cmd(tmp_path, _OUTPUT_SCRIPT, "truncated")
    exec_3 = ProcessOperationExecutor(OperationLimits(), worker_command=cmd_trunc)
    svc_3 = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=exec_3,
        ssh_settings=settings,
        telemetry=telemetry,
    )
    with pytest.raises(OperationUnavailable, match="Invalid response received"):
        svc_3.execute(node.id, "system.uptime", {}, b"digest-seq-3")
    assert len(exec_3._active) == 0

    # 4. Failure 4: External forced kill
    with _readiness_listener() as (listener, port):
        cmd_kill = _make_worker_cmd(tmp_path, _SYNC_WAIT_SCRIPT, str(port))
        exec_4 = ProcessOperationExecutor(OperationLimits(), worker_command=cmd_kill)
        svc_4 = OperationService(
            inventory_repository=inv_repo,
            operations_repository=ops_repo,
            executor=exec_4,
            ssh_settings=settings,
            telemetry=telemetry,
        )

        def run_kill_op() -> None:
            try:
                svc_4.execute(node.id, "system.uptime", {}, b"digest-seq-4")
            except OperationUnavailable:
                pass

        t = threading.Thread(target=run_kill_op, daemon=True)
        t.start()
        conn = _accept_worker_ready(listener)
        try:
            proc_4 = exec_4._active[node.id]
            proc_4.kill()
        finally:
            conn.close()
        t.join(timeout=5.0)

        assert proc_4.poll() is not None
        assert proc_4.wait(timeout=1.0) is not None
        assert len(exec_4._active) == 0

    # 5. Failure 5: Timeout
    cmd_timeout = _make_worker_cmd(tmp_path, _HANG_SCRIPT)
    exec_5 = ProcessOperationExecutor(
        OperationLimits(total_timeout_seconds=0.3), worker_command=cmd_timeout
    )
    svc_5 = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=exec_5,
        ssh_settings=settings,
        telemetry=telemetry,
    )
    rec_5 = svc_5.execute(node.id, "system.uptime", {}, b"digest-seq-5")
    assert rec_5.outcome == OperationOutcome.TIMEOUT
    assert len(exec_5._active) == 0

    # Baseline verification across all 5 sequential failures
    active = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active.value == 0.0

    # 6. Verify subsequent healthy execution executes normally
    cmd_success = _make_worker_cmd(tmp_path, _SUCCESS_SCRIPT)
    exec_final = ProcessOperationExecutor(OperationLimits(), worker_command=cmd_success)
    svc_final = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=exec_final,
        ssh_settings=settings,
        telemetry=telemetry,
    )
    rec_final = svc_final.execute(node.id, "system.uptime", {}, b"digest-seq-final")
    assert rec_final.outcome == OperationOutcome.SUCCESS
    assert rec_final.exit_code == 0
    assert len(exec_final._active) == 0


# ---------------------------------------------------------------------------
# Additional Lifecycle Edge Cases
# ---------------------------------------------------------------------------


def test_executor_close_terminates_active_workers_and_rejects_new_work(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """ProcessOperationExecutor.close() kills active workers and rejects new runs."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node = worker_env

    with _readiness_listener() as (listener, port):
        worker_cmd = _make_worker_cmd(tmp_path, _SYNC_WAIT_SCRIPT, str(port))
        executor = ProcessOperationExecutor(OperationLimits(), worker_command=worker_cmd)

        def run_target() -> None:
            try:
                executor.run(node, "uptime", settings)
            except OperationUnavailable:
                pass

        t = threading.Thread(target=run_target, daemon=True)
        t.start()

        conn = _accept_worker_ready(listener)
        try:
            proc = executor._active[node.id]
            assert proc.poll() is None

            # Close executor while child is actively waiting
            executor.close()
        finally:
            conn.close()

        t.join(timeout=5.0)

        # Worker must have been killed and reaped
        assert proc.poll() is not None
        assert proc.wait(timeout=1.0) is not None

    # New operations must be rejected with OperationUnavailable
    with pytest.raises(OperationUnavailable, match="Executor is shutting down"):
        executor.run(node, "uptime", settings)


def test_executor_capacity_exhaustion_does_not_corrupt_state(
    worker_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        SSHSettings,
        Node,
    ],
    tmp_path: Path,
) -> None:
    """When executor capacity is exhausted, excess request is rejected with OperationBusy."""
    inv_repo, _, ops_repo, telemetry, _, _, settings, node1 = worker_env
    node2 = inv_repo.add_node(NewNode("second-node", "127.0.0.1", 2203))

    with _readiness_listener() as (listener, port):
        worker_cmd = _make_worker_cmd(tmp_path, _SYNC_WAIT_SCRIPT, str(port))
        # Set max_concurrent to 1
        limits = OperationLimits(max_concurrent=1)
        executor = ProcessOperationExecutor(limits, worker_command=worker_cmd)
        service = OperationService(
            inventory_repository=inv_repo,
            operations_repository=ops_repo,
            executor=executor,
            ssh_settings=settings,
            telemetry=telemetry,
        )

        def run_busy_op() -> None:
            try:
                service.execute(node1.id, "system.uptime", {}, b"digest-node1")
            except OperationUnavailable:
                pass

        t = threading.Thread(
            target=run_busy_op,
            daemon=True,
        )
        t.start()

        conn = _accept_worker_ready(listener)
        try:
            # While node 1 occupies the single capacity slot, node 2 is rejected with OperationBusy
            with pytest.raises(OperationBusy, match="Operation execution capacity is exhausted"):
                service.execute(node2.id, "system.uptime", {}, b"digest-node2")

            # Verify no record created for node 2
            assert len(ops_repo.list_for_node(node2.id)) == 0

            # Release node 1
            proc = executor._active[node1.id]
            proc.kill()
        finally:
            conn.close()

        t.join(timeout=5.0)

    # After slot frees, node 2 is admitted normally
    executor._command = _make_worker_cmd(tmp_path, _SUCCESS_SCRIPT)
    rec2 = service.execute(node2.id, "system.uptime", {}, b"digest-node2-admit")
    assert rec2.outcome == OperationOutcome.SUCCESS
