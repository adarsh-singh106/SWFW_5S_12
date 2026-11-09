"""Unit tests for GCE Acceptance Test Suite safety, flags, and mock execution."""

from __future__ import annotations

import json

import httpx
import pytest
from scripts.gce_acceptance_test import GCE_NODES, ROOT, AcceptanceRunner, main


@pytest.mark.parametrize("opt_in", [False, True])
def test_acceptance_runner_mock_execution(monkeypatch, opt_in) -> None:
    """Only executed local checks pass; missing live evidence stays incomplete."""

    def deny_network(*args, **kwargs):
        pytest.fail("Offline acceptance must not open a network connection")

    # Block external HTTP and real SSH, not Windows asyncio's internal socketpair.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny_network)
    monkeypatch.setattr("paramiko.SSHClient.connect", deny_network)
    runner = AcceptanceRunner(mock=True, allow_fault_injection=opt_in)
    exit_code = runner.run_all()
    assert exit_code == 2
    assert all(r.status == "SKIPPED" for r in runner.results[1:7])
    assert len(runner.results) == 14

    # Simulated contracts must never masquerade as completed live acceptance.
    for result in runner.results:
        assert result.status in ("PASSED", "SKIPPED", "SIMULATED"), (
            f"Test '{result.name}' has unexpected status '{result.status}' in mock mode"
        )

    # Suite 2 tests 08-13 execute only explicitly labelled deterministic simulations.
    suite2_names = [
        "Invalid SSH Credentials Classification",
        "Host-Key Mismatch Rejection",
        "Timeout & Unreachable Node Handling",
        "Transient Outage Node Recovery",
        "Partial Fleet Failure Resilience",
        "Controller Crash Reconciliation",
    ]
    for name in suite2_names:
        matching = [r for r in runner.results if r.name == name]
        assert len(matching) == 1, f"Expected exactly 1 result for '{name}'"
        assert matching[0].status == "SIMULATED"
        assert "SIMULATED ONLY; LIVE GATE UNMET" in matching[0].details

    # Backup/restore (test 14) should still PASS (real SQLite operations)
    backup_results = [r for r in runner.results if "Backup" in r.name]
    assert len(backup_results) == 1
    assert backup_results[0].status == "PASSED"
    assert runner.tmp_dir is not None and not runner.tmp_dir.exists()


def test_acceptance_runner_requires_token_for_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """AcceptanceRunner refuses live cloud execution without an explicit token."""
    monkeypatch.delenv("FLEET_MANAGER_API_TOKEN", raising=False)
    with pytest.raises(
        ValueError,
        match="FLEET_MANAGER_API_TOKEN environment variable or --token required",
    ):
        AcceptanceRunner(mock=False, token=None)


def test_acceptance_fault_injection_skipped_without_opt_in() -> None:
    """Failure-injection tests are strictly skipped when --allow-fault-injection is omitted."""
    runner = AcceptanceRunner(mock=True, allow_fault_injection=False)
    # Explicitly test that non-destructive tests pass and opted-in methods can skip
    assert runner.allow_fault_injection is False
    runner.cleanup()


def test_main_cli_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() CLI entrypoint succeeds in --mock mode."""
    monkeypatch.setattr("sys.argv", ["gce_acceptance_test.py", "--mock"])
    ret = main()
    assert ret == 2


def test_main_cli_missing_token_returns_code_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() CLI entrypoint exits with code 1 when token is missing for live run."""
    monkeypatch.delenv("FLEET_MANAGER_API_TOKEN", raising=False)
    monkeypatch.setattr("sys.argv", ["gce_acceptance_test.py"])
    ret = main()
    assert ret == 1


@pytest.fixture
def live_runner():
    runner = AcceptanceRunner(token="local-test")
    yield runner
    runner.cleanup()


def up_payload():
    targets = [("fleet-manager", "127.0.0.1:8000")]
    targets += [("node_exporter", f"{n['address']}:9100") for n in GCE_NODES]
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"job": job, "instance": instance}, "value": [1, "1"]}
                for job, instance in targets
            ],
        },
    }


@pytest.mark.parametrize(
    "problem", ["empty", "missing", "down", "wrong_instance", "error", "duplicate"]
)
def test_prometheus_rejects_false_success(live_runner, monkeypatch, problem):
    data = up_payload()
    results = data["data"]["result"]
    if problem == "empty":
        results.clear()
    elif problem == "missing":
        results.pop()
    elif problem == "down":
        results[-1]["value"][1] = "0"
    elif problem == "wrong_instance":
        results[-1]["metric"]["instance"] = "wrong:9100"
    elif problem == "error":
        data["status"] = "error"
    else:
        results.append(results[-1].copy())
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json=data))
    with pytest.raises(AssertionError):
        live_runner.test_06_prometheus_scrape_status()


def test_prometheus_expected_four_targets_pass(live_runner, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json=up_payload()))
    live_runner.test_06_prometheus_scrape_status()
    assert live_runner.results[-1].status == "PASSED"


@pytest.mark.parametrize(
    "problem",
    [None, "FAILURE", "UNCERTAIN", "busy", "empty_output", "missing_audit", "wrong_audit"],
)
def test_operations_require_success_output_and_matching_audit(live_runner, problem):
    records = []
    outputs = {
        "system.uptime": "12:00 up 2 days, 1 user, load average: 0.01, 0.02, 0.03",
        "system.memory": "total used free\nMem: 1000 200 800\nSwap: 0 0 0",
        "system.disk": "Filesystem Size Used Avail Use% Mounted on\n/dev/sda 10G 2G 8G 20% /\n",
    }

    def handle(request):
        if request.url.path == "/api/nodes":
            return httpx.Response(
                200, json={"nodes": [dict(n, id=i + 17) for i, n in enumerate(GCE_NODES)]}
            )
        if request.method == "POST":
            if problem == "busy":
                return httpx.Response(409)
            payload = json.loads(request.content)
            if payload["action"] == "system.disk":
                assert payload["arguments"] == {"path": "/"}
            record = dict(
                payload,
                id=str(len(records)),
                node_id=int(request.url.path.split("/")[3]),
                outcome=problem if problem in ("FAILURE", "UNCERTAIN") else "SUCCESS",
                exit_code=0,
                failure_category=None,
                output_truncated=False,
                stdout="" if problem == "empty_output" else outputs[payload["action"]],
                stderr="",
                requested_at="now",
                started_at="now",
                completed_at="now",
                audit_metadata={"operator_type": "bearer_token"},
            )
            records.append(record)
            return httpx.Response(200, json=record)
        history = [] if problem == "missing_audit" else [dict(r) for r in records]
        if problem == "wrong_audit":
            history[-1]["stdout"] = "altered"
        return httpx.Response(200, json={"operations": history})

    live_runner.client.close()
    live_runner.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle))
    if problem:
        with pytest.raises(AssertionError):
            live_runner.test_05_remote_operations()
    else:
        live_runner.test_05_remote_operations()
        assert len(records) == 9
        assert live_runner.results[-1].status == "PASSED"


@pytest.mark.parametrize(
    "problem", [None, "datasource", "query", "dashboard", "not_provisioned", "panel"]
)
def test_grafana_checks_real_contract(live_runner, monkeypatch, problem):
    monkeypatch.setenv("GRAFANA_USER", "test")
    monkeypatch.setenv("GRAFANA_PASSWORD", "test")
    dashboard = json.loads(
        (ROOT / "monitoring/grafana/dashboards/fleet-monitoring.json").read_text()
    )
    if problem == "panel":
        dashboard["panels"] = []

    def handle(request):
        path = request.url.path
        if path == "/api/health":
            return httpx.Response(200, json={"database": "ok"})
        if path == "/api/datasources/uid/prometheus":
            return httpx.Response(
                200,
                json={
                    "type": "prometheus",
                    "url": "wrong" if problem == "datasource" else "http://127.0.0.1:9090",
                    "access": "proxy",
                    "isDefault": True,
                },
            )
        if "/proxy/" in path:
            return httpx.Response(503 if problem == "query" else 200, json=up_payload())
        return httpx.Response(
            404 if problem == "dashboard" else 200,
            json={"meta": {"provisioned": problem != "not_provisioned"}, "dashboard": dashboard},
        )

    client_type = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client_type(**kw, transport=httpx.MockTransport(handle))
    )
    if problem:
        with pytest.raises((AssertionError, StopIteration)):
            live_runner.test_07_grafana_health()
    else:
        live_runner.test_07_grafana_health()
        assert live_runner.results[-1].status == "PASSED"


def test_network_check_runs_on_controller_with_actual_ids(live_runner):
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(
                200, json={"nodes": [dict(n, id=i + 31) for i, n in enumerate(GCE_NODES)]}
            )
        return httpx.Response(200, json={"outcome": "CONNECTED"})

    live_runner.client.close()
    live_runner.client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle))
    live_runner.test_02_ssh_connectivity_baseline()
    assert seen[1:] == [("POST", f"/api/nodes/{i}/connectivity-check") for i in (31, 32, 33)]


@pytest.mark.parametrize("opt_in", [False, True])
def test_unimplemented_scenarios_never_pass(live_runner, opt_in):
    live_runner.allow_fault_injection = opt_in

    def deny_network(request):
        pytest.fail("Live fault gates must never inject faults or contact endpoints")

    live_runner.client.close()
    live_runner.client = httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(deny_network)
    )
    for method in (
        "test_08_invalid_ssh_credentials",
        "test_09_host_key_mismatch_rejection",
        "test_10_timeout_unreachable_node",
        "test_11_node_recovery",
        "test_12_partial_fleet_failure",
        "test_13_controller_restart_crash_recovery",
    ):
        getattr(live_runner, method)()
    assert all(
        r.status == "SKIPPED" and "NOT IMPLEMENTED" in r.details for r in live_runner.results
    )


@pytest.mark.parametrize("scenario", ["08", "09", "10", "11", "12", "13"])
def test_simulated_faults_are_independent_and_fail_closed(monkeypatch, scenario):
    from fleet_manager.connectivity.models import ConnectivityOutcome

    runner = AcceptanceRunner(mock=True)
    method = next(n for n in dir(runner) if n.startswith(f"test_{scenario}_"))
    try:
        getattr(runner, method)()
        assert runner.results[-1].status == "SIMULATED"
        assert "LIVE GATE UNMET" in runner.results[-1].details
        if scenario != "13":
            monkeypatch.setattr(
                runner.simulated_transport,
                "verify",
                lambda *args: ConnectivityOutcome.UNKNOWN_ERROR,
            )
            with pytest.raises(AssertionError):
                getattr(runner, method)()
            assert len(runner.results) == 1, "Failed assertions must not record simulation success"
    finally:
        runner.cleanup()


def test_simulated_failure_sets_failure_exit_and_cleans_up(monkeypatch):
    runner = AcceptanceRunner(mock=True)

    def fail():
        raise AssertionError("sensitive diagnostic")

    monkeypatch.setattr(runner, "test_13_controller_restart_crash_recovery", fail)
    assert runner.run_all() == 1
    assert len(runner.results) == 14
    failed = [r for r in runner.results if r.status == "FAILED"]
    assert len(failed) == 1
    assert "sensitive" not in failed[0].details
    assert not runner.tmp_dir.exists()


def test_onboarding_never_silently_enrolls(live_runner):
    def deny_network(request):
        pytest.fail("Manual trust gate must not scan or enroll keys")

    live_runner.client.close()
    live_runner.client = httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(deny_network)
    )
    live_runner.test_03_node_onboarding_and_trust()
    assert live_runner.results[-1].status == "SKIPPED"
    assert "fingerprint" in live_runner.results[-1].details
