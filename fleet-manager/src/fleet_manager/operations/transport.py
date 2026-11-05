"""Paramiko adapter for controlled remote command execution."""

import errno
import socket
import time
from typing import Protocol

import paramiko

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.transport import UnknownHostKeyError, _RejectUnknownHostKey
from fleet_manager.connectivity.trust import endpoint_identity, normalize_address, trusted_host_key
from fleet_manager.errors import ConnectivityConfigurationError
from fleet_manager.inventory.models import Node
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationFailureCategory,
    OperationOutcome,
)


class OperationTransport(Protocol):
    def execute(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult: ...


class ParamikoOperationTransport:
    """Executes a structured command strictly over an authenticated SSH channel."""

    def execute(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        command_sent = False
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
                )

                transport = client.get_transport()
                if transport is None or not transport.is_active():
                    return OperationExecutionResult(
                        outcome=OperationOutcome.FAILURE,
                        failure_category=OperationFailureCategory.UNAVAILABLE,
                        exit_code=None,
                        stdout=None,
                        stderr="SSH transport is not active",
                        output_truncated=False,
                    )

                channel = transport.open_session()
                channel.settimeout(timeout_seconds)
                command_sent = True
                channel.exec_command(command)

                stdout_chunks: list[bytes] = []
                stderr_chunks: list[bytes] = []
                stdout_bytes = 0
                stderr_bytes = 0
                truncated = False
                deadline = time.monotonic() + timeout_seconds

                while True:
                    read_any = False
                    if channel.recv_ready():
                        chunk = channel.recv(4096)
                        if chunk:
                            read_any = True
                            if stdout_bytes < max_output_bytes:
                                take = chunk[: max_output_bytes - stdout_bytes]
                                stdout_chunks.append(take)
                                stdout_bytes += len(take)
                                if len(chunk) > len(take):
                                    truncated = True
                            else:
                                truncated = True

                    if channel.recv_stderr_ready():
                        chunk = channel.recv_stderr(4096)
                        if chunk:
                            read_any = True
                            if stderr_bytes < max_output_bytes:
                                take = chunk[: max_output_bytes - stderr_bytes]
                                stderr_chunks.append(take)
                                stderr_bytes += len(take)
                                if len(chunk) > len(take):
                                    truncated = True
                            else:
                                truncated = True

                    if channel.exit_status_ready():
                        # Drain remaining buffers after process finishes
                        while channel.recv_ready():
                            chunk = channel.recv(4096)
                            if not chunk:
                                break
                            if stdout_bytes < max_output_bytes:
                                take = chunk[: max_output_bytes - stdout_bytes]
                                stdout_chunks.append(take)
                                stdout_bytes += len(take)
                                if len(chunk) > len(take):
                                    truncated = True
                            else:
                                truncated = True
                        while channel.recv_stderr_ready():
                            chunk = channel.recv_stderr(4096)
                            if not chunk:
                                break
                            if stderr_bytes < max_output_bytes:
                                take = chunk[: max_output_bytes - stderr_bytes]
                                stderr_chunks.append(take)
                                stderr_bytes += len(take)
                                if len(chunk) > len(take):
                                    truncated = True
                            else:
                                truncated = True
                        break

                    if time.monotonic() > deadline:
                        try:
                            channel.close()
                        except (OSError, EOFError, paramiko.SSHException):
                            pass
                        return OperationExecutionResult(
                            outcome=OperationOutcome.TIMEOUT,
                            failure_category=OperationFailureCategory.TIMEOUT,
                            exit_code=None,
                            stdout=b"".join(stdout_chunks).decode("utf-8", errors="replace"),
                            stderr=b"".join(stderr_chunks).decode("utf-8", errors="replace"),
                            output_truncated=truncated,
                        )

                    if not read_any:
                        time.sleep(0.02)

                exit_code = channel.recv_exit_status()
                try:
                    channel.close()
                except (OSError, EOFError, paramiko.SSHException):
                    pass

                stdout_text = b"".join(stdout_chunks).decode("utf-8", errors="replace")
                stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")

                if exit_code == -1:
                    return OperationExecutionResult(
                        outcome=OperationOutcome.UNCERTAIN,
                        failure_category=OperationFailureCategory.TRANSPORT_ERROR,
                        exit_code=None,
                        stdout=stdout_text,
                        stderr="Transport disconnected before exit status was received",
                        output_truncated=truncated,
                    )

                if exit_code == 0:
                    return OperationExecutionResult(
                        outcome=OperationOutcome.SUCCESS,
                        failure_category=None,
                        exit_code=0,
                        stdout=stdout_text,
                        stderr=stderr_text,
                        output_truncated=truncated,
                    )
                return OperationExecutionResult(
                    outcome=OperationOutcome.FAILURE,
                    failure_category=OperationFailureCategory.COMMAND_ERROR,
                    exit_code=exit_code,
                    stdout=stdout_text,
                    stderr=stderr_text,
                    output_truncated=truncated,
                )

        except UnknownHostKeyError:
            return OperationExecutionResult(
                outcome=OperationOutcome.FAILURE,
                failure_category=OperationFailureCategory.HOST_KEY_UNKNOWN,
                exit_code=None,
                stdout=None,
                stderr="Untrusted SSH host key",
                output_truncated=False,
            )
        except paramiko.BadHostKeyException:
            return OperationExecutionResult(
                outcome=OperationOutcome.FAILURE,
                failure_category=OperationFailureCategory.HOST_KEY_MISMATCH,
                exit_code=None,
                stdout=None,
                stderr="SSH host key mismatch",
                output_truncated=False,
            )
        except paramiko.AuthenticationException:
            return OperationExecutionResult(
                outcome=OperationOutcome.FAILURE,
                failure_category=OperationFailureCategory.AUTH_FAILED,
                exit_code=None,
                stdout=None,
                stderr="SSH authentication failed",
                output_truncated=False,
            )
        except socket.gaierror:
            return OperationExecutionResult(
                outcome=OperationOutcome.FAILURE,
                failure_category=OperationFailureCategory.DNS_ERROR,
                exit_code=None,
                stdout=None,
                stderr="Address resolution failed",
                output_truncated=False,
            )
        except TimeoutError:
            return OperationExecutionResult(
                outcome=OperationOutcome.UNCERTAIN if command_sent else OperationOutcome.TIMEOUT,
                failure_category=OperationFailureCategory.TIMEOUT,
                exit_code=None,
                stdout=None,
                stderr="Connection timed out",
                output_truncated=False,
            )
        except ConnectionRefusedError:
            return OperationExecutionResult(
                outcome=OperationOutcome.FAILURE,
                failure_category=OperationFailureCategory.CONNECTION_REFUSED,
                exit_code=None,
                stdout=None,
                stderr="Connection refused by remote host",
                output_truncated=False,
            )
        except paramiko.ssh_exception.NoValidConnectionsError as exc:
            errors = list(exc.errors.values())
            if any(isinstance(err, TimeoutError) for err in errors):
                return OperationExecutionResult(
                    outcome=OperationOutcome.TIMEOUT,
                    failure_category=OperationFailureCategory.TIMEOUT,
                    exit_code=None,
                    stdout=None,
                    stderr="Connection timed out",
                    output_truncated=False,
                )
            return OperationExecutionResult(
                outcome=OperationOutcome.FAILURE,
                failure_category=OperationFailureCategory.CONNECTION_REFUSED,
                exit_code=None,
                stdout=None,
                stderr="Connection refused by remote host",
                output_truncated=False,
            )
        except OSError as exc:
            if exc.errno == errno.ECONNREFUSED and not command_sent:
                return OperationExecutionResult(
                    outcome=OperationOutcome.FAILURE,
                    failure_category=OperationFailureCategory.CONNECTION_REFUSED,
                    exit_code=None,
                    stdout=None,
                    stderr="Connection refused by remote host",
                    output_truncated=False,
                )
            if command_sent:
                return OperationExecutionResult(
                    outcome=OperationOutcome.UNCERTAIN,
                    failure_category=OperationFailureCategory.TRANSPORT_ERROR,
                    exit_code=None,
                    stdout=None,
                    stderr="Transport error after command dispatch",
                    output_truncated=False,
                )
            return OperationExecutionResult(
                outcome=OperationOutcome.FAILURE,
                failure_category=OperationFailureCategory.UNAVAILABLE,
                exit_code=None,
                stdout=None,
                stderr="SSH transport is unavailable",
                output_truncated=False,
            )
        except (EOFError, paramiko.SSHException):
            if command_sent:
                return OperationExecutionResult(
                    outcome=OperationOutcome.UNCERTAIN,
                    failure_category=OperationFailureCategory.TRANSPORT_ERROR,
                    exit_code=None,
                    stdout=None,
                    stderr="SSH protocol failure after command dispatch",
                    output_truncated=False,
                )
            return OperationExecutionResult(
                outcome=OperationOutcome.FAILURE,
                failure_category=OperationFailureCategory.UNAVAILABLE,
                exit_code=None,
                stdout=None,
                stderr="SSH protocol failure before command dispatch",
                output_truncated=False,
            )
