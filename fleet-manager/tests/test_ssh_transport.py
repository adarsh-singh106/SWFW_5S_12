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

    def set_missing_host_key_policy(self, policy: paramiko.MissingHostKeyPolicy) -> None:
        self.policy = policy

    def connect(self, **kwargs: Any) -> None:
        self.connect_kwargs = kwargs
        if self.unknown_key:
            assert self.policy is not None
            self.policy.missing_host_key(Mock(spec=paramiko.SSHClient), "node.example", Mock())
        if self.failure is not None:
            raise self.failure


@pytest.fixture
def node() -> Node:
    return Node(7, "node", "node.example", 2222, ObservationState.NOT_CHECKED)


@pytest.fixture
def settings(tmp_path: Path) -> SSHSettings:
    return SSHSettings("fleet-observer", tmp_path / "known_hosts", tmp_path / "observer-key")


def test_success_uses_explicit_trust_key_and_deadlines_without_command(
    monkeypatch: pytest.MonkeyPatch, node: Node, settings: SSHSettings
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
    }
    assert client.closed


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            paramiko.BadHostKeyException("node.example", Mock(), Mock()),
            ConnectivityOutcome.HOST_KEY_MISMATCH,
        ),
        (paramiko.AuthenticationException(), ConnectivityOutcome.AUTH_FAILED),
        (
            paramiko.ssh_exception.NoValidConnectionsError(
                {("127.0.0.1", 2222): ConnectionRefusedError(errno.ECONNREFUSED, "refused")}
            ),
            ConnectivityOutcome.CONNECTION_REFUSED,
        ),
        (TimeoutError("deadline"), ConnectivityOutcome.TIMEOUT),
        (socket.gaierror(socket.EAI_NONAME, "not found"), ConnectivityOutcome.DNS_ERROR),
        (paramiko.SSHException("bad handshake"), ConnectivityOutcome.UNKNOWN_ERROR),
    ],
)
def test_transport_classifies_failure_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    node: Node,
    settings: SSHSettings,
    failure: Exception,
    expected: ConnectivityOutcome,
) -> None:
    client = FakeClient(failure)
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _path: Mock(spec=paramiko.PKey))
    assert ParamikoSSHTransport().verify(node, settings) is expected
    assert client.closed


def test_unknown_host_key_is_rejected_without_trust_on_first_use(
    monkeypatch: pytest.MonkeyPatch, node: Node, settings: SSHSettings
) -> None:
    client = FakeClient(unknown_key=True)
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _path: Mock(spec=paramiko.PKey))
    assert ParamikoSSHTransport().verify(node, settings) is ConnectivityOutcome.HOST_KEY_UNKNOWN
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
