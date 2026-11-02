"""Real SSH channel execution against a disposable in-process loopback server."""

import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import paramiko
from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.inventory.models import NewNode, Node, ObservationState
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.main import create_app
from fleet_manager.metrics.telemetry import Telemetry
from fleet_manager.operations.executor import DirectOperationExecutor
from fleet_manager.operations.models import OperationFailureCategory, OperationOutcome
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.service import OperationService
from fleet_manager.operations.transport import ParamikoOperationTransport


class _ExecServer(paramiko.ServerInterface):
    def __init__(
        self,
        accepted_key: paramiko.PKey,
        handler: Callable[[str], tuple[int, str, str]],
    ) -> None:
        self.accepted_key = accepted_key
        self.handler = handler

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        if username == "fleet-observer" and key == self.accepted_key:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, _username: str) -> str:
        return "publickey"

    def check_channel_request(self, kind: str, _chanid: int) -> int:
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel: paramiko.Channel, command: bytes) -> bool:
        cmd_str = command.decode("utf-8")

        def run() -> None:
            try:
                exit_code, stdout, stderr = self.handler(cmd_str)
                if stdout:
                    channel.send(stdout.encode("utf-8"))
                if stderr:
                    channel.send_stderr(stderr.encode("utf-8"))
                channel.send_exit_status(exit_code)
                time.sleep(0.05)
                channel.close()
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()
        return True


@contextmanager
def _ssh_exec_server(
    host_key: paramiko.PKey,
    accepted_key: paramiko.PKey,
    handler: Callable[[str], tuple[int, str, str]],
) -> Iterator[int]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    stop_event = threading.Event()
    active_transports: list[paramiko.Transport] = []
    transports_lock = threading.Lock()

    def handle_client(connection: socket.socket) -> None:
        with connection:
            transport = paramiko.Transport(connection)
            with transports_lock:
                active_transports.append(transport)
            try:
                transport.add_server_key(host_key)
                transport.start_server(server=_ExecServer(accepted_key, handler))
                chan = transport.accept(5)
                deadline = time.monotonic() + 5
                while transport.is_active() and time.monotonic() < deadline:
                    if chan is not None and chan.closed:
                        time.sleep(0.05)
                        break
                    time.sleep(0.02)
            except (EOFError, OSError, paramiko.SSHException):
                pass
            finally:
                transport.close()

    def serve() -> None:
        while not stop_event.is_set():
            try:
                connection, _peer = listener.accept()
                threading.Thread(target=handle_client, args=(connection,), daemon=True).start()
            except TimeoutError:
                continue
            except OSError:
                break

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        yield port
    finally:
        stop_event.set()
        listener.close()
        worker.join(timeout=2)
        with transports_lock:
            for t in active_transports:
                try:
                    t.close()
                except Exception:
                    pass


def _known_hosts(path: Path, port: int, key: paramiko.PKey) -> None:
    path.write_text(f"[127.0.0.1]:{port} {key.get_name()} {key.get_base64()}\n", encoding="ascii")


def test_real_loopback_ssh_operation_execution(tmp_path: Path) -> None:
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"

    dispatched_commands: list[str] = []

    def command_handler(cmd: str) -> tuple[int, str, str]:
        dispatched_commands.append(cmd)
        if cmd == "uptime":
            return 0, "15:00:00 up 5 days, 1 user, load average: 0.10, 0.05, 0.01\n", ""
        return 1, "", "Unknown command\n"

    transport = ParamikoOperationTransport()

    with _ssh_exec_server(host_key, client_key, command_handler) as port:
        _known_hosts(known_hosts_path, port, host_key)
        node = Node(1, "loopback", "127.0.0.1", port, ObservationState.NOT_CHECKED)
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)

        result = transport.execute(node, "uptime", settings)
        assert result.outcome == OperationOutcome.SUCCESS
        assert result.exit_code == 0
        assert "up 5 days" in (result.stdout or "")
        assert result.stderr == ""
        assert not result.output_truncated

    assert dispatched_commands == ["uptime"]


def test_api_e2e_real_loopback_ssh_operation(tmp_path: Path) -> None:
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"
    api_token = secrets.token_urlsafe(32)
    headers = {"Authorization": f"Bearer {api_token}"}

    def command_handler(cmd: str) -> tuple[int, str, str]:
        if "node_exporter" in cmd:
            return 0, "● node_exporter.service - active (running)\n", ""
        return 0, "mock output", ""

    with _ssh_exec_server(host_key, client_key, command_handler) as port:
        _known_hosts(known_hosts_path, port, host_key)
        app = create_app(
            database_path=tmp_path / "inventory.db",
            api_token=api_token,
            ssh_settings=SSHSettings("fleet-observer", known_hosts_path, private_key_path),
            enable_scheduler=False,
        )
        with TestClient(app, headers=headers) as client:
            reg = client.post(
                "/api/nodes",
                json={"name": "disposable-node", "address": "127.0.0.1", "ssh_port": port},
            )
            assert reg.status_code == 201
            node_id = reg.json()["id"]

            resp = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": "service.status", "arguments": {"service_name": "node_exporter"}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["outcome"] == "SUCCESS"
            assert data["exit_code"] == 0
            assert "active (running)" in data["stdout"]

            # Retrieve from GET
            op_id = data["id"]
            get_resp = client.get(f"/api/nodes/{node_id}/operations/{op_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["id"] == op_id
            assert get_resp.json()["outcome"] == "SUCCESS"


@contextmanager
def _ssh_fault_server(
    host_key: paramiko.PKey,
    accepted_key: paramiko.PKey,
    *,
    disconnect_before_dispatch: bool = False,
    disconnect_after_dispatch: bool = False,
) -> Iterator[int]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    stop_event = threading.Event()
    active_transports: list[paramiko.Transport] = []
    transports_lock = threading.Lock()

    class _FaultServer(paramiko.ServerInterface):
        def __init__(self, transport: paramiko.Transport) -> None:
            self.transport = transport

        def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
            if username == "fleet-observer" and key == accepted_key:
                return paramiko.AUTH_SUCCESSFUL
            return paramiko.AUTH_FAILED

        def get_allowed_auths(self, _username: str) -> str:
            return "publickey"

        def check_channel_request(self, kind: str, _chanid: int) -> int:
            if kind == "session":
                if disconnect_before_dispatch:
                    # Sever connection before command dispatch can occur
                    self.transport.close()
                    return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
                return paramiko.OPEN_SUCCEEDED
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_channel_exec_request(self, channel: paramiko.Channel, command: bytes) -> bool:
            if disconnect_after_dispatch:

                def drop() -> None:
                    time.sleep(0.05)
                    self.transport.close()
                    try:
                        channel.close()
                    except Exception:
                        pass

                threading.Thread(target=drop, daemon=True).start()
                return True

            channel.send_exit_status(0)
            channel.close()
            return True

    def handle_client(connection: socket.socket) -> None:
        with connection:
            transport = paramiko.Transport(connection)
            with transports_lock:
                active_transports.append(transport)
            try:
                transport.add_server_key(host_key)
                server = _FaultServer(transport)
                transport.start_server(server=server)
                chan = transport.accept(5)
                deadline = time.monotonic() + 5
                while transport.is_active() and time.monotonic() < deadline:
                    if chan is not None and chan.closed:
                        time.sleep(0.05)
                        break
                    time.sleep(0.02)
            except (EOFError, OSError, paramiko.SSHException):
                pass
            finally:
                transport.close()

    def serve() -> None:
        while not stop_event.is_set():
            try:
                connection, _peer = listener.accept()
                threading.Thread(target=handle_client, args=(connection,), daemon=True).start()
            except TimeoutError:
                continue
            except OSError:
                break

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        yield port
    finally:
        stop_event.set()
        listener.close()
        worker.join(timeout=2)
        with transports_lock:
            for t in active_transports:
                try:
                    t.close()
                except Exception:
                    pass


def test_loopback_disconnect_before_dispatch_returns_failure(tmp_path: Path) -> None:
    """Disconnect before command dispatch maps strictly to FAILURE (UNAVAILABLE)."""
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"

    transport = ParamikoOperationTransport()

    with _ssh_fault_server(host_key, client_key, disconnect_before_dispatch=True) as port:
        _known_hosts(known_hosts_path, port, host_key)
        node = Node(1, "fault-node", "127.0.0.1", port, ObservationState.NOT_CHECKED)
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)

        result = transport.execute(node, "uptime", settings)
        assert result.outcome == OperationOutcome.FAILURE
        assert result.failure_category == OperationFailureCategory.UNAVAILABLE
        assert result.exit_code is None
        assert not result.output_truncated


def test_loopback_connection_loss_after_dispatch_returns_uncertain(tmp_path: Path) -> None:
    """Connection loss while command is running maps strictly to UNCERTAIN (TRANSPORT_ERROR)."""
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"

    transport = ParamikoOperationTransport()

    with _ssh_fault_server(host_key, client_key, disconnect_after_dispatch=True) as port:
        _known_hosts(known_hosts_path, port, host_key)
        node = Node(1, "fault-node", "127.0.0.1", port, ObservationState.NOT_CHECKED)
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)

        result = transport.execute(node, "uptime", settings)
        assert result.outcome == OperationOutcome.UNCERTAIN
        assert result.failure_category == OperationFailureCategory.TRANSPORT_ERROR
        assert result.exit_code is None
        assert any(
            msg in (result.stderr or "")
            for msg in ("after command dispatch", "Transport disconnected")
        )


def test_operation_service_faults_and_gauge_resets(tmp_path: Path) -> None:
    """Service maps faults to UNCERTAIN/FAILURE and guarantees operations_active resets to 0."""
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"

    db_path = tmp_path / "service_fault.db"
    inv_repo = SQLiteNodeRepository(db_path)
    inv_repo.initialize()

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    ops_repo = SQLiteOperationsRepository(db_path)
    ops_repo.initialize()

    telemetry = Telemetry()
    settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
    transport = ParamikoOperationTransport()
    executor = DirectOperationExecutor(transport)
    service = OperationService(
        inventory_repository=inv_repo,
        operations_repository=ops_repo,
        executor=executor,
        ssh_settings=settings,
        telemetry=telemetry,
    )

    # 1. Connection loss after dispatch -> UNCERTAIN
    with _ssh_fault_server(host_key, client_key, disconnect_after_dispatch=True) as port:
        _known_hosts(known_hosts_path, port, host_key)
        node = inv_repo.add_node(NewNode("uncertain-node", "127.0.0.1", port))

        record = service.execute(
            node_id=node.id,
            action="system.uptime",
            arguments={},
            operator_digest=b"operator-digest-test",
        )

        assert record.outcome == OperationOutcome.UNCERTAIN
        assert record.failure_category == OperationFailureCategory.TRANSPORT_ERROR
        assert record.completed_at is not None

        # Verify durable storage
        persisted = ops_repo.get(record.id)
        assert persisted is not None
        assert persisted.outcome == OperationOutcome.UNCERTAIN

        # Active gauge reset to 0
        samples = telemetry.operations_active.collect()
        active_sample = next(s for s in samples if s.labels.get("action") == "system.uptime")
        assert active_sample.value == 0.0
        assert 'fleet_operations_active{action="system.uptime"} 0.0' in telemetry.render()

        # Total metric incremented for UNCERTAIN
        expected_uncertain = (
            'fleet_operations_total{action="system.uptime",outcome="UNCERTAIN"} 1.0'
        )
        assert expected_uncertain in telemetry.render()

    # 2. Disconnect before dispatch -> FAILURE
    with _ssh_fault_server(host_key, client_key, disconnect_before_dispatch=True) as port:
        _known_hosts(known_hosts_path, port, host_key)
        node_fail = inv_repo.add_node(NewNode("fail-node", "127.0.0.1", port))

        record_fail = service.execute(
            node_id=node_fail.id,
            action="system.uptime",
            arguments={},
            operator_digest=b"operator-digest-test",
        )

        assert record_fail.outcome == OperationOutcome.FAILURE
        assert record_fail.failure_category == OperationFailureCategory.UNAVAILABLE

        # Active gauge reset to 0
        samples = telemetry.operations_active.collect()
        active_sample = next(s for s in samples if s.labels.get("action") == "system.uptime")
        assert active_sample.value == 0.0

        # Total metric incremented for FAILURE
        expected_failure = 'fleet_operations_total{action="system.uptime",outcome="FAILURE"} 1.0'
        assert expected_failure in telemetry.render()


def test_loopback_fault_socket_cleanup(tmp_path: Path) -> None:
    """Repeated faults do not leak open sockets or block subsequent successful executions."""
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"

    transport = ParamikoOperationTransport()

    # Run consecutive faults
    for _ in range(3):
        with _ssh_fault_server(host_key, client_key, disconnect_after_dispatch=True) as port:
            _known_hosts(known_hosts_path, port, host_key)
            node = Node(1, "repeat-fault", "127.0.0.1", port, ObservationState.NOT_CHECKED)
            settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
            res = transport.execute(node, "uptime", settings)
            assert res.outcome == OperationOutcome.UNCERTAIN

    # Clean execution immediately afterward succeeds
    def healthy_handler(_cmd: str) -> tuple[int, str, str]:
        return 0, "healthy output\n", ""

    with _ssh_exec_server(host_key, client_key, healthy_handler) as port:
        _known_hosts(known_hosts_path, port, host_key)
        node = Node(2, "healthy-node", "127.0.0.1", port, ObservationState.NOT_CHECKED)
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
        res = transport.execute(node, "uptime", settings)
        assert res.outcome == OperationOutcome.SUCCESS
        assert res.stdout == "healthy output\n"
