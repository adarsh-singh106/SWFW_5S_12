"""Deterministic fleet benchmarks: Stage 1 admission and Stage 2 fleet execution.

Run with .local/windows-verify/Scripts/python.exe scripts/benchmark_fleet_performance.py.
Paths are relative to the project, never the caller's working directory. Service validation,
SQLite audit persistence, executor admission, and telemetry are real.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import platform
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import paramiko
from paramiko.common import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED,
    OPEN_SUCCEEDED,
)

from fleet_manager.config import ConnectivityLimits, OperationLimits, SSHSettings
from fleet_manager.connectivity.executor import ProcessSSHExecutor
from fleet_manager.connectivity.models import ConnectivityObservation
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.scheduler import ConnectivityScheduler
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.errors import OperationBusy
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.metrics.telemetry import Telemetry
from fleet_manager.operations.executor import DirectOperationExecutor, ProcessOperationExecutor
from fleet_manager.operations.models import OperationExecutionResult, OperationOutcome
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.service import OperationService
from fleet_manager.operations.transport import ParamikoOperationTransport

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = (PROJECT_ROOT / ".local").resolve()

SCENARIO_ADMISSION = "admission"
SCENARIO_OPERATION_DIRECT = "operation-direct"
SCENARIO_OPERATION_LOOPBACK = "operation-loopback"
SCENARIO_OPERATION_PROCESS = "operation-process"
SCENARIO_SCHEDULER_FLEET = "scheduler-fleet"

SCENARIO = SCENARIO_ADMISSION  # backward-compatible export

TRANSPORT_ADMISSION = "controlled-in-process"
TRANSPORT_OPERATION_DIRECT = "synthetic-direct"
TRANSPORT_OPERATION_LOOPBACK = "paramiko-direct"
TRANSPORT_OPERATION_PROCESS = "subprocess-paramiko"
TRANSPORT_SCHEDULER_FLEET = "process-ssh"

TRANSPORT = TRANSPORT_ADMISSION  # backward-compatible export

DEFAULT_TRANSPORTS = {
    SCENARIO_ADMISSION: TRANSPORT_ADMISSION,
    SCENARIO_OPERATION_DIRECT: TRANSPORT_OPERATION_DIRECT,
    SCENARIO_OPERATION_LOOPBACK: TRANSPORT_OPERATION_LOOPBACK,
    SCENARIO_OPERATION_PROCESS: TRANSPORT_OPERATION_PROCESS,
    SCENARIO_SCHEDULER_FLEET: TRANSPORT_SCHEDULER_FLEET,
}

ALL_SCENARIOS = [
    SCENARIO_ADMISSION,
    SCENARIO_OPERATION_DIRECT,
    SCENARIO_OPERATION_LOOPBACK,
    SCENARIO_OPERATION_PROCESS,
    SCENARIO_SCHEDULER_FLEET,
]

ALL_TRANSPORTS = [
    TRANSPORT_ADMISSION,
    TRANSPORT_OPERATION_DIRECT,
    TRANSPORT_OPERATION_LOOPBACK,
    TRANSPORT_OPERATION_PROCESS,
    TRANSPORT_SCHEDULER_FLEET,
]

ACTION = "system.uptime"
OPERATOR_DIGEST = b"benchmark-synthetic-operator"


@dataclass(frozen=True)
class Configuration:
    max_concurrent: int = 4
    requests: int = 16
    warmup: int = 1
    repetitions: int = 5
    timeout_seconds: float = 30.0
    output_dir: Path = LOCAL_ROOT / "benchmarks"
    scenario: str = SCENARIO_ADMISSION
    transport: str = TRANSPORT_ADMISSION
    fleet_size: int = 3
    simulated_delay_ms: float = 0.0

    def validate(self) -> None:
        if not 1 <= self.max_concurrent <= 16:
            raise ValueError("max-concurrent must be between 1 and 16 (application limit)")
        if self.warmup < 0 or self.repetitions < 1:
            raise ValueError("warmup must be non-negative and repetitions must be positive")
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 120:
            raise ValueError("timeout-seconds must be finite, positive and at most 120")
        if not self.output_dir.resolve().is_relative_to(LOCAL_ROOT):
            raise ValueError("output-dir must resolve under the project's Git-ignored .local/")
        if not math.isfinite(self.simulated_delay_ms) or self.simulated_delay_ms < 0:
            raise ValueError("simulated-delay-ms must be non-negative and finite")

        if self.scenario == SCENARIO_ADMISSION:
            if self.transport != TRANSPORT_ADMISSION:
                raise ValueError(
                    f"only admission with {TRANSPORT_ADMISSION} transport is supported"
                )
            if self.requests <= self.max_concurrent:
                raise ValueError(
                    "requests must exceed max-concurrent to measure capacity rejection"
                )
        elif self.scenario in (
            SCENARIO_OPERATION_DIRECT,
            SCENARIO_OPERATION_LOOPBACK,
            SCENARIO_OPERATION_PROCESS,
            SCENARIO_SCHEDULER_FLEET,
        ):
            expected_transport = DEFAULT_TRANSPORTS[self.scenario]
            if self.transport != expected_transport:
                raise ValueError(
                    f"{self.scenario} scenario requires transport '{expected_transport}'"
                )
            if self.fleet_size not in (3, 10):
                raise ValueError("fleet-size must be either 3 or 10")
        else:
            raise ValueError(f"unsupported scenario: {self.scenario}")


def parse_args(argv: list[str] | None = None) -> Configuration:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-concurrent", type=int, default=4)
    parser.add_argument("--requests", type=int, default=16)
    parser.add_argument("--warmup", type=int, default=1, help="unmeasured warm-up rounds")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="coordination watchdog, not a performance pass/fail threshold",
    )
    parser.add_argument("--output-dir", type=Path, default=Path(".local/benchmarks"))
    parser.add_argument("--scenario", choices=ALL_SCENARIOS, default=SCENARIO_ADMISSION)
    parser.add_argument("--transport", choices=ALL_TRANSPORTS, default=None)
    parser.add_argument(
        "--fleet-size",
        type=int,
        choices=[3, 10],
        default=3,
        help="fleet size for direct operation benchmarks (3 or 10 nodes)",
    )
    parser.add_argument(
        "--simulated-delay-ms",
        type=float,
        default=0.0,
        help="simulated server-side processing delay in milliseconds",
    )
    args = vars(parser.parse_args(argv))
    if args["transport"] is None:
        args["transport"] = DEFAULT_TRANSPORTS[args["scenario"]]
    args["output_dir"] = (PROJECT_ROOT / args["output_dir"]).resolve()
    config = Configuration(**args)
    try:
        config.validate()
    except ValueError as exc:
        parser.error(str(exc))
    return config


def percentiles(values: Sequence[int | float]) -> dict[str, float]:
    """Linear interpolation at zero-based rank (n - 1) * p (Hyndman-Fan type 7)."""
    if not values:
        raise ValueError("percentiles require at least one sample")
    ordered = sorted(values)
    result = {}
    for p in (50, 90, 95, 99):
        rank = (len(ordered) - 1) * p / 100
        lower = int(rank)
        upper = min(lower + 1, len(ordered) - 1)
        result[f"p{p}"] = float(ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower))
    return result


class ObservedProcessOperationExecutor(ProcessOperationExecutor):
    """Observe only this executor's admitted Popen objects through its on_start hook.

    The production run/communicate/timeout/kill path remains inherited. Post-return
    wait(0) verifies termination; it does not prove which production wait call ran.
    """

    def __init__(
        self, limits: OperationLimits, worker_command: Sequence[str] | None = None
    ) -> None:
        super().__init__(limits, worker_command)
        self.phase = "not_set"
        self.iteration = -1
        self._observation_lock = threading.Lock()
        self._tracked: list[tuple[subprocess.Popen[str], dict[str, Any]]] = []

    def run(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        on_start: Callable[[], None] | None = None,
    ) -> OperationExecutionResult:
        process: subprocess.Popen[str] | None = None
        record: dict[str, Any] = {}

        def observe_start() -> None:
            nonlocal process
            with self._lock:
                process = self._active[node.id]
            record.update(
                execution_id=uuid.uuid4().hex,
                node_id=node.id,
                pid=process.pid,
                phase=self.phase,
                iteration=self.iteration,
                admitted_ns=time.perf_counter_ns(),
            )
            with self._observation_lock:
                self._tracked.append((process, record))
            if on_start is not None:
                on_start()

        try:
            return super().run(node, command, settings, on_start=observe_start)
        finally:
            if process is not None:
                returned_ns = time.perf_counter_ns()
                returncode = process.poll()
                waited = False
                try:
                    waited = process.wait(timeout=0) is not None
                except (OSError, subprocess.TimeoutExpired):
                    pass
                with self._observation_lock:
                    record.update(
                        executor_returned_ns=returned_ns,
                        returncode_after_run=returncode,
                        active_after_run=returncode is None,
                        wait_verified_after_run=waited,
                        pipes_closed_after_run=all(
                            stream is None or stream.closed
                            for stream in (process.stdin, process.stdout, process.stderr)
                        ),
                    )

    def lifecycle_summary(self) -> dict[str, Any]:
        with self._observation_lock:
            workers = [
                {
                    **record,
                    "active_final": process.poll() is None,
                    "pipes_closed_final": all(
                        stream is None or stream.closed
                        for stream in (process.stdin, process.stdout, process.stderr)
                    ),
                }
                for process, record in self._tracked
            ]
        return {
            "scope": "only worker Popen objects owned by this benchmark executor",
            "tracked_worker_count": len(workers),
            "active_children_final": sum(w["active_final"] for w in workers),
            "orphaned_children_detected": sum(w.get("active_after_run", False) for w in workers),
            "orphan_definition": "tracked worker still active immediately after executor.run",
            "system_wide_orphans": "not_measured",
            "native_process_handle_closure": "not_measured",
            "production_wait_call_trace": "not_measured; post-return wait(0) verified separately",
            "workers": workers,
        }

    def close(self) -> None:
        super().close()
        # Timeout paths may leave Python pipe objects open. Record the production
        # state above, then close only these owned resources during benchmark teardown.
        with self._observation_lock:
            tracked = list(self._tracked)
        for process, _ in tracked:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1.0)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


class ObservedConnectivityService(ConnectivityService):
    """Time the real service call, including inventory lookup and observation persistence."""

    def begin_cycle(self, config: Configuration, phase: str, iteration: int, start: int) -> None:
        self._sample_config = config
        self._sample_phase = phase
        self._sample_iteration = iteration
        self._cycle_start = start
        self.probe_samples: list[dict[str, Any]] = []
        self._sample_lock = threading.Lock()

    def check(self, node_id: int) -> ConnectivityObservation:
        started_ns = time.perf_counter_ns()
        result = "ERROR"
        try:
            observation = super().check(node_id)
            result = observation.outcome.value
            return observation
        except Exception as exc:
            result = f"ERROR: {type(exc).__name__}"
            raise
        finally:
            ended_ns = time.perf_counter_ns()
            sample = {
                "scenario": self._sample_config.scenario,
                "transport": self._sample_config.transport,
                "fleet_size": self._sample_config.fleet_size,
                "sample_type": "probe",
                "phase": self._sample_phase,
                "iteration": self._sample_iteration,
                "node_id": node_id,
                "result": result,
                "started_ns": started_ns,
                "ended_ns": ended_ns,
                "elapsed_ns": ended_ns - started_ns,
                "schedule_delay_ns": started_ns - self._cycle_start,
            }
            with self._sample_lock:
                self.probe_samples.append(sample)


class ControlledTransport:
    """Stage 1: Acknowledge entry after admission; hold every call until explicit release."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.condition = threading.Condition()
        self.release = threading.Event()
        self.active = 0
        self.peak = 0

    def execute(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        with self.condition:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.condition.notify_all()
        try:
            if not self.release.wait(self.timeout_seconds):
                raise RuntimeError("controlled transport release watchdog expired")
            return OperationExecutionResult(
                OperationOutcome.SUCCESS, None, 0, "controlled", "", False
            )
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    def wait_until_full(self, capacity: int) -> None:
        with self.condition:
            if not self.condition.wait_for(lambda: self.active >= capacity, self.timeout_seconds):
                raise RuntimeError("admission readiness watchdog expired")


class SyntheticOperationTransport:
    """Stage 2: Deterministic in-process transport returning valid OperationExecutionResult.

    Implements OperationTransport protocol. Supports both immediate unheld execution
    and synchronized admission holding.
    """

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        *,
        hold_until_release: bool = False,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.hold_until_release = hold_until_release
        self.condition = threading.Condition()
        self.release = threading.Event()
        self.active = 0
        self.peak = 0
        self.entry_timestamps: dict[int, int] = {}

    def execute(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        entry_ns = time.perf_counter_ns()
        with self.condition:
            self.entry_timestamps[node.id] = entry_ns
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.condition.notify_all()
        try:
            if self.hold_until_release:
                if not self.release.wait(self.timeout_seconds):
                    raise RuntimeError("synthetic transport release watchdog expired")
            return OperationExecutionResult(
                OperationOutcome.SUCCESS,
                None,
                0,
                " 08:35:00 up 10 days,  2:15,  1 user,  load average: 0.05, 0.03, 0.01\n",
                "",
                False,
            )
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    def wait_until_active(self, expected_count: int) -> None:
        with self.condition:
            if not self.condition.wait_for(
                lambda: self.active >= expected_count, self.timeout_seconds
            ):
                raise RuntimeError("synthetic transport readiness watchdog expired")


class LoopbackSSHServerInterface(paramiko.ServerInterface):
    """In-process Paramiko SSH server interface handling authentication and command exec."""

    def __init__(
        self,
        accepted_key: paramiko.PKey,
        simulated_delay_sec: float = 0.0,
    ) -> None:
        self.accepted_key = accepted_key
        self.simulated_delay_sec = simulated_delay_sec

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        if username == "fleet-observer" and key == self.accepted_key:
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return "publickey"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        if kind == "session":
            return OPEN_SUCCEEDED
        return OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel: paramiko.Channel, command: bytes) -> bool:
        delay = self.simulated_delay_sec

        def handle_exec() -> None:
            try:
                if delay > 0:
                    time.sleep(delay)
                channel.send(
                    b" 08:55:00 up 10 days,  2:30,  1 user,  load average: 0.08, 0.05, 0.02\n"
                )
                channel.send_exit_status(0)
                time.sleep(0.05)
                channel.close()
            except Exception:
                pass

        threading.Thread(target=handle_exec, daemon=True).start()
        return True


@contextmanager
def loopback_ssh_cluster(
    num_nodes: int,
    base_dir: Path,
    timeout_seconds: float = 30.0,
    simulated_delay_sec: float = 0.0,
) -> Iterator[tuple[list[int], SSHSettings]]:
    """Context manager spinning up an isolated multi-port in-process loopback SSH server."""
    host_key = paramiko.RSAKey.generate(2048)
    client_key = paramiko.RSAKey.generate(2048)
    key_path = base_dir / "id_rsa_benchmark"
    client_key.write_private_key_file(str(key_path))

    listeners: list[socket.socket] = []
    ports: list[int] = []
    known_hosts_lines: list[str] = []

    for _ in range(num_nodes):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(5)
        s.settimeout(0.5)
        p = s.getsockname()[1]
        listeners.append(s)
        ports.append(p)
        known_hosts_lines.append(f"[127.0.0.1]:{p} {host_key.get_name()} {host_key.get_base64()}\n")

    known_hosts_path = base_dir / "known_hosts_benchmark"
    known_hosts_path.write_text("".join(known_hosts_lines), encoding="ascii")

    settings = SSHSettings(
        "fleet-observer",
        known_hosts_path,
        key_path,
        banner_timeout_seconds=15.0,
        connect_timeout_seconds=10.0,
        authentication_timeout_seconds=10.0,
    )

    stop_event = threading.Event()
    active_transports: list[paramiko.Transport] = []
    transports_lock = threading.Lock()

    def handle_client(conn: socket.socket) -> None:
        with conn:
            transport = paramiko.Transport(conn)
            with transports_lock:
                active_transports.append(transport)
            try:
                transport.add_server_key(host_key)
                transport.start_server(
                    server=LoopbackSSHServerInterface(client_key, simulated_delay_sec)
                )
                chan = transport.accept(10)
                deadline = time.monotonic() + 10
                while transport.is_active() and time.monotonic() < deadline:
                    if chan is not None and chan.closed:
                        time.sleep(0.05)
                        break
                    time.sleep(0.02)
            except (EOFError, OSError, paramiko.SSHException):
                pass
            finally:
                transport.close()
                with transports_lock:
                    if transport in active_transports:
                        active_transports.remove(transport)

    def serve_listener(sock: socket.socket) -> None:
        while not stop_event.is_set():
            try:
                conn, _ = sock.accept()
                threading.Thread(target=handle_client, args=(conn,), daemon=True).start()
            except TimeoutError:
                continue
            except OSError:
                break

    server_threads = [
        threading.Thread(target=serve_listener, args=(s,), daemon=True) for s in listeners
    ]
    for st in server_threads:
        st.start()

    try:
        yield ports, settings
    finally:
        stop_event.set()
        for s in listeners:
            try:
                s.close()
            except Exception:
                pass
        for st in server_threads:
            st.join(timeout=1.0)
        with transports_lock:
            for t in list(active_transports):
                try:
                    t.close()
                except Exception:
                    pass
            active_transports.clear()


def active_metric(telemetry: Telemetry) -> float:
    return sum(sample.value for sample in telemetry.operations_active.collect())


def git_output(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def measure(
    service: OperationService,
    node: Node,
    phase: str,
    iteration: int,
    config: Configuration,
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    try:
        record = service.execute(node.id, ACTION, {}, OPERATOR_DIGEST)
        result = record.outcome.value
    except OperationBusy:
        result = "OperationBusy"
    ended = time.perf_counter_ns()
    return {
        "scenario": config.scenario,
        "transport": config.transport,
        "fleet_size": config.requests,
        "sample_type": "admission",
        "phase": phase,
        "iteration": iteration,
        "node_id": node.id,
        "result": result,
        "started_ns": started,
        "ended_ns": ended,
        "elapsed_ns": ended - started,
    }


def run_round(
    config: Configuration,
    service: OperationService,
    nodes: list[Node],
    telemetry: Telemetry,
    phase: str,
    iteration: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    transport = ControlledTransport(config.timeout_seconds)
    executor = service.executor
    if not isinstance(executor, DirectOperationExecutor):
        raise TypeError("controlled scenario requires DirectOperationExecutor")
    executor.transport = transport
    prefix = f"benchmark-{uuid.uuid4().hex}"
    pool = ThreadPoolExecutor(max_workers=config.max_concurrent, thread_name_prefix=prefix)
    samples: list[dict[str, Any]] = []
    try:
        admitted = [
            pool.submit(measure, service, node, phase, iteration, config)
            for node in nodes[: config.max_concurrent]
        ]
        transport.wait_until_full(config.max_concurrent)
        held = active_metric(telemetry)
        if held != config.max_concurrent:
            raise RuntimeError("active metric does not match occupied capacity")
        for node in nodes[config.max_concurrent :]:
            sample = measure(service, node, phase, iteration, config)
            samples.append(sample)
            if sample["result"] != "OperationBusy" or active_metric(telemetry) != held:
                raise RuntimeError("capacity rejection failed while all slots were held")
    finally:
        transport.release.set()
        pool.shutdown(wait=True, cancel_futures=True)
        remaining = sum(t.name.startswith(prefix) for t in threading.enumerate())
        if remaining or transport.active or active_metric(telemetry):
            raise RuntimeError("scenario cleanup left active work or threads")
    samples.extend(future.result() for future in admitted)
    samples.sort(key=lambda item: item["node_id"])
    accepted_count = sum(item["result"] == "SUCCESS" for item in samples)
    rejected_count = sum(item["result"] == "OperationBusy" for item in samples)
    if (
        accepted_count != config.max_concurrent
        or rejected_count != config.requests - config.max_concurrent
        or transport.peak != config.max_concurrent
    ):
        raise RuntimeError("admission counts or peak executions violated configured capacity")
    return samples, {
        "phase": phase,
        "iteration": iteration,
        "admitted": accepted_count,
        "rejected": rejected_count,
        "peak_active": transport.peak,
        "active_while_held": held,
        "active_after_release": active_metric(telemetry),
        "transport_active_after_release": transport.active,
        "threads_remaining": remaining,
    }


def run_direct_execution_baseline(
    config: Configuration,
    service: OperationService,
    nodes: list[Node],
    telemetry: Telemetry,
    phase: str,
    iteration: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Section 4.A: Direct execution baseline across distinct nodes without holding."""
    transport = SyntheticOperationTransport(config.timeout_seconds, hold_until_release=False)
    executor = service.executor
    if not isinstance(executor, DirectOperationExecutor):
        raise TypeError("direct scenario requires DirectOperationExecutor")
    executor.transport = transport

    samples: list[dict[str, Any]] = []
    cycle_started = time.perf_counter_ns()
    for node in nodes:
        started = time.perf_counter_ns()
        record = service.execute(node.id, ACTION, {}, OPERATOR_DIGEST)
        ended = time.perf_counter_ns()
        if record.outcome != OperationOutcome.SUCCESS:
            raise RuntimeError(f"unexpected baseline execution outcome: {record.outcome}")
        samples.append(
            {
                "scenario": config.scenario,
                "transport": config.transport,
                "fleet_size": config.fleet_size,
                "sample_type": "execution",
                "phase": phase,
                "iteration": iteration,
                "node_id": node.id,
                "result": record.outcome.value,
                "started_ns": started,
                "ended_ns": ended,
                "elapsed_ns": ended - started,
            }
        )
    cycle_ended = time.perf_counter_ns()
    cycle_duration_ns = cycle_ended - cycle_started
    duration_sec = cycle_duration_ns / 1_000_000_000.0
    ops_per_second = len(nodes) / duration_sec if duration_sec > 0 else 0.0

    if active_metric(telemetry) != 0 or transport.active != 0:
        raise RuntimeError("active work remained after direct execution baseline")

    for node in nodes:
        records = service.list_operations_for_node(node.id, limit=10)
        if not records or records[0].outcome != OperationOutcome.SUCCESS:
            raise RuntimeError(f"persisted record verification failed for node {node.id}")

    return samples, {
        "cycle_duration_ns": cycle_duration_ns,
        "ops_per_second": ops_per_second,
        "success_count": len(nodes),
        "failed_count": 0,
    }


def run_direct_admission_scenario(
    config: Configuration,
    service: OperationService,
    nodes: list[Node],
    telemetry: Telemetry,
    phase: str,
    iteration: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Section 4.B: Deterministic operation admission scenario with synchronization."""
    transport = SyntheticOperationTransport(config.timeout_seconds, hold_until_release=True)
    executor = service.executor
    if not isinstance(executor, DirectOperationExecutor):
        raise TypeError("direct scenario requires DirectOperationExecutor")
    executor.transport = transport

    expected_admitted = min(len(nodes), config.max_concurrent)
    expected_rejected = max(0, len(nodes) - config.max_concurrent)

    prefix = f"benchmark-direct-{uuid.uuid4().hex}"
    pool = ThreadPoolExecutor(max_workers=len(nodes), thread_name_prefix=prefix)
    barrier = threading.Barrier(len(nodes) + 1)
    condition = threading.Condition()
    settled_results: list[dict[str, Any]] = []

    def execute_node(node: Node) -> None:
        barrier.wait(timeout=config.timeout_seconds)
        started = time.perf_counter_ns()
        try:
            service.execute(node.id, ACTION, {}, OPERATOR_DIGEST)
            admitted_ns = transport.entry_timestamps.get(node.id, started)
            sample = {
                "scenario": config.scenario,
                "transport": config.transport,
                "fleet_size": config.fleet_size,
                "sample_type": "admission",
                "phase": phase,
                "iteration": iteration,
                "node_id": node.id,
                "result": "ADMITTED",
                "started_ns": started,
                "ended_ns": admitted_ns,
                "elapsed_ns": admitted_ns - started,
            }
        except OperationBusy:
            ended = time.perf_counter_ns()
            sample = {
                "scenario": config.scenario,
                "transport": config.transport,
                "fleet_size": config.fleet_size,
                "sample_type": "admission",
                "phase": phase,
                "iteration": iteration,
                "node_id": node.id,
                "result": "OperationBusy",
                "started_ns": started,
                "ended_ns": ended,
                "elapsed_ns": ended - started,
            }
        with condition:
            settled_results.append(sample)
            condition.notify_all()

    try:
        futures = [pool.submit(execute_node, node) for node in nodes]
        barrier.wait(timeout=config.timeout_seconds)

        transport.wait_until_active(expected_admitted)

        with condition:
            if not condition.wait_for(
                lambda: (
                    (
                        sum(s["result"] == "ADMITTED" for s in settled_results)
                        + sum(s["result"] == "OperationBusy" for s in settled_results)
                    )
                    >= len(nodes)
                    or (
                        transport.active >= expected_admitted
                        and sum(s["result"] == "OperationBusy" for s in settled_results)
                        >= expected_rejected
                    )
                ),
                config.timeout_seconds,
            ):
                raise RuntimeError("admission settlement watchdog expired")

        held_active = active_metric(telemetry)
        if held_active != expected_admitted:
            raise RuntimeError(
                f"active telemetry ({held_active}) != expected ({expected_admitted})"
            )
        if transport.peak != expected_admitted:
            raise RuntimeError(
                f"peak transport active ({transport.peak}) != expected ({expected_admitted})"
            )

    finally:
        transport.release.set()
        pool.shutdown(wait=True, cancel_futures=False)
        remaining = sum(t.name.startswith(prefix) for t in threading.enumerate())
        if remaining or transport.active or active_metric(telemetry):
            raise RuntimeError("admission scenario cleanup left active work or threads")

    for f in futures:
        f.result()

    admitted_count = sum(s["result"] == "ADMITTED" for s in settled_results)
    rejected_count = sum(s["result"] == "OperationBusy" for s in settled_results)

    if admitted_count != expected_admitted or rejected_count != expected_rejected:
        raise RuntimeError(
            f"admission counts mismatch: admitted={admitted_count} (exp {expected_admitted}), "
            f"rejected={rejected_count} (exp {expected_rejected})"
        )

    settled_results.sort(key=lambda s: s["node_id"])
    return settled_results, {
        "admitted": admitted_count,
        "rejected": rejected_count,
        "peak_active": transport.peak,
        "held_active": held_active,
        "final_active": active_metric(telemetry),
        "threads_remaining": remaining,
    }


def run_bounded_operations(
    config: Configuration,
    service: OperationService,
    nodes: list[Node],
    telemetry: Telemetry,
    phase: str,
    iteration: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Runs fleet operations using bounded client orchestration (concurrency <= max_concurrent)."""
    prefix = f"benchmark-op-{uuid.uuid4().hex}"
    pool = ThreadPoolExecutor(max_workers=config.max_concurrent, thread_name_prefix=prefix)

    cycle_start = time.perf_counter_ns()

    def execute_node(node: Node, submit_ns: int) -> dict[str, Any]:
        dispatch_ns = time.perf_counter_ns()
        exec_start_ns = dispatch_ns
        try:
            record = service.execute(node.id, ACTION, {}, OPERATOR_DIGEST)
            outcome_val = record.outcome.value
        except Exception as exc:
            outcome_val = f"ERROR: {type(exc).__name__}"
        exec_end_ns = time.perf_counter_ns()
        return {
            "scenario": config.scenario,
            "transport": config.transport,
            "fleet_size": config.fleet_size,
            "sample_type": "execution",
            "phase": phase,
            "iteration": iteration,
            "node_id": node.id,
            "result": outcome_val,
            "started_ns": exec_start_ns,
            "ended_ns": exec_end_ns,
            "elapsed_ns": exec_end_ns - exec_start_ns,
            "schedule_delay_ns": dispatch_ns - submit_ns,
        }

    futures = []
    for node in nodes:
        now_ns = time.perf_counter_ns()
        futures.append(pool.submit(execute_node, node, now_ns))

    pool.shutdown(wait=True, cancel_futures=False)
    cycle_end = time.perf_counter_ns()
    cycle_duration_ns = cycle_end - cycle_start
    duration_sec = cycle_duration_ns / 1_000_000_000.0
    ops_per_second = len(nodes) / duration_sec if duration_sec > 0 else 0.0

    samples = [f.result() for f in futures]
    samples.sort(key=lambda s: s["node_id"])

    if active_metric(telemetry) != 0:
        raise RuntimeError("active operations telemetry did not return to 0")

    success_count = sum(s["result"] == "SUCCESS" for s in samples)
    failed_count = sum(s["result"] != "SUCCESS" for s in samples)

    for node in nodes:
        recs = service.list_operations_for_node(node.id, limit=10)
        if not recs or recs[0].outcome != OperationOutcome.SUCCESS:
            raise RuntimeError(f"operation persistence verification failed for node {node.id}")

    return samples, {
        "cycle_duration_ns": cycle_duration_ns,
        "ops_per_second": ops_per_second,
        "success_count": success_count,
        "failed_count": failed_count,
    }


async def run_scheduler_fleet_round(
    config: Configuration,
    scheduler: ConnectivityScheduler,
    service: ObservedConnectivityService,
    nodes: list[Node],
    telemetry: Telemetry,
    phase: str,
    iteration: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Runs one full periodic connectivity monitoring sweep via
    ConnectivityScheduler.run_cycle().
    """
    cycle_start = time.perf_counter_ns()
    service.begin_cycle(config, phase, iteration, cycle_start)
    await scheduler.run_cycle()
    cycle_end = time.perf_counter_ns()

    cycle_duration_ns = cycle_end - cycle_start
    duration_sec = cycle_duration_ns / 1_000_000_000.0
    checks_per_sec = len(nodes) / duration_sec if duration_sec > 0 else 0.0

    samples = sorted(service.probe_samples, key=lambda sample: sample["node_id"])
    failed_checks = sum(s["result"] != "CONNECTED" for s in samples)
    completed_checks = len(samples)
    samples.append(
        {
            "scenario": config.scenario,
            "transport": config.transport,
            "fleet_size": config.fleet_size,
            "sample_type": "fleet_cycle",
            "phase": phase,
            "iteration": iteration,
            "node_id": 0,
            "result": "COMPLETED",
            "started_ns": cycle_start,
            "ended_ns": cycle_end,
            "elapsed_ns": cycle_duration_ns,
            "schedule_delay_ns": 0,
        }
    )

    active_checks = sum(s.value for s in telemetry.connectivity_active_checks.collect())
    if active_checks != 0:
        raise RuntimeError(f"connectivity active checks did not return to 0 (got {active_checks})")

    skipped_samples = telemetry.scheduler_checks_skipped_total.collect()
    skipped_reasons = {
        s.labels.get("reason", "unknown"): s.value for s in skipped_samples if s.value > 0
    }

    return samples, {
        "cycle_duration_ns": cycle_duration_ns,
        "effective_checks_per_sec": checks_per_sec,
        "completed_checks": completed_checks,
        "failed_checks": failed_checks,
        "skipped_checks_by_reason": skipped_reasons,
    }


def run_benchmark(config: Configuration) -> tuple[dict[str, Any], Path, Path]:
    config.validate()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        raise ValueError("benchmark requires Windows-native Python 3.12")

    if config.scenario == SCENARIO_ADMISSION:
        prefix = f"admission-{uuid.uuid4().hex}"
    else:
        prefix = f"{config.scenario}-{config.fleet_size}node-{uuid.uuid4().hex}"
    run_dir = config.output_dir.resolve() / prefix
    run_dir.mkdir(parents=True, exist_ok=False)

    samples: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    status = git_output("status", "--porcelain")

    with TemporaryDirectory(prefix="database-", dir=run_dir) as temporary:
        temporary_dir = Path(temporary)
        database = temporary_dir / "benchmark.db"
        inventory = SQLiteNodeRepository(database)
        inventory.initialize()
        connectivity_repo = SQLiteConnectivityRepository(database)
        connectivity_repo.initialize()
        operations_repo = SQLiteOperationsRepository(database)
        operations_repo.initialize()

        with closing(sqlite3.connect(database)) as connection:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

        telemetry = Telemetry()

        if config.scenario == SCENARIO_ADMISSION:
            nodes = [
                inventory.add_node(NewNode(f"bench-{i}", f"node-{i}.invalid", 22))
                for i in range(config.requests)
            ]
            adm_executor = DirectOperationExecutor(
                ControlledTransport(config.timeout_seconds),
                OperationLimits(max_concurrent=config.max_concurrent),
            )
            service = OperationService(
                inventory,
                operations_repo,
                adm_executor,
                SSHSettings(
                    "benchmark",
                    temporary_dir / "unused-hosts",
                    temporary_dir / "unused-key",
                ),
                telemetry,
            )
            try:
                for iteration in range(config.warmup + config.repetitions):
                    phase = "warmup" if iteration < config.warmup else "measurement"
                    raw, counts = run_round(config, service, nodes, telemetry, phase, iteration)
                    samples.extend(raw)
                    rounds.append(counts)
            finally:
                adm_executor.close()

            measured = [s for s in samples if s["phase"] == "measurement"]
            rejected = [s["elapsed_ns"] for s in measured if s["result"] == "OperationBusy"]
            summary: dict[str, Any] = {
                "sample_count": len(measured),
                "admitted": len(measured) - len(rejected),
                "rejected": len(rejected),
                "rejection_latency_ns": percentiles(rejected),
            }
            method_info: dict[str, Any] = {
                "clock": "time.perf_counter_ns",
                "unit": "nanoseconds",
                "percentile": "linear interpolation at (n - 1) * p; Hyndman-Fan type 7",
                "measurement_boundary": "OperationService.execute entry to return or OperationBusy",
                "ordering": (
                    "fill capacity, await transport entry, "
                    "reject remaining nodes sequentially, release"
                ),
                "warmup": "raw samples retained; excluded from summary",
                "limitations": (
                    "controlled in-process transport; admitted timings include artificial hold; "
                    "no HTTP, SSH or process-worker performance claim"
                ),
            }
            schema_version = 1

        elif config.scenario == SCENARIO_OPERATION_DIRECT:
            nodes = [
                inventory.add_node(NewNode(f"direct-node-{i}", f"node-{i}.benchmark.local", 22))
                for i in range(config.fleet_size)
            ]
            direct_executor = DirectOperationExecutor(
                SyntheticOperationTransport(config.timeout_seconds),
                OperationLimits(max_concurrent=config.max_concurrent),
            )
            service = OperationService(
                inventory,
                operations_repo,
                direct_executor,
                SSHSettings(
                    "benchmark",
                    temporary_dir / "unused-hosts",
                    temporary_dir / "unused-key",
                ),
                telemetry,
            )
            try:
                for iteration in range(config.warmup + config.repetitions):
                    phase = "warmup" if iteration < config.warmup else "measurement"
                    exec_samples, exec_stats = run_direct_execution_baseline(
                        config, service, nodes, telemetry, phase, iteration
                    )
                    adm_samples, adm_stats = run_direct_admission_scenario(
                        config, service, nodes, telemetry, phase, iteration
                    )
                    samples.extend(exec_samples)
                    samples.extend(adm_samples)
                    rounds.append(
                        {
                            "phase": phase,
                            "iteration": iteration,
                            "execution": exec_stats,
                            "admission": adm_stats,
                        }
                    )
            finally:
                direct_executor.close()

            measured_exec = [
                s
                for s in samples
                if s["phase"] == "measurement" and s["sample_type"] == "execution"
            ]
            measured_adm = [
                s
                for s in samples
                if s["phase"] == "measurement" and s["sample_type"] == "admission"
            ]
            exec_latencies = [s["elapsed_ns"] for s in measured_exec]
            admitted_latencies = [
                s["elapsed_ns"] for s in measured_adm if s["result"] == "ADMITTED"
            ]
            rejected_latencies = [
                s["elapsed_ns"] for s in measured_adm if s["result"] == "OperationBusy"
            ]

            measured_rounds = [r for r in rounds if r["phase"] == "measurement"]
            cycle_durations = [r["execution"]["cycle_duration_ns"] for r in measured_rounds]
            throughputs = [r["execution"]["ops_per_second"] for r in measured_rounds]

            summary = {
                "fleet_size": config.fleet_size,
                "max_concurrent": config.max_concurrent,
                "sample_count": len(measured_exec) + len(measured_adm),
                "execution": {
                    "sample_count": len(measured_exec),
                    "success_count": sum(s["result"] == "SUCCESS" for s in measured_exec),
                    "failure_count": sum(s["result"] != "SUCCESS" for s in measured_exec),
                    "latency_ns": percentiles(exec_latencies) if exec_latencies else None,
                    "fleet_cycle_duration_ns": (
                        percentiles(cycle_durations) if cycle_durations else None
                    ),
                    "throughput_ops_per_sec": (percentiles(throughputs) if throughputs else None),
                },
                "admission": {
                    "sample_count": len(measured_adm),
                    "admitted_count": len(admitted_latencies),
                    "rejected_count": len(rejected_latencies),
                    "admitted_latency_ns": (
                        percentiles(admitted_latencies) if admitted_latencies else None
                    ),
                    "rejection_latency_ns": (
                        percentiles(rejected_latencies) if rejected_latencies else None
                    ),
                },
                "telemetry_verification": {
                    "operations_active_final": active_metric(telemetry),
                    "operations_total": sum(s.value for s in telemetry.operations_total.collect()),
                    "duration_histogram_present": bool(
                        telemetry.operation_duration_seconds.collect()
                    ),
                },
            }
            method_info = {
                "clock": "time.perf_counter_ns",
                "unit": "nanoseconds",
                "percentile": "linear interpolation at (n - 1) * p; Hyndman-Fan type 7",
                "measurement_boundary": (
                    "Execution: OperationService.execute entry to completion (unheld); "
                    "Admission: OperationService.execute entry to transport entry "
                    "(admitted) or OperationBusy (rejected)"
                ),
                "fleet_size": config.fleet_size,
                "max_concurrent": config.max_concurrent,
                "warmup": "raw samples retained; excluded from summary",
                "limitations": (
                    "synthetic in-process transport baseline; "
                    "does not measure SSH or subprocess overhead; "
                    "no external network or host"
                ),
            }
            schema_version = 2

        elif config.scenario in (SCENARIO_OPERATION_LOOPBACK, SCENARIO_OPERATION_PROCESS):
            delay_sec = config.simulated_delay_ms / 1000.0
            with loopback_ssh_cluster(
                config.fleet_size,
                temporary_dir,
                config.timeout_seconds,
                simulated_delay_sec=delay_sec,
            ) as (ports, ssh_settings):
                nodes = [
                    inventory.add_node(NewNode(f"ssh-node-{i}", "127.0.0.1", port))
                    for i, port in enumerate(ports)
                ]
                op_limits = OperationLimits(max_concurrent=config.max_concurrent)

                op_executor: DirectOperationExecutor | ProcessOperationExecutor
                if config.scenario == SCENARIO_OPERATION_LOOPBACK:
                    op_executor = DirectOperationExecutor(
                        ParamikoOperationTransport(), limits=op_limits
                    )
                else:
                    op_executor = ObservedProcessOperationExecutor(op_limits)

                service = OperationService(
                    inventory,
                    operations_repo,
                    op_executor,
                    ssh_settings=ssh_settings,
                    telemetry=telemetry,
                )
                try:
                    for iteration in range(config.warmup + config.repetitions):
                        phase = "warmup" if iteration < config.warmup else "measurement"
                        if isinstance(op_executor, ObservedProcessOperationExecutor):
                            op_executor.phase = phase
                            op_executor.iteration = iteration
                        op_samples, op_counts = run_bounded_operations(
                            config, service, nodes, telemetry, phase, iteration
                        )
                        samples.extend(op_samples)
                        rounds.append(
                            {"phase": phase, "iteration": iteration, "execution": op_counts}
                        )
                finally:
                    op_executor.close()

            measured_exec = [s for s in samples if s["phase"] == "measurement"]
            exec_latencies = [s["elapsed_ns"] for s in measured_exec]
            schedule_delays = [
                s["schedule_delay_ns"] for s in measured_exec if "schedule_delay_ns" in s
            ]
            measured_rounds = [r for r in rounds if r["phase"] == "measurement"]
            cycle_durations = [r["execution"]["cycle_duration_ns"] for r in measured_rounds]
            throughputs = [r["execution"]["ops_per_second"] for r in measured_rounds]

            summary = {
                "fleet_size": config.fleet_size,
                "max_concurrent": config.max_concurrent,
                "sample_count": len(measured_exec),
                "execution": {
                    "sample_count": len(measured_exec),
                    "success_count": sum(s["result"] == "SUCCESS" for s in measured_exec),
                    "failure_count": sum(s["result"] != "SUCCESS" for s in measured_exec),
                    "latency_ns": percentiles(exec_latencies) if exec_latencies else None,
                    "schedule_delay_ns": (
                        percentiles(schedule_delays) if schedule_delays else None
                    ),
                    "fleet_cycle_duration_ns": (
                        percentiles(cycle_durations) if cycle_durations else None
                    ),
                    "throughput_ops_per_sec": (percentiles(throughputs) if throughputs else None),
                },
                "worker_lifecycle": (
                    op_executor.lifecycle_summary()
                    if isinstance(op_executor, ObservedProcessOperationExecutor)
                    else {"status": "not_applicable; direct in-process execution"}
                ),
                "telemetry_verification": {
                    "operations_active_final": active_metric(telemetry),
                    "operations_total": sum(s.value for s in telemetry.operations_total.collect()),
                    "duration_histogram_present": bool(
                        telemetry.operation_duration_seconds.collect()
                    ),
                },
            }
            method_info = {
                "clock": "time.perf_counter_ns",
                "unit": "nanoseconds",
                "percentile": "linear interpolation at (n - 1) * p; Hyndman-Fan type 7",
                "measurement_boundary": (
                    "OperationService.execute entry to return over real Paramiko SSH channel; "
                    "client orchestration bounded by max_concurrent"
                ),
                "fleet_size": config.fleet_size,
                "max_concurrent": config.max_concurrent,
                "simulated_delay_ms": config.simulated_delay_ms,
                "execution_timeout_seconds": op_limits.total_timeout_seconds,
                "warmup": "raw samples retained; excluded from summary",
                "limitations": (
                    "ephemeral loopback SSH server on 127.0.0.1; strict host-key verification; "
                    "complete execution-path timing; no isolated crypto, wire or spawn timings; "
                    "process observer overhead and post-return wait verification included"
                ),
            }
            schema_version = 3 if config.scenario == SCENARIO_OPERATION_PROCESS else 2

        elif config.scenario == SCENARIO_SCHEDULER_FLEET:
            delay_sec = config.simulated_delay_ms / 1000.0
            with loopback_ssh_cluster(
                config.fleet_size,
                temporary_dir,
                config.timeout_seconds,
                simulated_delay_sec=delay_sec,
            ) as (ports, ssh_settings):
                nodes = [
                    inventory.add_node(NewNode(f"sched-node-{i}", "127.0.0.1", port))
                    for i, port in enumerate(ports)
                ]
                conn_limits = ConnectivityLimits(
                    max_concurrent=config.max_concurrent,
                    total_timeout_seconds=config.timeout_seconds,
                )
                conn_executor = ProcessSSHExecutor(conn_limits)
                conn_service = ObservedConnectivityService(
                    inventory,
                    connectivity_repo,
                    conn_executor,
                    settings=ssh_settings,
                    telemetry=telemetry,
                )

                async def run_all_scheduler_rounds() -> tuple[
                    list[dict[str, Any]], list[dict[str, Any]]
                ]:
                    all_s: list[dict[str, Any]] = []
                    all_r: list[dict[str, Any]] = []
                    sched = ConnectivityScheduler(
                        conn_service,
                        interval_seconds=60.0,
                        max_concurrent=config.max_concurrent,
                        telemetry=telemetry,
                    )
                    for iteration in range(config.warmup + config.repetitions):
                        phase = "warmup" if iteration < config.warmup else "measurement"
                        round_samples, round_stats = await run_scheduler_fleet_round(
                            config, sched, conn_service, nodes, telemetry, phase, iteration
                        )
                        all_s.extend(round_samples)
                        all_r.append(
                            {"phase": phase, "iteration": iteration, "scheduler": round_stats}
                        )
                    return all_s, all_r

                try:
                    s_samples, s_rounds = asyncio.run(run_all_scheduler_rounds())
                    samples.extend(s_samples)
                    rounds.extend(s_rounds)
                finally:
                    conn_executor.close()

            measured_probes = [
                s for s in samples if s["phase"] == "measurement" and s["sample_type"] == "probe"
            ]
            probe_latencies = [s["elapsed_ns"] for s in measured_probes]
            measured_rounds = [r for r in rounds if r["phase"] == "measurement"]
            cycle_durations = [r["scheduler"]["cycle_duration_ns"] for r in measured_rounds]
            checks_per_sec = [r["scheduler"]["effective_checks_per_sec"] for r in measured_rounds]

            skipped_samples = telemetry.scheduler_checks_skipped_total.collect()
            skipped_reasons = {
                s.labels.get("reason", "unknown"): s.value for s in skipped_samples if s.value > 0
            }

            summary = {
                "fleet_size": config.fleet_size,
                "max_concurrent": config.max_concurrent,
                "sample_count": len(measured_probes),
                "scheduler": {
                    "cycle_count": len(measured_rounds),
                    "fleet_cycle_duration_ns": (
                        percentiles(cycle_durations) if cycle_durations else None
                    ),
                    "effective_checks_per_sec": (
                        percentiles(checks_per_sec) if checks_per_sec else None
                    ),
                    "probe_latency_ns": percentiles(probe_latencies) if probe_latencies else None,
                    "schedule_delay_ns": (
                        percentiles([s["schedule_delay_ns"] for s in measured_probes])
                        if measured_probes
                        else None
                    ),
                    "completed_checks": len(measured_probes),
                    "failed_checks": sum(s["result"] != "CONNECTED" for s in measured_probes),
                    "skipped_checks_by_reason": skipped_reasons,
                },
                "telemetry_verification": {
                    "connectivity_active_final": sum(
                        s.value for s in telemetry.connectivity_active_checks.collect()
                    ),
                    "scheduler_cycles_total": sum(
                        s.value for s in telemetry.scheduler_cycles_total.collect()
                    ),
                    "scheduler_running": sum(
                        s.value for s in telemetry.scheduler_running.collect()
                    ),
                },
            }
            method_info = {
                "clock": "time.perf_counter_ns",
                "unit": "nanoseconds",
                "percentile": "linear interpolation at (n - 1) * p; Hyndman-Fan type 7",
                "measurement_boundary": (
                    "probe: real ConnectivityService.check entry to return/raise, including "
                    "inventory lookup, process SSH check, telemetry and SQLite persistence; "
                    "fleet_cycle: ConnectivityScheduler.run_cycle entry to return; "
                    "schedule_delay_ns: cycle entry to this node's service-check entry, "
                    "including inventory enumeration, semaphore and thread dispatch; "
                    "not isolated queue wait; fleet_cycle uses node_id=0 and delay=0 sentinel"
                ),
                "fleet_size": config.fleet_size,
                "max_concurrent": config.max_concurrent,
                "simulated_delay_ms": config.simulated_delay_ms,
                "warmup": "raw samples retained; excluded from summary",
                "limitations": (
                    "ephemeral loopback SSH server on 127.0.0.1; process-backed SSH checks; "
                    "strict host-key verification; bounded concurrency; "
                    "observer setup/recording overhead included in cycle timing; "
                    "manual run_cycle sweeps do not measure periodic timer jitter; "
                    "scheduler worker OS lifecycle not independently instrumented"
                ),
            }
            schema_version = 3

    report: dict[str, Any] = {
        "schema_version": schema_version,
        "created_at": datetime.now(UTC).isoformat(),
        "scenario": config.scenario,
        "transport": config.transport,
        "configuration": {**asdict(config), "output_dir": str(config.output_dir.resolve())},
        "environment": {
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "processor": platform.processor() or None,
            "machine": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
            "project_revision": git_output("rev-parse", "HEAD"),
            "working_tree_dirty": bool(status) if status is not None else None,
            "sqlite_version": sqlite3.sqlite_version,
            "sqlite_journal_mode": journal_mode,
        },
        "method": method_info,
        "summary": summary,
        "sample_counts": {
            "raw": len(samples),
            "warmup": sum(s["phase"] == "warmup" for s in samples),
            "measurement": sum(s["phase"] == "measurement" for s in samples),
        },
        "rounds": rounds,
        "samples": samples,
    }

    json_path, csv_path = run_dir / "results.json", run_dir / "samples.csv"
    with json_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")

    # CSV headers match the common sample schema
    fieldnames = list(dict.fromkeys(key for sample in samples for key in sample))
    with csv_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(samples)
    return report, json_path, csv_path


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    try:
        report, json_path, csv_path = run_benchmark(config)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Benchmark error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"summary": report["summary"], "json": str(json_path), "csv": str(csv_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
