"""Real host-key and authentication checks against a disposable SSH server."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import paramiko

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.transport import ParamikoSSHTransport
from fleet_manager.inventory.models import Node, ObservationState


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
        yield listener.getsockname()[1]
    finally:
        listener.close()
        assert completed.wait(timeout=7), "Disposable SSH server did not shut down"
        worker.join(timeout=1)


def _known_hosts(path: Path, port: int, key: paramiko.PKey) -> None:
    path.write_text(f"[127.0.0.1]:{port} {key.get_name()} {key.get_base64()}\n", encoding="ascii")


def test_verified_login_rejects_unknown_changed_and_wrong_credentials(tmp_path: Path) -> None:
    host_key = paramiko.RSAKey.generate(2048)
    different_host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    wrong_client_key = paramiko.RSAKey.generate(2048)
    key_path = tmp_path / "observer-key"
    wrong_key_path = tmp_path / "wrong-key"
    client_key.write_private_key_file(str(key_path))
    wrong_client_key.write_private_key_file(str(wrong_key_path))
    hosts_path = tmp_path / "known_hosts"
    transport = ParamikoSSHTransport()

    def observe(port: int, private_key_path: Path = key_path) -> ConnectivityOutcome:
        node = Node(1, "loopback", "127.0.0.1", port, ObservationState.NOT_CHECKED)
        return transport.verify(node, SSHSettings("fleet-observer", hosts_path, private_key_path))

    with _ssh_server(host_key, client_key) as port:
        _known_hosts(hosts_path, port, host_key)
        assert observe(port) is ConnectivityOutcome.CONNECTED

    with _ssh_server(host_key, client_key) as port:
        hosts_path.write_text("", encoding="ascii")
        assert observe(port) is ConnectivityOutcome.HOST_KEY_UNKNOWN

    with _ssh_server(host_key, client_key) as port:
        _known_hosts(hosts_path, port, different_host_key)
        assert observe(port) is ConnectivityOutcome.HOST_KEY_MISMATCH

    with _ssh_server(host_key, client_key) as port:
        _known_hosts(hosts_path, port, host_key)
        assert observe(port, wrong_key_path) is ConnectivityOutcome.AUTH_FAILED
