"""Paramiko adapter: verify SSH host identity and authenticate without a channel."""

import errno
import socket
from collections.abc import Iterable

import paramiko

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.trust import endpoint_identity, normalize_address, trusted_host_key
from fleet_manager.errors import ConnectivityConfigurationError
from fleet_manager.inventory.models import Node


class UnknownHostKeyError(Exception):
    """No explicitly trusted key exists for this endpoint."""


class _RejectUnknownHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(
        self, _client: paramiko.SSHClient, _hostname: str, _key: paramiko.PKey
    ) -> None:
        raise UnknownHostKeyError


class _ConnectionAttemptsFailed(Exception):
    """Every resolved TCP endpoint failed before SSH negotiation began."""

    def __init__(self, errors: Iterable[OSError]) -> None:
        self.errors = tuple(errors)


def _socket_outcome(
    errors: Iterable[OSError], *, connection_attempt: bool = False
) -> ConnectivityOutcome:
    found = list(errors)
    if any(isinstance(error, socket.gaierror) for error in found):
        return ConnectivityOutcome.DNS_ERROR
    if any(isinstance(error, TimeoutError) for error in found):
        return (
            ConnectivityOutcome.CONNECTION_TIMEOUT
            if connection_attempt
            else ConnectivityOutcome.TIMEOUT
        )
    if found and all(error.errno == errno.ECONNREFUSED for error in found):
        return ConnectivityOutcome.CONNECTION_REFUSED
    return ConnectivityOutcome.UNKNOWN_ERROR


def _caused_by_timeout(error: BaseException) -> bool:
    """Recognize timeouts wrapped by Paramiko during SSH protocol negotiation."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, TimeoutError):
            return True
        seen.add(id(current))
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return False


def _connect_socket(address: str, port: int, timeout: float) -> socket.socket:
    """Resolve and try every TCP address, closing each failed candidate."""
    candidates = socket.getaddrinfo(
        address,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    errors: list[OSError] = []
    for family, socket_type, protocol, _canonical_name, socket_address in candidates:
        candidate: socket.socket | None = None
        try:
            candidate = socket.socket(family, socket_type, protocol)
            candidate.settimeout(timeout)
            candidate.connect(socket_address)
        except OSError as exc:
            errors.append(exc)
            if candidate is not None:
                try:
                    candidate.close()
                except OSError:
                    pass
            continue
        return candidate
    raise _ConnectionAttemptsFailed(errors)


class ParamikoSSHTransport:
    """One short-lived SSH connection per observation; no shell or command channel."""

    def verify(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome:
        try:
            with paramiko.SSHClient() as client:
                try:
                    client.load_host_keys(str(settings.known_hosts_path))
                except (OSError, paramiko.SSHException) as exc:
                    raise ConnectivityConfigurationError(
                        "Trusted SSH host-key configuration is unavailable"
                    ) from exc
                try:
                    pinned = trusted_host_key(
                        node.address, node.ssh_port, settings.known_hosts_path
                    )
                    client.get_host_keys().clear()
                    if pinned is not None:
                        client.get_host_keys().add(
                            endpoint_identity(node.address, node.ssh_port),
                            pinned.get_name(),
                            pinned,
                        )
                except ValueError as exc:
                    raise ConnectivityConfigurationError("Ambiguous trusted SSH identity") from exc
                client.set_missing_host_key_policy(_RejectUnknownHostKey())
                try:
                    private_key = paramiko.PKey.from_path(settings.private_key_path)
                except Exception as exc:
                    raise ConnectivityConfigurationError(
                        "SSH credential configuration is unavailable"
                    ) from exc
                connected_socket = _connect_socket(
                    normalize_address(node.address),
                    node.ssh_port,
                    settings.connect_timeout_seconds,
                )
                try:
                    client.connect(
                        hostname=normalize_address(node.address),
                        port=node.ssh_port,
                        username=settings.username,
                        pkey=private_key,
                        allow_agent=False,
                        look_for_keys=False,
                        timeout=settings.connect_timeout_seconds,
                        banner_timeout=settings.banner_timeout_seconds,
                        auth_timeout=settings.authentication_timeout_seconds,
                        sock=connected_socket,
                    )
                finally:
                    connected_socket.close()
                return ConnectivityOutcome.CONNECTED
        except UnknownHostKeyError:
            return ConnectivityOutcome.HOST_KEY_UNKNOWN
        except paramiko.BadHostKeyException:
            return ConnectivityOutcome.HOST_KEY_MISMATCH
        except paramiko.AuthenticationException:
            return ConnectivityOutcome.AUTH_FAILED
        except paramiko.ssh_exception.PasswordRequiredException:
            return ConnectivityOutcome.AUTH_FAILED
        except paramiko.ssh_exception.NoValidConnectionsError as exc:
            return _socket_outcome(
                (error for error in exc.errors.values() if isinstance(error, OSError)),
                connection_attempt=True,
            )
        except _ConnectionAttemptsFailed as exc:
            return _socket_outcome(exc.errors, connection_attempt=True)
        except socket.gaierror:
            return ConnectivityOutcome.DNS_ERROR
        except TimeoutError:
            return ConnectivityOutcome.TIMEOUT
        except ConnectionRefusedError:
            return ConnectivityOutcome.CONNECTION_REFUSED
        except OSError as exc:
            return _socket_outcome([exc])
        except paramiko.SSHException as exc:
            return (
                ConnectivityOutcome.TIMEOUT
                if _caused_by_timeout(exc)
                else ConnectivityOutcome.UNKNOWN_ERROR
            )
