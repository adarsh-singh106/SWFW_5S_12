"""Admission control and killable process boundary for blocking SSH checks."""

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from typing import Protocol

from fleet_manager.config import ConnectivityLimits, SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.errors import (
    ConnectivityBusy,
    ConnectivityInProgress,
    ConnectivityUnavailable,
)
from fleet_manager.inventory.models import Node


class SSHCheckExecutor(Protocol):
    def run(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome: ...

    def close(self) -> None: ...


class SSHTransport(Protocol):
    def verify(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome: ...


class DirectSSHExecutor:
    """In-process adapter for injected test transports only."""

    def __init__(self, transport: SSHTransport) -> None:
        self.transport = transport

    def run(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome:
        return self.transport.verify(node, settings)

    def close(self) -> None:
        pass


class ProcessSSHExecutor:
    """One process per admitted check; kill and reap at its total deadline."""

    def __init__(
        self,
        limits: ConnectivityLimits,
        worker_command: Sequence[str] | None = None,
    ) -> None:
        self.limits = limits
        self._command = tuple(
            worker_command or (sys.executable, "-m", "fleet_manager.connectivity.worker")
        )
        self._lock = threading.Lock()
        self._active: dict[int, subprocess.Popen[str]] = {}
        self._closed = False

    def run(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome:
        request = json.dumps(
            {
                "node": {"id": node.id, "address": node.address, "ssh_port": node.ssh_port},
                "ssh": {
                    "username": settings.username,
                    "known_hosts_path": str(settings.known_hosts_path),
                    "private_key_path": str(settings.private_key_path),
                    "connect_timeout_seconds": settings.connect_timeout_seconds,
                    "banner_timeout_seconds": settings.banner_timeout_seconds,
                    "authentication_timeout_seconds": settings.authentication_timeout_seconds,
                },
            }
        )
        safe_env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SYSTEMROOT", "WINDIR", "TMPDIR", "TMP", "TEMP"}
        }
        started = time.monotonic()
        with self._lock:
            if self._closed:
                raise ConnectivityUnavailable
            if node.id in self._active:
                raise ConnectivityInProgress
            if len(self._active) >= self.limits.max_concurrent:
                raise ConnectivityBusy
            try:
                process = subprocess.Popen(
                    self._command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    env=safe_env,
                )
            except OSError as exc:
                raise ConnectivityUnavailable from exc
            self._active[node.id] = process

        try:
            remaining = max(0.0, self.limits.total_timeout_seconds - (time.monotonic() - started))
            try:
                output, _ = process.communicate(input=request, timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                process.communicate()
                with self._lock:
                    if self._closed:
                        raise ConnectivityUnavailable from None
                return ConnectivityOutcome.EXECUTION_TIMEOUT
            except (OSError, ValueError) as exc:
                if process.poll() is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                process.wait()
                raise ConnectivityUnavailable from exc
            with self._lock:
                if self._closed:
                    raise ConnectivityUnavailable
            if process.returncode != 0:
                raise ConnectivityUnavailable
            try:
                return ConnectivityOutcome(output.strip())
            except ValueError as exc:
                raise ConnectivityUnavailable from exc
        finally:
            with self._lock:
                self._active.pop(node.id, None)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            processes = tuple(self._active.values())
        for process in processes:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        for process in processes:
            process.wait()
