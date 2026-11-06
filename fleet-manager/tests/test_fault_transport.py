"""End-to-end SSH transport and process-backed fault injection test suite.

Validates failure classification, state transitions (FAILURE vs UNCERTAIN),
durable SQLite persistence, active telemetry return-to-zero, and child worker
reap guarantees using ProcessOperationExecutor and ProcessSSHExecutor over
ephemeral 127.0.0.1 loopback sockets.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
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

from fleet_manager.config import OperationLimits, SSHSettings
from fleet_manager.connectivity.executor import ProcessSSHExecutor
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.inventory.models import NewNode, Node, ObservationState
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.metrics.telemetry import Telemetry
from fleet_manager.operations.executor import ProcessOperationExecutor
from fleet_manager.operations.models import (
    OperationFailureCategory,
    OperationOutcome,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.service import OperationService
from fleet_manager.operations.transport import ParamikoOperationTransport


def _write_known_hosts(path: Path, port: int, key: paramiko.PKey) -> None:
    """Format and write a single known_hosts entry for loopback testing."""
    path.write_text(
        f"[127.0.0.1]:{port} {key.get_name()} {key.get_base64()}\n",
        encoding="ascii",
    )


@contextmanager
def _ephemeral_closed_port() -> Iterator[int]:
    """Bind and immediately close an ephemeral socket to guarantee connection refused."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    yield port


@contextmanager
def _banner_stall_server() -> Iterator[int]:
    """Accept TCP connection on loopback but withhold SSH protocol banner."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    stop_event = threading.Event()
    client_conn: socket.socket | None = None
    conn_lock = threading.Lock()

    def serve() -> None:
        nonlocal client_conn
        try:
            conn, _ = listener.accept()
            with conn_lock:
                client_conn = conn
            stop_event.wait(timeout=5.0)
        except OSError:
            pass
        finally:
            with conn_lock:
                if client_conn is not None:
                    try:
                        client_conn.close()
                    except OSError:
                        pass

    worker_thread = threading.Thread(target=serve, daemon=True)
    worker_thread.start()
    try:
        yield port
    finally:
        stop_event.set()
        listener.close()
        with conn_lock:
            if client_conn is not None:
                try:
                    client_conn.close()
                except OSError:
                    pass
        worker_thread.join(timeout=2.0)


@contextmanager
def _loopback_fault_server(
    host_key: paramiko.PKey,
    accepted_key: paramiko.PKey,
    *,
    disconnect_before_dispatch: bool = False,
    disconnect_after_dispatch: bool = False,
    exec_landmark_event: threading.Event | None = None,
    exec_handler: Callable[[str], tuple[int, str, str]] | None = None,
) -> Iterator[int]:
    """Paramiko loopback SSH server with controlled fault injection landmarks."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    stop_event = threading.Event()
    transports: list[paramiko.Transport] = []
    transports_lock = threading.Lock()

    class _FaultServerInterface(paramiko.ServerInterface):
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
                if disconnect_before_dispatch:
                    self.transport.close()
                    return int(OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED)
                return int(OPEN_SUCCEEDED)
            return int(OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED)

        def check_channel_exec_request(self, channel: paramiko.Channel, command: bytes) -> bool:
            if exec_landmark_event is not None:
                exec_landmark_event.set()

            if disconnect_after_dispatch:

                def drop_after_dispatch() -> None:
                    time.sleep(0.04)
                    self.transport.close()
                    try:
                        channel.close()
                    except Exception:
                        pass

                threading.Thread(target=drop_after_dispatch, daemon=True).start()
                return True

            cmd_str = command.decode("utf-8")

            def handle_exec() -> None:
                try:
                    if exec_handler is not None:
                        exit_code, stdout, stderr = exec_handler(cmd_str)
                    else:
                        exit_code, stdout, stderr = 0, "ok\n", ""
                    if stdout:
                        channel.send(stdout.encode("utf-8"))
                    if stderr:
                        channel.send_stderr(stderr.encode("utf-8"))
                    channel.send_exit_status(exit_code)
                    time.sleep(0.04)
                    channel.close()
                except Exception:
                    pass

            threading.Thread(target=handle_exec, daemon=True).start()
            return True

    def handle_client(conn: socket.socket) -> None:
        with conn:
            transport = paramiko.Transport(conn)
            with transports_lock:
                transports.append(transport)
            try:
                transport.add_server_key(host_key)
                transport.start_server(server=_FaultServerInterface(transport))
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
                threading.Thread(target=handle_client, args=(conn,), daemon=True).start()
            except TimeoutError:
                continue
            except OSError:
                break

    worker_thread = threading.Thread(target=serve, daemon=True)
    worker_thread.start()
    try:
        yield port
    finally:
        stop_event.set()
        listener.close()
        worker_thread.join(timeout=2.0)
        with transports_lock:
            for t in transports:
                try:
                    t.close()
                except Exception:
                    pass


@pytest.fixture
def fault_env(
    tmp_path: Path,
) -> tuple[
    SQLiteNodeRepository,
    SQLiteConnectivityRepository,
    SQLiteOperationsRepository,
    Telemetry,
    Path,
    Path,
    paramiko.PKey,
]:
    """Set up disposable SQLite database, telemetry, and client keypair."""
    db_path = tmp_path / "fault_test.db"
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

    return (
        inv_repo,
        conn_repo,
        ops_repo,
        telemetry,
        known_hosts_path,
        private_key_path,
        client_key,
    )


# ---------------------------------------------------------------------------
# Scenario A: Process-Backed Connection Refused
# ---------------------------------------------------------------------------


def test_direct_operation_connection_refused(
    fault_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        paramiko.PKey,
    ],
) -> None:
    """Direct ParamikoOperationTransport on a closed loopback port returns CONNECTION_REFUSED."""
    _, _, _, _, known_hosts_path, private_key_path, _ = fault_env

    with _ephemeral_closed_port() as port:
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
        transport = ParamikoOperationTransport()
        node = Node(1, "direct-refused", "127.0.0.1", port, ObservationState.NOT_CHECKED)

        result = transport.execute(node, "uptime", settings)

        assert result.outcome == OperationOutcome.FAILURE
        assert result.failure_category == OperationFailureCategory.CONNECTION_REFUSED
        assert result.exit_code is None
        assert result.stderr == "Connection refused by remote host"
        assert not result.output_truncated


def test_process_backed_connection_refused(
    fault_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        paramiko.PKey,
    ],
) -> None:
    """Worker connects to a closed port;
    validates exact CONNECTION_REFUSED classification and cleanup.
    """
    (
        inv_repo,
        _,
        ops_repo,
        telemetry,
        known_hosts_path,
        private_key_path,
        _,
    ) = fault_env

    with _ephemeral_closed_port() as port:
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
        executor = ProcessOperationExecutor(OperationLimits(max_concurrent=2))
        service = OperationService(
            inventory_repository=inv_repo,
            operations_repository=ops_repo,
            executor=executor,
            ssh_settings=settings,
            telemetry=telemetry,
        )

        node = inv_repo.add_node(NewNode("refused-node", "127.0.0.1", port))
        record = service.execute(
            node_id=node.id,
            action="system.uptime",
            arguments={},
            operator_digest=b"test-digest-refused",
        )

        # Verified FAILURE classification and exact CONNECTION_REFUSED category
        assert record.outcome == OperationOutcome.FAILURE
        assert record.failure_category == OperationFailureCategory.CONNECTION_REFUSED
        assert record.exit_code is None
        assert record.completed_at is not None

        # Verified durable SQLite terminal state
        persisted = ops_repo.get(record.id)
        assert persisted is not None
        assert persisted.outcome == OperationOutcome.FAILURE
        assert persisted.failure_category == OperationFailureCategory.CONNECTION_REFUSED

        # Verified telemetry active gauge reset to 0
        samples = telemetry.operations_active.collect()
        active = next(s for s in samples if s.labels.get("action") == "system.uptime")
        assert active.value == 0.0

        # Verified worker cleanup and capacity release
        assert len(executor._active) == 0

        # Verify capacity immediately usable by another execution
        # (will fail fast on the same closed port, proving no 429/409 lockups)
        second_record = service.execute(
            node_id=node.id,
            action="system.uptime",
            arguments={},
            operator_digest=b"test-digest-refused-repeat",
        )
        assert second_record.outcome == OperationOutcome.FAILURE
        assert second_record.failure_category == OperationFailureCategory.CONNECTION_REFUSED
        assert len(executor._active) == 0


# ---------------------------------------------------------------------------
# Scenario B: Process-Backed SSH Banner Timeout
# ---------------------------------------------------------------------------


def test_process_backed_ssh_banner_timeout(
    fault_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        paramiko.PKey,
    ],
) -> None:
    """Worker connects to stalled TCP server; verifies banner timeout and bounded run."""
    (
        inv_repo,
        _,
        ops_repo,
        telemetry,
        known_hosts_path,
        private_key_path,
        _,
    ) = fault_env

    with _banner_stall_server() as port:
        # Configure short 0.5s banner timeout with 2.0s connect timeout
        settings = SSHSettings(
            "fleet-observer",
            known_hosts_path,
            private_key_path,
            connect_timeout_seconds=2.0,
            banner_timeout_seconds=0.5,
        )
        executor = ProcessOperationExecutor(OperationLimits(max_concurrent=2))
        service = OperationService(
            inventory_repository=inv_repo,
            operations_repository=ops_repo,
            executor=executor,
            ssh_settings=settings,
            telemetry=telemetry,
        )

        node = inv_repo.add_node(NewNode("banner-timeout-node", "127.0.0.1", port))
        start_time = time.monotonic()

        record = service.execute(
            node_id=node.id,
            action="system.uptime",
            arguments={},
            operator_digest=b"test-digest-banner-timeout",
        )
        elapsed = time.monotonic() - start_time

        # Ensure bounded execution: finishes close to banner_timeout, well before watchdog
        assert elapsed < 3.0, f"Banner timeout took too long: {elapsed}s"

        # Verified outcome and failure category
        assert record.outcome == OperationOutcome.FAILURE
        assert record.failure_category == OperationFailureCategory.UNAVAILABLE
        assert "SSH protocol failure before command dispatch" in (record.stderr or "")

        # Verified durable SQLite state
        persisted = ops_repo.get(record.id)
        assert persisted is not None
        assert persisted.outcome == OperationOutcome.FAILURE

        # Telemetry active gauge reset
        active = next(
            s
            for s in telemetry.operations_active.collect()
            if s.labels.get("action") == "system.uptime"
        )
        assert active.value == 0.0

        # Child worker terminated and reaped
        assert len(executor._active) == 0


# ---------------------------------------------------------------------------
# Scenario C: Process-Backed Host-Key Security Lifecycle
# ---------------------------------------------------------------------------


def test_process_backed_host_key_security_lifecycle(
    fault_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        paramiko.PKey,
    ],
) -> None:
    """Verify strict host-key rejection (unknown, mismatch) and acceptance of known key."""
    (
        inv_repo,
        _,
        ops_repo,
        telemetry,
        known_hosts_path,
        private_key_path,
        client_key,
    ) = fault_env

    server_host_key = paramiko.RSAKey.generate(2048)
    other_host_key = paramiko.RSAKey.generate(2048)

    with _loopback_fault_server(server_host_key, client_key) as port:
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
        executor = ProcessOperationExecutor(OperationLimits(max_concurrent=2))
        service = OperationService(
            inventory_repository=inv_repo,
            operations_repository=ops_repo,
            executor=executor,
            ssh_settings=settings,
            telemetry=telemetry,
        )
        node = inv_repo.add_node(NewNode("security-node", "127.0.0.1", port))

        # 1. Unknown host key (known_hosts is empty)
        known_hosts_path.write_text("", encoding="ascii")
        rec_unknown = service.execute(node.id, "system.uptime", {}, b"test-digest-unknown")
        assert rec_unknown.outcome == OperationOutcome.FAILURE
        assert rec_unknown.failure_category == OperationFailureCategory.HOST_KEY_UNKNOWN
        assert known_hosts_path.read_text(encoding="ascii") == "", (
            "known_hosts must not be auto-mutated"
        )
        assert len(executor._active) == 0

        # 2. Mismatched host key
        _write_known_hosts(known_hosts_path, port, other_host_key)
        rec_mismatch = service.execute(node.id, "system.uptime", {}, b"test-digest-mismatch")
        assert rec_mismatch.outcome == OperationOutcome.FAILURE
        assert rec_mismatch.failure_category == OperationFailureCategory.HOST_KEY_MISMATCH
        assert len(executor._active) == 0

        # 3. Correct known host key
        _write_known_hosts(known_hosts_path, port, server_host_key)
        rec_success = service.execute(node.id, "system.uptime", {}, b"test-digest-success")
        assert rec_success.outcome == OperationOutcome.SUCCESS
        assert rec_success.exit_code == 0
        assert rec_success.stdout == "ok\n"
        assert len(executor._active) == 0

        # Verify active gauge returned to zero
        active = next(
            s
            for s in telemetry.operations_active.collect()
            if s.labels.get("action") == "system.uptime"
        )
        assert active.value == 0.0


# ---------------------------------------------------------------------------
# Scenario D: Disconnect Before Remote Command Dispatch
# ---------------------------------------------------------------------------


def test_process_backed_disconnect_before_dispatch(
    fault_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        paramiko.PKey,
    ],
) -> None:
    """Disconnect before exec_command must strictly map to FAILURE (UNAVAILABLE)."""
    (
        inv_repo,
        _,
        ops_repo,
        telemetry,
        known_hosts_path,
        private_key_path,
        client_key,
    ) = fault_env

    server_key = paramiko.RSAKey.generate(2048)

    with _loopback_fault_server(server_key, client_key, disconnect_before_dispatch=True) as port:
        _write_known_hosts(known_hosts_path, port, server_key)
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
        executor = ProcessOperationExecutor(OperationLimits(max_concurrent=2))
        service = OperationService(
            inventory_repository=inv_repo,
            operations_repository=ops_repo,
            executor=executor,
            ssh_settings=settings,
            telemetry=telemetry,
        )
        node = inv_repo.add_node(NewNode("pre-dispatch-node", "127.0.0.1", port))

        record = service.execute(node.id, "system.uptime", {}, b"test-digest-pre-dispatch")

        # Must be FAILURE, NEVER UNCERTAIN (command was never sent)
        assert record.outcome == OperationOutcome.FAILURE
        assert record.failure_category == OperationFailureCategory.UNAVAILABLE
        assert record.exit_code is None
        assert record.completed_at is not None

        # Verify SQLite terminal state
        persisted = ops_repo.get(record.id)
        assert persisted is not None
        assert persisted.outcome == OperationOutcome.FAILURE

        # Telemetry active gauge reset
        active = next(
            s
            for s in telemetry.operations_active.collect()
            if s.labels.get("action") == "system.uptime"
        )
        assert active.value == 0.0
        assert len(executor._active) == 0


# ---------------------------------------------------------------------------
# Scenario E: Disconnect After Remote Command Dispatch
# ---------------------------------------------------------------------------


def test_process_backed_disconnect_after_dispatch_landmark(
    fault_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        paramiko.PKey,
    ],
) -> None:
    """Disconnect after exec request confirmed must strictly map to UNCERTAIN."""
    (
        inv_repo,
        _,
        ops_repo,
        telemetry,
        known_hosts_path,
        private_key_path,
        client_key,
    ) = fault_env

    server_key = paramiko.RSAKey.generate(2048)
    exec_landmark = threading.Event()

    with _loopback_fault_server(
        server_key,
        client_key,
        disconnect_after_dispatch=True,
        exec_landmark_event=exec_landmark,
    ) as port:
        _write_known_hosts(known_hosts_path, port, server_key)
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
        executor = ProcessOperationExecutor(OperationLimits(max_concurrent=2))
        service = OperationService(
            inventory_repository=inv_repo,
            operations_repository=ops_repo,
            executor=executor,
            ssh_settings=settings,
            telemetry=telemetry,
        )
        node = inv_repo.add_node(NewNode("post-dispatch-node", "127.0.0.1", port))

        record = service.execute(node.id, "system.uptime", {}, b"test-digest-post-dispatch")

        # Verify the actual dispatch landmark was established by the server
        assert exec_landmark.is_set(), "Server never received exec request landmark"

        # Must be UNCERTAIN (command was sent before connection dropped)
        assert record.outcome == OperationOutcome.UNCERTAIN
        assert record.failure_category == OperationFailureCategory.TRANSPORT_ERROR
        assert record.exit_code is None
        assert record.completed_at is not None

        # Verify SQLite terminal state
        persisted = ops_repo.get(record.id)
        assert persisted is not None
        assert persisted.outcome == OperationOutcome.UNCERTAIN
        assert persisted.failure_category == OperationFailureCategory.TRANSPORT_ERROR

        # Telemetry verification: active returns to 0, total increments UNCERTAIN
        active = next(
            s
            for s in telemetry.operations_active.collect()
            if s.labels.get("action") == "system.uptime"
        )
        assert active.value == 0.0

        uncertain_metric = 'fleet_operations_total{action="system.uptime",outcome="UNCERTAIN"} 1.0'
        assert uncertain_metric in telemetry.render()
        assert len(executor._active) == 0


# ---------------------------------------------------------------------------
# Scenario F: Process-Backed Connectivity Failures
# ---------------------------------------------------------------------------


def test_process_backed_connectivity_failures(
    fault_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        paramiko.PKey,
    ],
) -> None:
    """Verify ProcessSSHExecutor connectivity checks across refused, host-key, and timeout."""
    (
        inv_repo,
        conn_repo,
        _,
        telemetry,
        known_hosts_path,
        private_key_path,
        client_key,
    ) = fault_env

    executor = ProcessSSHExecutor(
        OperationLimits(max_concurrent=2)  # type: ignore[arg-type]
    )
    settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
    service = ConnectivityService(
        inventory=inv_repo,
        observations=conn_repo,
        executor=executor,
        settings=settings,
        telemetry=telemetry,
    )

    # 1. Connection Refused
    with _ephemeral_closed_port() as port_refused:
        node_refused = inv_repo.add_node(NewNode("conn-refused", "127.0.0.1", port_refused))
        obs_refused = service.check(node_refused.id)
        assert obs_refused.outcome == ConnectivityOutcome.CONNECTION_REFUSED
        assert obs_refused.error_category == ConnectivityOutcome.CONNECTION_REFUSED
        # Persisted in SQLite
        latest_refused = conn_repo.latest(node_refused.id)
        assert latest_refused is not None
        assert latest_refused.outcome == ConnectivityOutcome.CONNECTION_REFUSED

    # 2. Host-Key Unknown
    server_key = paramiko.RSAKey.generate(2048)
    other_key = paramiko.RSAKey.generate(2048)
    with _loopback_fault_server(server_key, client_key) as port_srv:
        known_hosts_path.write_text("", encoding="ascii")
        node_srv = inv_repo.add_node(NewNode("conn-unknown", "127.0.0.1", port_srv))
        obs_unknown = service.check(node_srv.id)
        assert obs_unknown.outcome == ConnectivityOutcome.HOST_KEY_UNKNOWN
        assert obs_unknown.error_category == ConnectivityOutcome.HOST_KEY_UNKNOWN

        # 3. Host-Key Mismatch
        _write_known_hosts(known_hosts_path, port_srv, other_key)
        obs_mismatch = service.check(node_srv.id)
        assert obs_mismatch.outcome == ConnectivityOutcome.HOST_KEY_MISMATCH
        assert obs_mismatch.error_category == ConnectivityOutcome.HOST_KEY_MISMATCH

    # 4. Banner Timeout
    with _banner_stall_server() as port_stall:
        settings_stall = SSHSettings(
            "fleet-observer",
            known_hosts_path,
            private_key_path,
            connect_timeout_seconds=2.0,
            banner_timeout_seconds=0.5,
        )
        service_stall = ConnectivityService(
            inventory=inv_repo,
            observations=conn_repo,
            executor=executor,
            settings=settings_stall,
            telemetry=telemetry,
        )
        node_stall = inv_repo.add_node(NewNode("conn-stall", "127.0.0.1", port_stall))
        obs_stall = service_stall.check(node_stall.id)
        assert obs_stall.outcome == ConnectivityOutcome.TIMEOUT
        assert obs_stall.error_category == ConnectivityOutcome.TIMEOUT
        latest_stall = conn_repo.latest(node_stall.id)
        assert latest_stall is not None
        assert latest_stall.outcome == ConnectivityOutcome.TIMEOUT
        assert latest_stall.error_category == ConnectivityOutcome.TIMEOUT

    # Verify active connectivity checks returned to zero
    active_samples = telemetry.connectivity_active_checks.collect()
    assert len(active_samples) == 1
    assert active_samples[0].value == 0.0
    assert len(executor._active) == 0


# ---------------------------------------------------------------------------
# Section 5: Deterministic DNS Error Coverage
# ---------------------------------------------------------------------------


def test_deterministic_dns_error_classification(
    fault_env: tuple[
        SQLiteNodeRepository,
        SQLiteConnectivityRepository,
        SQLiteOperationsRepository,
        Telemetry,
        Path,
        Path,
        paramiko.PKey,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deterministic resolver injection verifying DNS_ERROR without external DNS lookups."""
    (
        inv_repo,
        _,
        ops_repo,
        telemetry,
        known_hosts_path,
        private_key_path,
        _,
    ) = fault_env

    # Monkeypatch socket.getaddrinfo to deterministically simulate resolver failure
    def fake_getaddrinfo(*args: object, **kwargs: object) -> None:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    node = Node(99, "dns-node", "unresolvable.local", 22, ObservationState.NOT_CHECKED)
    settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)

    # 1. Transport layer classification
    transport = ParamikoOperationTransport()
    res = transport.execute(node, "uptime", settings)
    assert res.outcome == OperationOutcome.FAILURE
    assert res.failure_category == OperationFailureCategory.DNS_ERROR

    # 2. Service integration with SQLite and telemetry
    inv_node = inv_repo.add_node(NewNode("dns-test-node", "unresolvable.local", 22))

    class DirectAdapter:
        def run(
            self,
            node: Node,
            command: str,
            settings: SSHSettings,
            on_start: Callable[[], None] | None = None,
        ) -> object:
            if on_start is not None:
                on_start()
            return res

        def close(self) -> None:
            pass

    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=DirectAdapter(),  # type: ignore[arg-type]
        ssh_settings=settings,
        telemetry=telemetry,
    )

    rec = service.execute(inv_node.id, "system.uptime", {}, b"test-dns-digest")
    assert rec.outcome == OperationOutcome.FAILURE
    assert rec.failure_category == OperationFailureCategory.DNS_ERROR

    persisted = ops_repo.get(rec.id)
    assert persisted is not None
    assert persisted.outcome == OperationOutcome.FAILURE
    assert persisted.failure_category == OperationFailureCategory.DNS_ERROR

    active = next(
        s
        for s in telemetry.operations_active.collect()
        if s.labels.get("action") == "system.uptime"
    )
    assert active.value == 0.0
