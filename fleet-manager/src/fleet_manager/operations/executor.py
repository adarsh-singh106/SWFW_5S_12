"""Admission control and killable process boundary for remote operations."""

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import Protocol

from fleet_manager.config import OperationLimits, SSHSettings
from fleet_manager.errors import (
    ConnectivityConfigurationError,
    OperationBusy,
    OperationInProgress,
    OperationUnavailable,
)
from fleet_manager.inventory.models import Node
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationFailureCategory,
    OperationOutcome,
)
from fleet_manager.operations.transport import OperationTransport


class OperationExecutor(Protocol):
    def run(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        on_start: Callable[[], None] | None = None,
    ) -> OperationExecutionResult: ...

    def close(self) -> None: ...


class DirectOperationExecutor:
    """In-process adapter for injected test transports."""

    def __init__(
        self,
        transport: OperationTransport,
        limits: OperationLimits | None = None,
    ) -> None:
        self.transport = transport
        self.limits = limits or OperationLimits()
        self._lock = threading.Lock()
        self._active: set[int] = set()
        self._closed = False

    def run(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        on_start: Callable[[], None] | None = None,
    ) -> OperationExecutionResult:
        with self._lock:
            if self._closed:
                raise OperationUnavailable("Executor is shutting down")
            if node.id in self._active:
                raise OperationInProgress(f"Operation already active for node {node.id}")
            if len(self._active) >= self.limits.max_concurrent:
                raise OperationBusy("Operation execution capacity is exhausted")
            self._active.add(node.id)

        try:
            if on_start is not None:
                on_start()
            return self.transport.execute(
                node=node,
                command=command,
                settings=settings,
                timeout_seconds=self.limits.total_timeout_seconds,
                max_output_bytes=self.limits.max_output_bytes,
            )
        finally:
            with self._lock:
                self._active.discard(node.id)

    def close(self) -> None:
        with self._lock:
            self._closed = True


class ProcessOperationExecutor:
    """One dedicated child process per admitted operation; kill and reap at deadline."""

    def __init__(
        self,
        limits: OperationLimits,
        worker_command: Sequence[str] | None = None,
    ) -> None:
        self.limits = limits
        self._command = tuple(
            worker_command or (sys.executable, "-m", "fleet_manager.operations.worker")
        )
        self._lock = threading.Lock()
        self._active: dict[int, subprocess.Popen[str]] = {}
        self._closed = False

    def run(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        on_start: Callable[[], None] | None = None,
    ) -> OperationExecutionResult:
        request = json.dumps(
            {
                "node": {"id": node.id, "address": node.address, "ssh_port": node.ssh_port},
                "command": command,
                "ssh": {
                    "username": settings.username,
                    "known_hosts_path": str(settings.known_hosts_path),
                    "private_key_path": str(settings.private_key_path),
                    "connect_timeout_seconds": settings.connect_timeout_seconds,
                    "banner_timeout_seconds": settings.banner_timeout_seconds,
                    "authentication_timeout_seconds": settings.authentication_timeout_seconds,
                },
                "timeout_seconds": self.limits.total_timeout_seconds,
                "max_output_bytes": self.limits.max_output_bytes,
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
                raise OperationUnavailable("Executor is shutting down")
            if node.id in self._active:
                raise OperationInProgress(f"Operation already active for node {node.id}")
            if len(self._active) >= self.limits.max_concurrent:
                raise OperationBusy("Operation execution capacity is exhausted")
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
                raise OperationUnavailable("Failed to spawn operation worker") from exc
            self._active[node.id] = process

        try:
            if on_start is not None:
                on_start()
            remaining = max(0.0, self.limits.total_timeout_seconds - (time.monotonic() - started))
            try:
                output, _ = process.communicate(input=request, timeout=remaining)
            except subprocess.TimeoutExpired:
                with self._lock:
                    if self._closed:
                        raise OperationUnavailable("Executor is shutting down") from None
                return OperationExecutionResult(
                    outcome=OperationOutcome.TIMEOUT,
                    failure_category=OperationFailureCategory.TIMEOUT,
                    exit_code=None,
                    stdout=None,
                    stderr=f"Operation timed out after {self.limits.total_timeout_seconds}s",
                    output_truncated=False,
                )
            except (OSError, ValueError) as exc:
                raise OperationUnavailable("Error communicating with worker") from exc

            with self._lock:
                if self._closed:
                    raise OperationUnavailable("Executor is shutting down")

            if process.returncode == 2:
                raise ConnectivityConfigurationError("SSH operator configuration is unavailable")
            if process.returncode != 0:
                raise OperationUnavailable(f"Worker exited with code {process.returncode}")

            try:
                data = json.loads(output.strip())
                failure_cat = data.get("failure_category")
                return OperationExecutionResult(
                    outcome=OperationOutcome(data["outcome"]),
                    failure_category=OperationFailureCategory(failure_cat) if failure_cat else None,
                    exit_code=data.get("exit_code"),
                    stdout=data.get("stdout"),
                    stderr=data.get("stderr"),
                    output_truncated=bool(data.get("output_truncated", False)),
                )
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                raise OperationUnavailable("Invalid response received from worker") from exc
        finally:
            try:
                if process.poll() is None:
                    self._terminate_and_reap(process)
            finally:
                with self._lock:
                    self._active.pop(node.id, None)

    @staticmethod
    def _terminate_and_reap(process: subprocess.Popen[str]) -> None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OperationUnavailable("Could not reap operation worker") from exc

    def close(self) -> None:
        with self._lock:
            self._closed = True
            processes = tuple(self._active.values())
        for process in processes:
            if process.poll() is None:
                self._terminate_and_reap(process)
