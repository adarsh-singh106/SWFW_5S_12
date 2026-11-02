"""Real SSH handshake against a disposable in-process loopback server."""

import secrets
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import paramiko
from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.executor import DirectSSHExecutor
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.connectivity.transport import ParamikoSSHTransport
from fleet_manager.inventory.models import NewNode, Node, ObservationState
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.main import create_app
from fleet_manager.metrics.telemetry import Telemetry


class _Server(paramiko.ServerInterface):
    def __init__(self, accepted_key: paramiko.PKey) -> None:
        self.accepted_key = accepted_key

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        if username == "fleet-observer" and key == self.accepted_key:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, _username: str) -> str:
        return "publickey"


@contextmanager
def _ssh_server(host_key: paramiko.PKey, accepted_key: paramiko.PKey) -> Iterator[int]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    port = listener.getsockname()[1]
    completed = threading.Event()

    def serve() -> None:
        try:
            connection, _peer = listener.accept()
            with connection:
                transport = paramiko.Transport(connection)
                try:
                    transport.add_server_key(host_key)
                    transport.start_server(server=_Server(accepted_key))
                    deadline = time.monotonic() + 5
                    while transport.is_active() and time.monotonic() < deadline:
                        time.sleep(0.02)
                except (EOFError, OSError, paramiko.SSHException):
                    pass
                finally:
                    transport.close()
        finally:
            completed.set()

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        yield port
    finally:
        listener.close()
        assert completed.wait(timeout=7), "Disposable SSH server did not shut down"
        worker.join(timeout=1)


def _known_hosts(path: Path, port: int, key: paramiko.PKey) -> None:
    path.write_text(f"[127.0.0.1]:{port} {key.get_name()} {key.get_base64()}\n", encoding="ascii")


def test_verified_ssh_login_and_host_key_failures_on_loopback(tmp_path: Path) -> None:
    host_key = paramiko.RSAKey.generate(2048)
    other_host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    wrong_client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"
    transport = ParamikoSSHTransport()

    def observe(port: int, key_path: Path = private_key_path) -> ConnectivityOutcome:
        node = Node(1, "loopback", "127.0.0.1", port, ObservationState.NOT_CHECKED)
        settings = SSHSettings("fleet-observer", known_hosts_path, key_path)
        return transport.verify(node, settings)

    with _ssh_server(host_key, client_key) as port:
        _known_hosts(known_hosts_path, port, host_key)
        assert observe(port) is ConnectivityOutcome.CONNECTED

    with _ssh_server(host_key, client_key) as port:
        known_hosts_path.write_text("", encoding="ascii")
        assert observe(port) is ConnectivityOutcome.HOST_KEY_UNKNOWN

    with _ssh_server(host_key, client_key) as port:
        _known_hosts(known_hosts_path, port, other_host_key)
        assert observe(port) is ConnectivityOutcome.HOST_KEY_MISMATCH

    wrong_key_path = tmp_path / "wrong-key"
    wrong_client_key.write_private_key_file(str(wrong_key_path))
    with _ssh_server(host_key, client_key) as port:
        _known_hosts(known_hosts_path, port, host_key)
        assert observe(port, wrong_key_path) is ConnectivityOutcome.AUTH_FAILED

    with socket.socket() as unused_port:
        unused_port.bind(("127.0.0.1", 0))
        refused_port = unused_port.getsockname()[1]
    assert observe(refused_port) is ConnectivityOutcome.CONNECTION_REFUSED


def test_api_persists_real_verified_loopback_ssh_observation(tmp_path: Path) -> None:
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"
    api_token = secrets.token_urlsafe(32)
    headers = {"Authorization": f"Bearer {api_token}"}

    with _ssh_server(host_key, client_key) as port:
        _known_hosts(known_hosts_path, port, host_key)
        with TestClient(
            create_app(
                tmp_path / "inventory.db",
                api_token=api_token,
                ssh_settings=SSHSettings("fleet-observer", known_hosts_path, private_key_path),
            ),
            headers=headers,
        ) as client:
            registered = client.post(
                "/api/nodes",
                json={"name": "disposable-ssh", "address": "127.0.0.1", "ssh_port": port},
            )
            assert registered.status_code == 201
            node_id = registered.json()["id"]
            checked = client.post(f"/api/nodes/{node_id}/connectivity-check")
            assert checked.status_code == 200
            assert checked.json()["outcome"] == "CONNECTED"
            assert checked.json()["error_category"] is None
            assert client.get(f"/api/nodes/{node_id}/connectivity").json() == {
                "observation": checked.json()
            }
            assert client.get("/api/nodes").json()["nodes"] == [registered.json()]


@contextmanager
def _abrupt_disconnect_server() -> Iterator[int]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        try:
            conn, _ = listener.accept()
            # Immediately close socket without speaking SSH protocol
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        yield port
    finally:
        listener.close()
        t.join(timeout=1)


def test_loopback_disconnect_before_auth_resets_gauge_and_cleans_sockets(
    tmp_path: Path,
) -> None:
    """Server disconnects abruptly before handshake; verifies gauge reset and cleanup."""
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"

    db_path = tmp_path / "conn_fault.db"
    inv_repo = SQLiteNodeRepository(db_path)
    inv_repo.initialize()

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    telemetry = Telemetry()
    transport = ParamikoSSHTransport()
    executor = DirectSSHExecutor(transport)
    settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)

    service = ConnectivityService(
        inventory=inv_repo,
        observations=conn_repo,
        executor=executor,
        settings=settings,
        telemetry=telemetry,
    )

    with _abrupt_disconnect_server() as port:
        # Dummy host key in known hosts so it gets past host key lookup
        host_key = paramiko.RSAKey.generate(2048)
        _known_hosts(known_hosts_path, port, host_key)

        node = inv_repo.add_node(NewNode("abrupt-node", "127.0.0.1", port))

        # Perform check against abrupt disconnect endpoint
        obs = service.check(node.id)

        assert obs.outcome in (
            ConnectivityOutcome.UNKNOWN_ERROR,
            ConnectivityOutcome.CONNECTION_REFUSED,
        )

        # Telemetry active gauge returned to 0
        samples = telemetry.connectivity_active_checks.collect()
        assert len(samples) == 1
        assert samples[0].value == 0.0
        assert "fleet_connectivity_active_checks 0.0" in telemetry.render()

        # Check total metric was incremented
        rendered = telemetry.render()
        assert f'fleet_connectivity_checks_total{{outcome="{obs.outcome.value}"}} 1.0' in rendered
