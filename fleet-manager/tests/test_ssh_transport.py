"""Transport classification and strict host-key behavior without a remote host."""

import errno
import socket
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import paramiko
import pytest

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.transport import ParamikoSSHTransport
from fleet_manager.errors import ConnectivityConfigurationError
from fleet_manager.inventory.models import Node, ObservationState


class FakeClient:
    def __init__(self, failure: Exception | None = None, unknown_key: bool = False) -> None:
        self.failure = failure
        self.unknown_key = unknown_key
        self.known_hosts_path: str | None = None
        self.policy: paramiko.MissingHostKeyPolicy | None = None
        self.connect_kwargs: dict[str, Any] = {}
        self.closed = False

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def load_host_keys(self, filename: str) -> None:
        self.known_hosts_path = filename

    def get_host_keys(self) -> paramiko.HostKeys:
        return paramiko.HostKeys()

    def set_missing_host_key_policy(self, policy: paramiko.MissingHostKeyPolicy) -> None:
        self.policy = policy

    def connect(self, **kwargs: Any) -> None:
        self.connect_kwargs = kwargs
        if self.unknown_key:
            assert self.policy is not None
            self.policy.missing_host_key(Mock(spec=paramiko.SSHClient), "node.example", Mock())
        if self.failure is not None:
            raise self.failure


class FakeSocket:
    def __init__(self, failure: OSError | None = None) -> None:
        self.failure = failure
        self.timeout: float | None = None
        self.connected_to: tuple[Any, ...] | None = None
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def connect(self, address: tuple[Any, ...]) -> None:
        self.connected_to = address
        if self.failure is not None:
            raise self.failure

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def node() -> Node:
    return Node(7, "node", "node.example", 2222, ObservationState.NOT_CHECKED)


@pytest.fixture
def settings(tmp_path: Path) -> SSHSettings:
    return SSHSettings("fleet-observer", tmp_path / "known_hosts", tmp_path / "observer-key")


@pytest.fixture
def connected_socket(monkeypatch: pytest.MonkeyPatch) -> FakeSocket:
    tcp_socket = FakeSocket()
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.7", 2222))
        ],
    )
    monkeypatch.setattr(socket, "socket", lambda *_args: tcp_socket)
    return tcp_socket


def _protocol_timeout() -> paramiko.SSHException:
    failure = paramiko.SSHException("Error reading SSH protocol banner")
    failure.__cause__ = TimeoutError("banner deadline")
    return failure


def test_success_uses_explicit_trust_key_and_deadlines_without_command(
    monkeypatch: pytest.MonkeyPatch,
    node: Node,
    settings: SSHSettings,
    connected_socket: FakeSocket,
) -> None:
    client = FakeClient()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    private_key = Mock(spec=paramiko.PKey)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _path: private_key)
    assert ParamikoSSHTransport().verify(node, settings) is ConnectivityOutcome.CONNECTED
    assert client.known_hosts_path == str(settings.known_hosts_path)
    assert client.connect_kwargs == {
        "hostname": "node.example",
        "port": 2222,
        "username": "fleet-observer",
        "pkey": private_key,
        "allow_agent": False,
        "look_for_keys": False,
        "timeout": 5.0,
        "banner_timeout": 5.0,
        "auth_timeout": 5.0,
        "sock": connected_socket,
    }
    assert connected_socket.timeout == 5.0
    assert connected_socket.connected_to == ("192.0.2.7", 2222)
    assert connected_socket.closed
    assert client.closed


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            paramiko.BadHostKeyException("node.example", Mock(), Mock()),
            ConnectivityOutcome.HOST_KEY_MISMATCH,
        ),
        (paramiko.AuthenticationException(), ConnectivityOutcome.AUTH_FAILED),
        (TimeoutError("deadline"), ConnectivityOutcome.TIMEOUT),
        (_protocol_timeout(), ConnectivityOutcome.TIMEOUT),
        (paramiko.SSHException("bad handshake"), ConnectivityOutcome.UNKNOWN_ERROR),
    ],
)
def test_transport_classifies_failure_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    node: Node,
    settings: SSHSettings,
    failure: Exception,
    expected: ConnectivityOutcome,
    connected_socket: FakeSocket,
) -> None:
    client = FakeClient(failure)
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _path: Mock(spec=paramiko.PKey))
    assert ParamikoSSHTransport().verify(node, settings) is expected
    assert connected_socket.closed
    assert client.closed


def test_tcp_candidates_try_ipv6_then_ipv4_and_close_each_socket(
    monkeypatch: pytest.MonkeyPatch, node: Node, settings: SSHSettings
) -> None:
    refused = FakeSocket(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
    connected = FakeSocket()
    sockets = iter([refused, connected])
    client = FakeClient()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _path: Mock(spec=paramiko.PKey))
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2001:db8::7", 2222, 0, 0),
            ),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.7", 2222)),
        ],
    )
    monkeypatch.setattr(socket, "socket", lambda *_args: next(sockets))

    assert ParamikoSSHTransport().verify(node, settings) is ConnectivityOutcome.CONNECTED
    assert refused.connected_to == ("2001:db8::7", 2222, 0, 0)
    assert connected.connected_to == ("192.0.2.7", 2222)
    assert refused.timeout == connected.timeout == 5.0
    assert refused.closed and connected.closed
    assert client.connect_kwargs["hostname"] == "node.example"
    assert client.connect_kwargs["port"] == 2222
    assert client.connect_kwargs["sock"] is connected


@pytest.mark.parametrize(
    ("registered_address", "normalized_address", "resolved_address", "family"),
    [
        ("192.0.2.8", "192.0.2.8", ("192.0.2.8", 2222), socket.AF_INET),
        ("[2001:db8::8]", "2001:db8::8", ("2001:db8::8", 2222, 0, 0), socket.AF_INET6),
        ("node.example", "node.example", ("192.0.2.8", 2222), socket.AF_INET),
    ],
)
def test_tcp_resolution_preserves_ipv4_ipv6_and_hostname_identity(
    monkeypatch: pytest.MonkeyPatch,
    settings: SSHSettings,
    registered_address: str,
    normalized_address: str,
    resolved_address: tuple[Any, ...],
    family: socket.AddressFamily,
) -> None:
    node = Node(7, "node", registered_address, 2222, ObservationState.NOT_CHECKED)
    connected = FakeSocket()
    client = FakeClient()
    resolution_calls: list[tuple[str, int, socket.AddressFamily, socket.SocketKind]] = []

    def resolve(
        address: str,
        port: int,
        *,
        family: socket.AddressFamily,
        type: socket.SocketKind,
    ) -> list[tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[Any, ...]]]:
        resolution_calls.append((address, port, family, type))
        return [(family_value, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", resolved_address)]

    family_value = family
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _path: Mock(spec=paramiko.PKey))
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "socket", lambda *_args: connected)

    assert ParamikoSSHTransport().verify(node, settings) is ConnectivityOutcome.CONNECTED
    assert resolution_calls == [(normalized_address, 2222, socket.AF_UNSPEC, socket.SOCK_STREAM)]
    assert connected.connected_to == resolved_address
    assert client.connect_kwargs["hostname"] == normalized_address
    assert client.connect_kwargs["port"] == 2222


@pytest.mark.parametrize(
    ("failures", "expected"),
    [
        (
            [
                TimeoutError("IPv6 connect deadline"),
                ConnectionRefusedError(errno.ECONNREFUSED, "IPv4 refused"),
            ],
            ConnectivityOutcome.CONNECTION_TIMEOUT,
        ),
        (
            [
                ConnectionRefusedError(errno.ECONNREFUSED, "IPv6 refused"),
                ConnectionRefusedError(errno.ECONNREFUSED, "IPv4 refused"),
            ],
            ConnectivityOutcome.CONNECTION_REFUSED,
        ),
        (
            [
                OSError(errno.ENETUNREACH, "IPv6 network unreachable"),
                ConnectionRefusedError(errno.ECONNREFUSED, "IPv4 refused"),
            ],
            ConnectivityOutcome.UNKNOWN_ERROR,
        ),
    ],
)
def test_all_tcp_candidates_preserve_most_informative_failure(
    monkeypatch: pytest.MonkeyPatch,
    node: Node,
    settings: SSHSettings,
    failures: list[OSError],
    expected: ConnectivityOutcome,
) -> None:
    attempted = [FakeSocket(failure) for failure in failures]
    sockets = iter(attempted)
    client = FakeClient()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _path: Mock(spec=paramiko.PKey))
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2001:db8::7", 2222, 0, 0),
            ),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.7", 2222)),
        ],
    )
    monkeypatch.setattr(socket, "socket", lambda *_args: next(sockets))

    assert ParamikoSSHTransport().verify(node, settings) is expected
    assert all(tcp_socket.closed for tcp_socket in attempted)
    assert all(tcp_socket.timeout == 5.0 for tcp_socket in attempted)
    assert client.connect_kwargs == {}


def test_dns_failure_is_check_error_before_any_socket_is_opened(
    monkeypatch: pytest.MonkeyPatch, node: Node, settings: SSHSettings
) -> None:
    client = FakeClient()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _path: Mock(spec=paramiko.PKey))

    def fail_resolution(*_args: object, **_kwargs: object) -> list[object]:
        raise socket.gaierror(socket.EAI_NONAME, "not found")

    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)
    socket_factory = Mock()
    monkeypatch.setattr(socket, "socket", socket_factory)

    assert ParamikoSSHTransport().verify(node, settings) is ConnectivityOutcome.DNS_ERROR
    socket_factory.assert_not_called()
    assert client.connect_kwargs == {}


def test_unknown_host_key_is_rejected_without_trust_on_first_use(
    monkeypatch: pytest.MonkeyPatch,
    node: Node,
    settings: SSHSettings,
    connected_socket: FakeSocket,
) -> None:
    client = FakeClient(unknown_key=True)
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _path: Mock(spec=paramiko.PKey))
    assert ParamikoSSHTransport().verify(node, settings) is ConnectivityOutcome.HOST_KEY_UNKNOWN
    assert connected_socket.closed
    assert client.closed


def test_unreadable_trust_file_closes_client_without_connecting(
    monkeypatch: pytest.MonkeyPatch, node: Node, settings: SSHSettings
) -> None:
    client = FakeClient()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)

    def fail_to_load(_filename: str) -> None:
        raise OSError("unreadable trust file")

    client.load_host_keys = fail_to_load
    with pytest.raises(ConnectivityConfigurationError):
        ParamikoSSHTransport().verify(node, settings)

    assert client.closed
    assert client.connect_kwargs == {}
