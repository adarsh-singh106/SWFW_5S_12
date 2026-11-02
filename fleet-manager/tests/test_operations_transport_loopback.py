"""Real SSH channel execution against a disposable in-process loopback server."""

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import paramiko
import pytest

from fleet_manager.config import SSHSettings
from fleet_manager.inventory.models import Node, ObservationState
from fleet_manager.operations.models import OperationFailureCategory, OperationOutcome
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


def test_loopback_nonzero_exit_and_bounded_both_output_streams(tmp_path: Path) -> None:
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"

    with _ssh_exec_server(host_key, client_key, lambda _cmd: (3, "x" * 100, "e" * 100)) as port:
        _known_hosts(known_hosts_path, port, host_key)
        node = Node(1, "loopback", "127.0.0.1", port, ObservationState.NOT_CHECKED)
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
        result = ParamikoOperationTransport().execute(node, "uptime", settings, max_output_bytes=8)

    assert result.outcome == OperationOutcome.FAILURE
    assert result.failure_category == OperationFailureCategory.COMMAND_ERROR
    assert result.exit_code == 3
    assert result.stdout == "x" * 8
    assert result.stderr == "e" * 8
    assert result.output_truncated


@pytest.mark.parametrize(
    ("trusted_key_matches", "expected"),
    [
        (None, OperationFailureCategory.HOST_KEY_UNKNOWN),
        (False, OperationFailureCategory.HOST_KEY_MISMATCH),
    ],
)
def test_loopback_rejects_untrusted_host_without_dispatch(
    tmp_path: Path,
    trusted_key_matches: bool | None,
    expected: OperationFailureCategory,
) -> None:
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    private_key_path = tmp_path / "observer-key"
    client_key.write_private_key_file(str(private_key_path))
    known_hosts_path = tmp_path / "known_hosts"
    dispatched: list[str] = []

    def handler(command: str) -> tuple[int, str, str]:
        dispatched.append(command)
        return 0, "", ""

    with _ssh_exec_server(host_key, client_key, handler) as port:
        if trusted_key_matches is None:
            known_hosts_path.write_text("", encoding="ascii")
        else:
            _known_hosts(known_hosts_path, port, paramiko.RSAKey.generate(2048))
        node = Node(1, "loopback", "127.0.0.1", port, ObservationState.NOT_CHECKED)
        settings = SSHSettings("fleet-observer", known_hosts_path, private_key_path)
        result = ParamikoOperationTransport().execute(node, "uptime", settings)

    assert result.outcome == OperationOutcome.FAILURE
    assert result.failure_category == expected
    assert dispatched == []
