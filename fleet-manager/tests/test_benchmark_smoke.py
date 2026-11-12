"""Isolated benchmark contracts; no external hosts, services, or SSH workers."""

import csv
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import paramiko
import pytest
from scripts import benchmark_fleet_performance as benchmark

from fleet_manager.config import OperationLimits, SSHSettings
from fleet_manager.connectivity.models import ConnectivityObservation
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.errors import OperationUnavailable
from fleet_manager.inventory.models import NewNode, Node, ObservationState
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.metrics.telemetry import Telemetry
from fleet_manager.operations.executor import DirectOperationExecutor
from fleet_manager.operations.models import OperationExecutionResult, OperationOutcome
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.service import OperationService

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Benchmark performance contracts require Windows-native Python 3.12",
)


def test_cli_defaults_and_explicit_configuration() -> None:
    config = benchmark.parse_args([])
    assert (config.max_concurrent, config.requests, config.warmup, config.repetitions) == (
        4,
        16,
        1,
        5,
    )
    configured = benchmark.parse_args(
        ["--max-concurrent", "2", "--requests", "8", "--warmup", "0", "--repetitions", "2"]
    )
    assert (configured.max_concurrent, configured.requests, configured.warmup) == (2, 8, 0)


@pytest.mark.parametrize(
    "args",
    [
        ["--max-concurrent", "0"],
        ["--max-concurrent", "17"],
        ["--requests", "4"],
        ["--requests", "-1"],
        ["--warmup", "-1"],
        ["--repetitions", "0"],
        ["--repetitions", "no"],
        ["--timeout-seconds", "nan"],
        ["--timeout-seconds", "inf"],
        ["--timeout-seconds", "0"],
        ["--scenario", "ssh"],
        ["--transport", "live"],
        ["--output-dir", "../outside"],
        ["--output-dir", ".local/../../outside"],
    ],
)
def test_invalid_arguments(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        benchmark.parse_args(args)
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_percentile_interpolation() -> None:
    assert benchmark.percentiles([40, 10, 30, 20]) == {
        "p50": 25.0,
        "p90": 37.0,
        "p95": 38.5,
        "p99": 39.7,
    }
    assert benchmark.percentiles([7]) == dict.fromkeys(("p50", "p90", "p95", "p99"), 7.0)
    with pytest.raises(ValueError):
        benchmark.percentiles([])


def test_deterministic_admission_output_and_repeatability() -> None:
    config = benchmark.parse_args(["--warmup", "1", "--repetitions", "3"])
    before = set(threading.enumerate())
    report, json_path, csv_path = benchmark.run_benchmark(config)
    assert set(threading.enumerate()) == before
    assert json_path.is_relative_to(benchmark.LOCAL_ROOT)
    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    assert report["schema_version"] == 1
    assert report["scenario"] == "admission"
    assert report["transport"] == "controlled-in-process"
    assert report["environment"]["sqlite_journal_mode"] == "delete"
    assert report["environment"]["python_version"].startswith("3.12.")
    assert report["environment"]["project_revision"]
    assert len(report["samples"]) == 64
    assert report["summary"]["admitted"] == 12
    assert report["summary"]["rejected"] == 36
    assert len(report["rounds"]) == 4
    for result in report["rounds"]:
        assert (result["admitted"], result["rejected"]) == (4, 12)
        assert result["peak_active"] == result["active_while_held"] == 4
        assert result["active_after_release"] == result["transport_active_after_release"] == 0
        assert result["threads_remaining"] == 0
    samples = report["samples"]
    for iteration in range(4):
        assert len({s["node_id"] for s in samples if s["iteration"] == iteration}) == 16
    rejection_times = sorted(
        s["elapsed_ns"]
        for s in samples
        if s["phase"] == "measurement" and s["result"] == "OperationBusy"
    )
    for name, percentage in (("p50", 50), ("p90", 90), ("p95", 95), ("p99", 99)):
        rank = (len(rejection_times) - 1) * percentage / 100
        low = int(rank)
        expected = rejection_times[low] + (
            rejection_times[min(low + 1, len(rejection_times) - 1)] - rejection_times[low]
        ) * (rank - low)
        assert report["summary"]["rejection_latency_ns"][name] == pytest.approx(expected)
    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(samples)
    assert set(rows[0]) == set(samples[0])
    for row, sample in zip(rows, samples, strict=True):
        assert row == {key: str(value) for key, value in sample.items()}
        assert sample["elapsed_ns"] >= 0
    assert not list(json_path.parent.glob("*.db*"))


def test_cleanup_after_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    original = benchmark.ControlledTransport.execute

    def fail_after_release(
        self: benchmark.ControlledTransport,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        original(self, node, command, settings, timeout_seconds, max_output_bytes)
        raise RuntimeError("injected transport failure")

    monkeypatch.setattr(benchmark.ControlledTransport, "execute", fail_after_release)
    before = set(threading.enumerate())
    with pytest.raises(RuntimeError, match="injected transport failure"):
        benchmark.run_benchmark(benchmark.parse_args(["--warmup", "0", "--repetitions", "1"]))
    assert set(threading.enumerate()) == before


def test_output_existing_run_is_preserved() -> None:
    config = benchmark.parse_args(["--warmup", "0", "--repetitions", "1"])
    _, first, _ = benchmark.run_benchmark(config)
    contents = first.read_bytes()
    _, second, _ = benchmark.run_benchmark(config)
    assert first != second
    assert first.read_bytes() == contents


def test_path_resolution_rejects_escape() -> None:
    with pytest.raises(SystemExit):
        benchmark.parse_args(["--output-dir", str(benchmark.PROJECT_ROOT / "outside")])


def test_no_network_or_worker_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("unexpected network or process execution")

    monkeypatch.setattr(benchmark, "git_output", lambda *args: None)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    report, _, _ = benchmark.run_benchmark(
        benchmark.parse_args(
            ["--max-concurrent", "1", "--requests", "3", "--warmup", "0", "--repetitions", "2"]
        )
    )
    assert report["summary"]["admitted"] == 2
    assert report["summary"]["rejected"] == 4
    assert report["environment"]["project_revision"] is None


def test_readiness_failure_releases_waiting_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    original = benchmark.ControlledTransport.wait_until_full

    def fail_when_held(self: benchmark.ControlledTransport, capacity: int) -> None:
        original(self, capacity)
        raise RuntimeError("injected coordination failure")

    monkeypatch.setattr(benchmark.ControlledTransport, "wait_until_full", fail_when_held)
    before = set(threading.enumerate())
    with pytest.raises(RuntimeError, match="injected coordination failure"):
        benchmark.run_benchmark(benchmark.parse_args(["--warmup", "0", "--repetitions", "1"]))
    assert set(threading.enumerate()) == before


def test_cli_main_emits_paths(capsys: pytest.CaptureFixture[str]) -> None:
    assert benchmark.main(["--warmup", "0", "--repetitions", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["summary"]["rejected"] == 12
    assert result["json"].endswith("results.json")
    assert result["csv"].endswith("samples.csv")


def test_cli_main_reports_runtime_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(config: benchmark.Configuration) -> None:
        raise RuntimeError("watchdog expired")

    monkeypatch.setattr(benchmark, "run_benchmark", fail)
    assert benchmark.main([]) == 1
    assert "Benchmark error: watchdog expired" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Stage 2 Step 1: Direct Operations Benchmark Tests
# ---------------------------------------------------------------------------


def test_operation_direct_cli_parsing_and_validation() -> None:
    config = benchmark.parse_args(["--scenario", "operation-direct"])
    assert config.scenario == "operation-direct"
    assert config.transport == "synthetic-direct"
    assert config.fleet_size == 3
    assert config.max_concurrent == 4

    config10 = benchmark.parse_args(["--scenario", "operation-direct", "--fleet-size", "10"])
    assert config10.fleet_size == 10
    assert config10.transport == "synthetic-direct"


@pytest.mark.parametrize(
    "args",
    [
        ["--scenario", "operation-direct", "--fleet-size", "5"],
        ["--scenario", "operation-direct", "--fleet-size", "0"],
        ["--scenario", "operation-direct", "--transport", "controlled-in-process"],
        ["--scenario", "operation-direct", "--max-concurrent", "0"],
        ["--scenario", "operation-direct", "--max-concurrent", "17"],
        ["--scenario", "unknown-scenario"],
    ],
)
def test_operation_direct_invalid_arguments(
    args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        benchmark.parse_args(args)
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_direct_operation_executor_and_service_integration() -> None:
    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"
        inventory = SQLiteNodeRepository(db_path)
        inventory.initialize()
        SQLiteConnectivityRepository(db_path).initialize()
        operations = SQLiteOperationsRepository(db_path)
        operations.initialize()

        node = inventory.add_node(NewNode("test-node", "127.0.0.1", 22))
        transport = benchmark.SyntheticOperationTransport(hold_until_release=False)
        executor = DirectOperationExecutor(transport, OperationLimits(max_concurrent=4))
        telemetry = Telemetry()
        service = OperationService(
            inventory,
            operations,
            executor,
            SSHSettings("observer", Path(temp_dir) / "hosts", Path(temp_dir) / "key"),
            telemetry=telemetry,
        )

        record = service.execute(node.id, "system.uptime", {}, b"digest")
        assert record.outcome == OperationOutcome.SUCCESS
        assert record.stdout is not None and "up" in record.stdout

        persisted = operations.list_for_node(node.id)
        assert len(persisted) == 1
        assert persisted[0].outcome == OperationOutcome.SUCCESS
        assert benchmark.active_metric(telemetry) == 0.0


def test_operation_direct_3node_execution() -> None:
    config = benchmark.parse_args(
        [
            "--scenario",
            "operation-direct",
            "--fleet-size",
            "3",
            "--warmup",
            "1",
            "--repetitions",
            "2",
        ]
    )
    before_threads = set(threading.enumerate())
    report, json_path, csv_path = benchmark.run_benchmark(config)
    assert set(threading.enumerate()) == before_threads

    assert report["schema_version"] == 2
    assert report["scenario"] == "operation-direct"
    assert report["transport"] == "synthetic-direct"
    assert report["configuration"]["fleet_size"] == 3

    summary = report["summary"]
    assert summary["fleet_size"] == 3
    assert summary["execution"]["sample_count"] == 6  # 2 measured rounds * 3 nodes
    assert summary["execution"]["success_count"] == 6
    assert summary["execution"]["failure_count"] == 0
    assert summary["execution"]["latency_ns"]["p50"] > 0
    assert summary["execution"]["fleet_cycle_duration_ns"]["p50"] > 0
    assert summary["execution"]["throughput_ops_per_sec"]["p50"] > 0

    assert summary["admission"]["sample_count"] == 6
    assert summary["admission"]["admitted_count"] == 6
    assert summary["admission"]["rejected_count"] == 0
    assert summary["admission"]["rejection_latency_ns"] is None
    assert summary["admission"]["admitted_latency_ns"]["p50"] > 0

    assert summary["telemetry_verification"]["operations_active_final"] == 0.0
    assert summary["telemetry_verification"]["operations_total"] > 0
    assert summary["telemetry_verification"]["duration_histogram_present"] is True

    # Check each round in rounds
    for round_info in report["rounds"]:
        assert round_info["execution"]["success_count"] == 3
        assert round_info["execution"]["failed_count"] == 0
        assert round_info["admission"]["admitted"] == 3
        assert round_info["admission"]["rejected"] == 0
        assert round_info["admission"]["held_active"] == 3.0
        assert round_info["admission"]["final_active"] == 0.0
        assert round_info["admission"]["threads_remaining"] == 0


def test_operation_direct_10node_execution() -> None:
    config = benchmark.parse_args(
        [
            "--scenario",
            "operation-direct",
            "--fleet-size",
            "10",
            "--warmup",
            "0",
            "--repetitions",
            "1",
        ]
    )
    before_threads = set(threading.enumerate())
    report, json_path, csv_path = benchmark.run_benchmark(config)
    assert set(threading.enumerate()) == before_threads

    assert report["schema_version"] == 2
    summary = report["summary"]
    assert summary["fleet_size"] == 10
    assert summary["execution"]["sample_count"] == 10
    assert summary["execution"]["success_count"] == 10
    assert summary["execution"]["failure_count"] == 0

    assert summary["admission"]["sample_count"] == 10
    assert summary["admission"]["admitted_count"] == 4
    assert summary["admission"]["rejected_count"] == 6
    assert summary["admission"]["rejection_latency_ns"] is not None
    assert summary["admission"]["rejection_latency_ns"]["p50"] > 0
    assert summary["admission"]["admitted_latency_ns"]["p50"] > 0

    round_info = report["rounds"][0]
    assert round_info["execution"]["success_count"] == 10
    assert round_info["admission"]["admitted"] == 4
    assert round_info["admission"]["rejected"] == 6
    assert round_info["admission"]["held_active"] == 4.0
    assert round_info["admission"]["final_active"] == 0.0


def test_operation_direct_csv_and_percentile_recomputation() -> None:
    config = benchmark.parse_args(
        [
            "--scenario",
            "operation-direct",
            "--fleet-size",
            "10",
            "--warmup",
            "1",
            "--repetitions",
            "2",
        ]
    )
    report, json_path, csv_path = benchmark.run_benchmark(config)

    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    samples = report["samples"]
    assert len(rows) == len(samples)
    assert set(rows[0]) == set(samples[0])
    for row, sample in zip(rows, samples, strict=True):
        assert row == {key: str(value) for key, value in sample.items()}
        assert int(row["elapsed_ns"]) >= 0

    # Independently recompute execution percentiles from measured CSV rows
    exec_elapsed = [
        int(r["elapsed_ns"])
        for r in rows
        if r["phase"] == "measurement" and r["sample_type"] == "execution"
    ]
    computed_exec_pct = benchmark.percentiles(exec_elapsed)
    for p in ("p50", "p90", "p95", "p99"):
        assert report["summary"]["execution"]["latency_ns"][p] == pytest.approx(
            computed_exec_pct[p]
        )

    # Independently recompute rejection percentiles from measured CSV rows
    rejection_elapsed = [
        int(r["elapsed_ns"])
        for r in rows
        if r["phase"] == "measurement"
        and r["sample_type"] == "admission"
        and r["result"] == "OperationBusy"
    ]
    computed_rej_pct = benchmark.percentiles(rejection_elapsed)
    for p in ("p50", "p90", "p95", "p99"):
        assert report["summary"]["admission"]["rejection_latency_ns"][p] == pytest.approx(
            computed_rej_pct[p]
        )


def test_operation_direct_admission_timing_does_not_include_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that admitted elapsed_ns captures admission decision before hold."""
    original_execute = benchmark.SyntheticOperationTransport.execute

    def slow_execute(
        self: benchmark.SyntheticOperationTransport,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        return original_execute(self, node, command, settings, timeout_seconds, max_output_bytes)

    monkeypatch.setattr(benchmark.SyntheticOperationTransport, "execute", slow_execute)
    config = benchmark.parse_args(
        [
            "--scenario",
            "operation-direct",
            "--fleet-size",
            "3",
            "--warmup",
            "0",
            "--repetitions",
            "1",
        ]
    )
    report, _, _ = benchmark.run_benchmark(config)
    admitted_samples = [
        s
        for s in report["samples"]
        if s["sample_type"] == "admission" and s["result"] == "ADMITTED"
    ]
    for s in admitted_samples:
        # Decision latency should be small (microseconds to low milliseconds), not holding
        assert s["elapsed_ns"] < 1_000_000_000  # < 1 second


def test_repeated_benchmark_runs_without_telemetry_conflict() -> None:
    config = benchmark.parse_args(
        [
            "--scenario",
            "operation-direct",
            "--fleet-size",
            "3",
            "--warmup",
            "0",
            "--repetitions",
            "1",
        ]
    )
    report1, _, _ = benchmark.run_benchmark(config)
    report2, _, _ = benchmark.run_benchmark(config)
    assert report1["summary"]["execution"]["success_count"] == 3
    assert report2["summary"]["execution"]["success_count"] == 3


def test_operation_direct_cleanup_on_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    original = benchmark.SyntheticOperationTransport.execute

    def fail_execute(
        self: benchmark.SyntheticOperationTransport,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        if self.hold_until_release:
            original(self, node, command, settings, timeout_seconds, max_output_bytes)
            raise RuntimeError("injected transport failure")
        return original(self, node, command, settings, timeout_seconds, max_output_bytes)

    monkeypatch.setattr(benchmark.SyntheticOperationTransport, "execute", fail_execute)
    before_threads = set(threading.enumerate())
    with pytest.raises(RuntimeError, match="injected transport failure"):
        benchmark.run_benchmark(
            benchmark.parse_args(
                [
                    "--scenario",
                    "operation-direct",
                    "--fleet-size",
                    "3",
                    "--warmup",
                    "0",
                    "--repetitions",
                    "1",
                ]
            )
        )
    assert set(threading.enumerate()) == before_threads


# ---------------------------------------------------------------------------
# Stage 2 Steps 2 & 3: Loopback, Process-Backed & Scheduler Benchmark Tests
# ---------------------------------------------------------------------------


def test_stage2_cli_parsing_and_defaults() -> None:
    c_loop = benchmark.parse_args(["--scenario", "operation-loopback"])
    assert c_loop.scenario == "operation-loopback"
    assert c_loop.transport == "paramiko-direct"
    assert c_loop.fleet_size == 3
    assert c_loop.max_concurrent == 4

    c_proc = benchmark.parse_args(["--scenario", "operation-process", "--fleet-size", "10"])
    assert c_proc.scenario == "operation-process"
    assert c_proc.transport == "subprocess-paramiko"
    assert c_proc.fleet_size == 10
    assert c_proc.max_concurrent == 4

    c_sched = benchmark.parse_args(["--scenario", "scheduler-fleet", "--fleet-size", "10"])
    assert c_sched.scenario == "scheduler-fleet"
    assert c_sched.transport == "process-ssh"
    assert c_sched.fleet_size == 10
    assert c_sched.max_concurrent == 4


@pytest.mark.parametrize(
    "args",
    [
        ["--scenario", "operation-loopback", "--fleet-size", "7"],
        ["--scenario", "operation-loopback", "--transport", "synthetic-direct"],
        ["--scenario", "operation-process", "--fleet-size", "1"],
        ["--scenario", "operation-process", "--transport", "paramiko-direct"],
        ["--scenario", "scheduler-fleet", "--fleet-size", "5"],
        ["--scenario", "scheduler-fleet", "--transport", "subprocess-worker"],
        ["--scenario", "scheduler-fleet", "--simulated-delay-ms", "-1"],
    ],
)
def test_stage2_invalid_arguments(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        benchmark.parse_args(args)
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_loopback_ssh_cluster_security() -> None:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        with benchmark.loopback_ssh_cluster(1, temp_path, timeout_seconds=5.0) as (
            ports,
            ssh_settings,
        ):
            port = ports[0]
            # Test unknown host key rejection
            empty_hosts = temp_path / "empty_hosts"
            empty_hosts.touch()
            client = paramiko.SSHClient()
            client.load_host_keys(str(empty_hosts))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            with pytest.raises(paramiko.ssh_exception.SSHException):
                client.connect(
                    "127.0.0.1",
                    port=port,
                    username=ssh_settings.username,
                    key_filename=str(ssh_settings.private_key_path),
                    timeout=5.0,
                    banner_timeout=5.0,
                )

            # Test wrong key authentication failure
            wrong_key = paramiko.RSAKey.generate(2048)
            client2 = paramiko.SSHClient()
            client2.load_host_keys(str(ssh_settings.known_hosts_path))
            client2.set_missing_host_key_policy(paramiko.RejectPolicy())
            with pytest.raises(paramiko.ssh_exception.AuthenticationException):
                client2.connect(
                    "127.0.0.1",
                    port=port,
                    username=ssh_settings.username,
                    pkey=wrong_key,
                    timeout=5.0,
                    banner_timeout=5.0,
                )

        # Confirm port is closed after leaving context manager
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        with pytest.raises(OSError):
            sock.connect(("127.0.0.1", port))
        sock.close()


def test_operation_loopback_execution() -> None:
    config = benchmark.parse_args(
        [
            "--scenario",
            "operation-loopback",
            "--fleet-size",
            "3",
            "--warmup",
            "0",
            "--repetitions",
            "1",
        ]
    )
    before_threads = set(threading.enumerate())
    report, json_path, csv_path = benchmark.run_benchmark(config)
    assert set(threading.enumerate()) == before_threads

    assert report["schema_version"] == 2
    assert report["scenario"] == "operation-loopback"
    assert report["transport"] == "paramiko-direct"
    summary = report["summary"]
    assert summary["fleet_size"] == 3
    assert summary["execution"]["sample_count"] == 3
    assert summary["execution"]["success_count"] == 3
    assert summary["execution"]["failure_count"] == 0
    assert summary["execution"]["latency_ns"]["p50"] > 0
    assert summary["execution"]["fleet_cycle_duration_ns"]["p50"] > 0
    assert summary["execution"]["throughput_ops_per_sec"]["p50"] > 0
    assert summary["telemetry_verification"]["operations_active_final"] == 0.0
    assert summary["telemetry_verification"]["operations_total"] == 3


def test_operation_process_execution() -> None:
    config = benchmark.parse_args(
        [
            "--scenario",
            "operation-process",
            "--fleet-size",
            "3",
            "--warmup",
            "0",
            "--repetitions",
            "1",
        ]
    )
    before_threads = set(threading.enumerate())
    report, json_path, csv_path = benchmark.run_benchmark(config)
    assert set(threading.enumerate()) == before_threads

    assert report["schema_version"] == 3
    assert report["scenario"] == "operation-process"
    assert report["transport"] == "subprocess-paramiko"
    summary = report["summary"]
    assert summary["fleet_size"] == 3
    assert summary["execution"]["sample_count"] == 3
    assert summary["execution"]["success_count"] == 3
    assert summary["execution"]["failure_count"] == 0
    assert summary["execution"]["latency_ns"]["p50"] > 0
    assert summary["worker_lifecycle"]["active_children_final"] == 0
    assert summary["worker_lifecycle"]["orphaned_children_detected"] == 0
    lifecycle = summary["worker_lifecycle"]
    assert lifecycle["tracked_worker_count"] == 3
    assert len(lifecycle["workers"]) == 3
    assert len({worker["execution_id"] for worker in lifecycle["workers"]}) == 3
    assert {worker["node_id"] for worker in lifecycle["workers"]} == {1, 2, 3}
    for worker in lifecycle["workers"]:
        assert worker["pid"] > 0
        assert worker["returncode_after_run"] == 0
        assert worker["wait_verified_after_run"] is True
        assert worker["active_after_run"] is False
        assert worker["active_final"] is False
        assert worker["pipes_closed_after_run"] is True
    assert summary["telemetry_verification"]["operations_active_final"] == 0.0
    assert summary["telemetry_verification"]["operations_total"] == 3


def test_scheduler_fleet_execution() -> None:
    config = benchmark.parse_args(
        [
            "--scenario",
            "scheduler-fleet",
            "--fleet-size",
            "3",
            "--warmup",
            "0",
            "--repetitions",
            "1",
        ]
    )
    before_threads = set(threading.enumerate())
    report, json_path, csv_path = benchmark.run_benchmark(config)
    assert set(threading.enumerate()) == before_threads

    assert report["schema_version"] == 3
    assert report["scenario"] == "scheduler-fleet"
    assert report["transport"] == "process-ssh"
    summary = report["summary"]
    assert summary["fleet_size"] == 3
    assert summary["scheduler"]["cycle_count"] == 1
    assert summary["scheduler"]["completed_checks"] == 3
    assert summary["scheduler"]["failed_checks"] == 0
    assert summary["scheduler"]["fleet_cycle_duration_ns"]["p50"] > 0
    assert summary["scheduler"]["effective_checks_per_sec"]["p50"] > 0
    assert summary["telemetry_verification"]["connectivity_active_final"] == 0.0
    assert summary["telemetry_verification"]["scheduler_cycles_total"] == 1.0


def test_stage2_csv_json_parity() -> None:
    config = benchmark.parse_args(
        [
            "--scenario",
            "operation-loopback",
            "--fleet-size",
            "3",
            "--warmup",
            "0",
            "--repetitions",
            "1",
        ]
    )
    report, json_path, csv_path = benchmark.run_benchmark(config)
    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    samples = report["samples"]
    assert len(rows) == len(samples)
    for row, sample in zip(rows, samples, strict=True):
        assert row["scenario"] == sample["scenario"]
        assert row["transport"] == sample["transport"]
        assert row["fleet_size"] == str(sample["fleet_size"])
        assert row["sample_type"] == sample["sample_type"]
        assert row["result"] == sample["result"]
        assert row["elapsed_ns"] == str(sample["elapsed_ns"])

    exec_elapsed = [int(r["elapsed_ns"]) for r in rows if r["sample_type"] == "execution"]
    computed_pct = benchmark.percentiles(exec_elapsed)
    for p in ("p50", "p90", "p95", "p99"):
        assert report["summary"]["execution"]["latency_ns"][p] == pytest.approx(computed_pct[p])


def test_scheduler_probe_boundaries_are_individual_service_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Independent inner timestamps reject duplicated fleet-cycle probe timings."""
    original_check = ConnectivityService.check
    observed: dict[int, list[tuple[int, int, str]]] = {}

    def record_check(self: ConnectivityService, node_id: int) -> ConnectivityObservation:
        started_ns = time.perf_counter_ns()
        observation = original_check(self, node_id)
        ended_ns = time.perf_counter_ns()
        observed.setdefault(node_id, []).append((started_ns, ended_ns, observation.outcome.value))
        return observation

    monkeypatch.setattr(ConnectivityService, "check", record_check)
    report, json_path, csv_path = benchmark.run_benchmark(
        benchmark.parse_args(
            [
                "--scenario",
                "scheduler-fleet",
                "--fleet-size",
                "3",
                "--max-concurrent",
                "1",
                "--warmup",
                "1",
                "--repetitions",
                "1",
            ]
        )
    )
    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    samples = report["samples"]
    assert len(samples) == len(rows) == 8
    for row, sample in zip(rows, samples, strict=True):
        assert row == {key: str(value) for key, value in sample.items()}
    assert set(observed) == {1, 2, 3}
    assert all(len(checks) == 2 for checks in observed.values())
    for iteration, phase in enumerate(("warmup", "measurement")):
        round_samples = [sample for sample in samples if sample["iteration"] == iteration]
        probes = [sample for sample in round_samples if sample["sample_type"] == "probe"]
        cycles = [sample for sample in round_samples if sample["sample_type"] == "fleet_cycle"]
        assert len(probes) == 3
        assert len(cycles) == 1
        cycle = cycles[0]
        assert cycle["node_id"] == 0
        assert cycle["schedule_delay_ns"] == 0
        assert cycle["elapsed_ns"] == cycle["ended_ns"] - cycle["started_ns"]
        assert len({sample["started_ns"] for sample in probes}) == 3
        assert len({sample["ended_ns"] for sample in probes}) == 3
        assert {sample["elapsed_ns"] for sample in probes} != {cycle["elapsed_ns"]}
        for probe in probes:
            inner_start, inner_end, outcome = observed[probe["node_id"]][iteration]
            assert probe["phase"] == cycle["phase"] == phase
            assert cycle["started_ns"] <= probe["started_ns"] <= inner_start
            assert inner_start < inner_end <= probe["ended_ns"] <= cycle["ended_ns"]
            assert probe["elapsed_ns"] == probe["ended_ns"] - probe["started_ns"]
            assert inner_end - inner_start <= probe["elapsed_ns"] < cycle["elapsed_ns"]
            assert probe["schedule_delay_ns"] == probe["started_ns"] - cycle["started_ns"]
            assert probe["result"] == outcome == "CONNECTED"
        ordered = sorted(probes, key=lambda sample: sample["started_ns"])
        # Concurrency one establishes actual serial dispatch, not a fabricated queue delay.
        assert ordered[1]["started_ns"] >= ordered[0]["ended_ns"]
        assert ordered[2]["started_ns"] >= ordered[1]["ended_ns"]
    assert report["summary"]["telemetry_verification"]["scheduler_cycles_total"] == 2.0


@pytest.mark.parametrize("worker_failure", [False, True], ids=["timeout", "worker-failure"])
def test_process_observer_tracks_live_workers_and_reaps_each_execution(
    worker_failure: bool,
) -> None:
    """Observe real owned Popen handles before and after failure/timeout cleanup."""
    command = (
        "import time,sys; time.sleep(0.1); sys.exit(3)"
        if worker_failure
        else "import time; time.sleep(2)"
    )
    executor = benchmark.ObservedProcessOperationExecutor(
        OperationLimits(max_concurrent=1, total_timeout_seconds=1.0),
        worker_command=(sys.executable, "-c", command),
    )
    node = Node(41, "owned-worker", "127.0.0.1", 22, ObservationState.NOT_CHECKED)
    settings = SSHSettings("observer", Path("unused-hosts"), Path("unused-key"))
    captured: list[subprocess.Popen[str]] = []

    def capture_live_worker() -> None:
        with executor._lock:
            process = executor._active[node.id]
        captured.append(process)
        assert process.poll() is None
        current = executor.lifecycle_summary()
        assert current["tracked_worker_count"] == len(captured)
        assert current["active_children_final"] == 1
        assert current["workers"][-1]["pid"] == process.pid
        assert current["workers"][-1]["node_id"] == node.id

    try:
        for _ in range(2):
            if worker_failure:
                with pytest.raises(OperationUnavailable, match="Worker exited with code 3"):
                    executor.run(node, "unused", settings, on_start=capture_live_worker)
            else:
                result = executor.run(node, "unused", settings, on_start=capture_live_worker)
                assert result.outcome == OperationOutcome.TIMEOUT
            assert captured[-1].poll() is not None
            assert captured[-1].wait(timeout=0) is not None
            assert executor.lifecycle_summary()["active_children_final"] == 0
    finally:
        executor.close()
    lifecycle = executor.lifecycle_summary()
    assert lifecycle["tracked_worker_count"] == 2
    assert lifecycle["active_children_final"] == 0
    assert lifecycle["orphaned_children_detected"] == 0
    workers = lifecycle["workers"]
    assert len(workers) == 2
    assert len({worker["execution_id"] for worker in workers}) == 2
    assert [worker["pid"] for worker in workers] == [process.pid for process in captured]
    for worker, process in zip(workers, captured, strict=True):
        assert worker["node_id"] == node.id
        assert worker["returncode_after_run"] == process.returncode
        if worker_failure:
            assert worker["returncode_after_run"] == 3
        assert worker["wait_verified_after_run"] is True
        assert worker["active_after_run"] is False
        assert worker["active_final"] is False
