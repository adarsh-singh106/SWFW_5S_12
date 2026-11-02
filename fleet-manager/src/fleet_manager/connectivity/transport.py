"""Paramiko adapter: verify SSH host identity and authenticate without a channel."""

import errno
import socket
from collections.abc import Iterable

import paramiko

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.errors import ConnectivityConfigurationError
from fleet_manager.inventory.models import Node


class UnknownHostKeyError(Exception):
    """No explicitly trusted key exists for this endpoint."""


class _RejectUnknownHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(
        self, _client: paramiko.SSHClient, _hostname: str, _key: paramiko.PKey
    ) -> None:
        raise UnknownHostKeyError


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
                client.set_missing_host_key_policy(_RejectUnknownHostKey())
                try:
                    private_key = paramiko.PKey.from_path(settings.private_key_path)
                except Exception as exc:
                    raise ConnectivityConfigurationError(
                        "SSH credential configuration is unavailable"
                    ) from exc
                client.connect(
                    hostname=node.address,
                    port=node.ssh_port,
                    username=settings.username,
                    pkey=private_key,
                    allow_agent=False,
                    look_for_keys=False,
                    timeout=settings.connect_timeout_seconds,
                    banner_timeout=settings.banner_timeout_seconds,
                    auth_timeout=settings.authentication_timeout_seconds,
                )
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
        except socket.gaierror:
            return ConnectivityOutcome.DNS_ERROR
        except TimeoutError:
            return ConnectivityOutcome.TIMEOUT
        except ConnectionRefusedError:
            return ConnectivityOutcome.CONNECTION_REFUSED
        except OSError as exc:
            return _socket_outcome([exc])
        except paramiko.SSHException:
            return ConnectivityOutcome.UNKNOWN_ERROR
