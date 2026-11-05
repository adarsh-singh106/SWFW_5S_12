#!/usr/bin/env python3
"""GCE Automated Acceptance Test Suite for Distributed Linux Fleet Manager.

Covers:
  Suite 1 (Non-Destructive Baseline):
    1. Application Authentication Boundary (401 on missing/invalid token, 200 on valid token)
    2. Managed Node SSH Reachability (Nodes A, B, C over port 22 as fleetbootstrap)
    3. Node Onboarding & Explicit Host-Key Trust Enrollment
    4. Availability Detection & Observation Freshness (derive_status contract)
    5. Controlled Remote Command Execution (system.uptime, system.memory, system.disk)
    6. Prometheus Scrape Pipeline Health (fleet-manager up=1, node_exporter up=1)
    7. Grafana Service & Datasource Health (/api/health and Prometheus datasource)

  Suite 2 (Explicitly Opted-In Fault-Injection & Recovery):
    8. Invalid SSH Credentials Classification (AUTH_FAILED)
    9. Host-Key Mismatch Rejection & Alerting (HOST_KEY_MISMATCH)
    10. Timeout & Unreachable Endpoint Handling (TIMEOUT / UNREACHABLE)
    11. Node Recovery Verification
    12. Partial Fleet Failure Resilience (healthy nodes unaffected by peer outage)
    13. Controller Restart & In-Flight Job Reconciliation (RUNNING -> UNCERTAIN)
    14. Offline SQLite Backup & Pre-Flight Restore Verification

Modes:
  --mock                   Local authentication and temporary DB checks; other checks SKIPPED.
  --allow-fault-injection  Compatibility flag only; fault scenarios are NOT IMPLEMENTED.

Live baseline requires manually onboarded nodes and adds observations/operation audit records.
Exit codes: 0 complete, 1 failure, 2 incomplete/manual gates. Never run with python -O.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from scripts.backup_restore import check_integrity, perform_backup, perform_restore  # noqa: E402

from fleet_manager.config import SSHSettings  # noqa: E402
from fleet_manager.main import create_app  # noqa: E402


@dataclass
class TestResult:
    name: str
    suite: str
    status: str  # "PASSED", "SKIPPED", "FAILED", "NOT_IMPLEMENTED"
    duration_ms: float
    details: str = ""


# Default GCE Topology Definitions
GCE_NODES = [
    {"name": "fleet-node-a", "address": "10.160.0.5", "ssh_port": 22},
    {"name": "fleet-node-b", "address": "10.160.0.3", "ssh_port": 22},
    {"name": "fleet-node-c", "address": "10.160.0.4", "ssh_port": 22},
]

# Expected Prometheus targets in live GCE topology
EXPECTED_PROMETHEUS_TARGETS = {
    "fleet-manager": "127.0.0.1:8000",
    "node_exporter:fleet-node-a": "10.160.0.5:9100",
    "node_exporter:fleet-node-b": "10.160.0.3:9100",
    "node_exporter:fleet-node-c": "10.160.0.4:9100",
}


class AcceptanceRunner:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        grafana_url: str = "http://127.0.0.1:3000",
        prometheus_url: str = "http://127.0.0.1:9090",
        token: str | None = None,
        mock: bool = False,
        allow_fault_injection: bool = False,
        verbose: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.grafana_url = grafana_url.rstrip("/")
        self.prometheus_url = prometheus_url.rstrip("/")
        self.mock = mock
        self.allow_fault_injection = allow_fault_injection
        self.verbose = verbose
        self.results: list[TestResult] = []
        self.tmp_dir: Path | None = None

        if self.mock:
            self.token: str = token or secrets.token_urlsafe(32)
            self._setup_mock_environment()
        else:
            self.token = token or os.getenv("FLEET_MANAGER_API_TOKEN") or ""
            if not self.token:
                raise ValueError(
                    "FLEET_MANAGER_API_TOKEN environment variable or --token required "
                    "for live execution."
                )
            self.client: httpx.Client | TestClient = httpx.Client(
                base_url=self.base_url, timeout=75.0
            )

    def _setup_mock_environment(self) -> None:
        """Create mock application with isolated temporary database."""
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="fm_gce_accept_"))
        db_path = self.tmp_dir / "inventory.db"
        known_hosts = self.tmp_dir / "known_hosts"
        known_hosts.write_text("")
        priv_key = self.tmp_dir / "id_ed25519"
        priv_key.write_text("DUMMY_KEY")
        if os.name == "posix":
            priv_key.chmod(0o600)
            known_hosts.chmod(0o600)

        ssh_settings = SSHSettings("fleetbootstrap", known_hosts, priv_key)
        app = create_app(
            database_path=db_path,
            api_token=self.token,
            ssh_settings=ssh_settings,
            enable_scheduler=False,
        )
        self.test_app = app
        test_client = TestClient(app)
        test_client.__enter__()
        self.client = test_client

    def cleanup(self) -> None:
        if self.mock and isinstance(self.client, TestClient):
            try:
                self.client.__exit__(None, None, None)
            except Exception:
                pass
        if not self.mock:
            self.client.close()
        if self.tmp_dir and self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def record(
        self, name: str, suite: str, status: str, duration_ms: float, details: str = ""
    ) -> None:
        self.results.append(
            TestResult(
                name=name,
                suite=suite,
                status=status,
                duration_ms=duration_ms,
                details=details,
            )
        )
        symbol_map = {
            "PASSED": "[OK]",
            "SKIPPED": "[SKIP]",
            "FAILED": "[FAIL]",
            "NOT_IMPLEMENTED": "[N/I]",
        }
        symbol = symbol_map.get(status, "[???]")
        print(f"  {symbol} {name} ({duration_ms:.1f}ms){' - ' + details if details else ''}")

    # =========================================================================
    # Suite 1: Non-Destructive Baseline Tests
    # =========================================================================

    def test_01_authentication_boundary(self) -> None:
        """Verify API authentication rejects unauthenticated and invalid requests."""
        start = time.monotonic()
        # 1. Unauthenticated request must return 401
        res = self.client.get("/api/nodes")
        assert res.status_code == 401, f"Expected 401 without auth, got {res.status_code}"

        # 2. Invalid token must return 401
        res = self.client.get("/api/nodes", headers={"Authorization": "Bearer invalid_token_123"})
        assert res.status_code == 401, f"Expected 401 with invalid token, got {res.status_code}"

        # 3. Valid operator token must return 200
        res = self.client.get("/api/nodes", headers=self._auth_headers())
        assert res.status_code == 200, f"Expected 200 with valid token, got {res.status_code}"

        elapsed = (time.monotonic() - start) * 1000
        self.record("API Authentication Barrier", "Baseline", "PASSED", elapsed)

    def _skip(self, name: str, reason: str) -> None:
        self.record(name, "Acceptance", "SKIPPED", 0.0, reason)

    def _nodes(self) -> list[dict]:
        response = self.client.get("/api/nodes", headers=self._auth_headers())
        assert response.status_code == 200, "Inventory request failed"
        nodes = response.json()["nodes"]
        selected = []
        for expected in GCE_NODES:
            matches = [n for n in nodes if all(n[k] == v for k, v in expected.items())]
            assert len(matches) == 1, f"Expected registered endpoint: {expected['name']}"
            selected.append(matches[0])
        return selected

    def test_02_ssh_connectivity_baseline(self) -> None:
        """Probe from the controller via its API, never from the runner's network."""
        name = "Controller-origin SSH Connectivity"
        if self.mock:
            self._skip(name, "No real SSH transport in offline mode")
            return
        for node in self._nodes():
            response = self.client.post(
                f"/api/nodes/{node['id']}/connectivity-check", headers=self._auth_headers()
            )
            assert response.status_code == 200, (
                "Controller probe rejected; inspect setup/busy state"
            )
            assert response.json()["outcome"] == "CONNECTED", "Controller SSH probe did not connect"
        self.record(name, "Baseline", "PASSED", 0.0, "Controller verified SSH to all 3 endpoints")

    def test_03_node_onboarding_and_trust(self) -> None:
        """Trust provenance requires independent operator verification; never auto-enroll."""
        self._skip(
            "Node Inventory Onboarding & Trust",
            "MANUAL APPROVAL GATE: register all 3 nodes; independently verify each fingerprint "
            "via authenticated GCE console/IAP access before explicit enrollment. "
            "A stored TRUSTED flag alone is not evidence of out-of-band verification. "
            "See runbook 15.",
        )

    def test_04_availability_detection(self) -> None:
        name = "Availability & Freshness Derivation"
        if self.mock:
            self._skip(name, "No live observations in offline mode")
            return
        nodes = self._nodes()
        response = self.client.get("/api/nodes/status", headers=self._auth_headers())
        assert response.status_code == 200, "Status request failed"
        data = response.json()
        for node in nodes:
            status = next(s for s in data["nodes"] if s["node"]["id"] == node["id"])
            assert status["display_status"] == "REACHABLE"
            observation = status["observation"]
            assert observation["outcome"] == "CONNECTED"
            observed = datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00"))
            age = (datetime.now(UTC) - observed).total_seconds()
            assert 0 <= age <= data["observation_ttl_seconds"], "Observation is stale/future"
        self.record(name, "Baseline", "PASSED", 0.0, "3 fresh CONNECTED observations")

    def test_05_remote_operations(self) -> None:
        name = "Controlled Remote Operations"
        if self.mock:
            self._skip(name, "No remote commands executed in offline mode")
            return
        headers = self._auth_headers()
        actions = {"system.uptime": {}, "system.memory": {}, "system.disk": {"path": "/"}}
        for node in self._nodes():
            for action, arguments in actions.items():
                response = self.client.post(
                    f"/api/nodes/{node['id']}/operations",
                    json={"action": action, "arguments": arguments},
                    headers=headers,
                )
                assert response.status_code == 200, f"{action}: request rejected; no retry"
                body = response.json()
                assert body["outcome"] == "SUCCESS", f"{action}: not SUCCESS"
                assert body["exit_code"] == 0 and body["failure_category"] is None
                assert body["output_truncated"] is False
                assert body["node_id"] == node["id"] and body["action"] == action
                assert body["arguments"] == arguments
                assert body["requested_at"] and body["started_at"] and body["completed_at"]
                assert body["audit_metadata"]["operator_type"] == "bearer_token"
                output = body["stdout"] or ""
                if action == "system.uptime":
                    assert re.search(r"up\s+.+load average[s]?:\s*\d", output), (
                        "Invalid uptime output"
                    )
                elif action == "system.memory":
                    assert re.search(r"(?m)^Mem:\s+\d+\s+\d+\s+\d+", output), (
                        "Invalid free -m output"
                    )
                else:
                    assert "Filesystem" in output and re.search(
                        r"(?m)^\S+\s+.+\s+\d+%\s+/\s*$", output
                    ), "Invalid df output"
                history = self.client.get(f"/api/nodes/{node['id']}/operations", headers=headers)
                assert history.status_code == 200
                stored = next(
                    (r for r in history.json()["operations"] if r["id"] == body["id"]), None
                )
                assert stored == body, "Audit history missing or differs from execution result"
        self.record(
            name,
            "Baseline",
            "PASSED",
            0.0,
            "9 successful operations with output and audit evidence",
        )

    @staticmethod
    def _verify_up(data: dict) -> None:
        assert data["status"] == "success" and data["data"]["resultType"] == "vector"
        results = data["data"]["result"]
        expected = [("fleet-manager", "127.0.0.1:8000")]
        expected += [("node_exporter", f"{node['address']}:9100") for node in GCE_NODES]
        for job, instance in expected:
            matches = [
                r
                for r in results
                if r["metric"].get("job") == job and r["metric"].get("instance") == instance
            ]
            assert len(matches) == 1, f"Missing/duplicate target: {job}/{instance}"
            assert float(matches[0]["value"][1]) == 1, f"Target down: {job}/{instance}"

    def test_06_prometheus_scrape_status(self) -> None:
        name = "Prometheus Scrape Pipeline Health"
        if self.mock:
            self._skip(name, "No Prometheus queried in offline mode")
            return
        response = httpx.get(
            f"{self.prometheus_url}/api/v1/query", params={"query": "up"}, timeout=10
        )
        assert response.status_code == 200, "Prometheus query failed"
        self._verify_up(response.json())
        self.record(
            name, "Baseline", "PASSED", 0.0, "Expected controller and 3 node_exporter targets up=1"
        )

    def test_07_grafana_health(self) -> None:
        name = "Grafana Service, Datasource & Dashboard"
        if self.mock:
            self._skip(name, "No Grafana queried in offline mode")
            return
        user, password = os.getenv("GRAFANA_USER"), os.getenv("GRAFANA_PASSWORD")
        if not user or not password:
            self._skip(name, "Set GRAFANA_USER and GRAFANA_PASSWORD for authenticated verification")
            return
        with httpx.Client(base_url=self.grafana_url, auth=(user, password), timeout=10) as client:
            health = client.get("/api/health")
            assert health.status_code == 200 and health.json()["database"] == "ok"
            datasource = client.get("/api/datasources/uid/prometheus")
            assert datasource.status_code == 200, "Provisioned datasource missing"
            ds = datasource.json()
            assert ds["type"] == "prometheus" and ds["url"] == "http://127.0.0.1:9090"
            assert ds["access"] == "proxy" and ds["isDefault"] is True
            query = client.get(
                "/api/datasources/proxy/uid/prometheus/api/v1/query", params={"query": "up"}
            )
            assert query.status_code == 200, "Grafana datasource query failed"
            self._verify_up(query.json())
            dashboard = client.get("/api/dashboards/uid/fleet-manager-overview")
            assert dashboard.status_code == 200, "Provisioned dashboard missing"
            payload = dashboard.json()
            assert payload["meta"]["provisioned"] is True
            actual = payload["dashboard"]
            expected = json.loads(
                (ROOT / "monitoring/grafana/dashboards/fleet-monitoring.json").read_text()
            )
            assert actual["uid"] == expected["uid"] and actual["title"] == expected["title"]
            for panel in expected["panels"]:
                live = next(p for p in actual["panels"] if p["id"] == panel["id"])
                for field in ("title", "type", "datasource", "targets"):
                    assert live.get(field) == panel.get(field), (
                        f"Dashboard panel differs: {panel['id']}/{field}"
                    )
        self.record(
            name,
            "Baseline",
            "PASSED",
            0.0,
            "Provisioning and datasource query verified; visual rendering remains manual",
        )

    def _not_implemented(self, name: str) -> None:
        self._skip(
            name, "NOT IMPLEMENTED: no live scenario executed, even with --allow-fault-injection"
        )

    def test_08_invalid_ssh_credentials(self) -> None:
        self._not_implemented("Invalid SSH Credentials Classification")

    def test_09_host_key_mismatch_rejection(self) -> None:
        self._not_implemented("Host-Key Mismatch Rejection")

    def test_10_timeout_unreachable_node(self) -> None:
        self._not_implemented("Timeout & Unreachable Node Handling")

    def test_11_node_recovery(self) -> None:
        self._not_implemented("Transient Outage Node Recovery")

    def test_12_partial_fleet_failure(self) -> None:
        self._not_implemented("Partial Fleet Failure Resilience")

    def test_13_controller_restart_crash_recovery(self) -> None:
        self._not_implemented("Controller Crash Reconciliation")

    def test_14_backup_restore_verification(self) -> None:
        """Disaster Recovery: Online SQLite backup, integrity check, and offline restore."""
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="fm_backup_accept_") as tmp:
            t_path = Path(tmp)
            src_db = t_path / "inventory.db"
            backup_db = t_path / "inventory_latest.db"
            restored_db = t_path / "inventory_restored.db"

            from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
            from fleet_manager.inventory.repository import SQLiteNodeRepository
            from fleet_manager.operations.repository import SQLiteOperationsRepository

            node_repo = SQLiteNodeRepository(src_db)
            node_repo.initialize()
            conn_repo = SQLiteConnectivityRepository(src_db)
            conn_repo.initialize()
            ops_repo = SQLiteOperationsRepository(src_db)
            ops_repo.initialize()

            # 1. Perform online backup
            perform_backup(src_db, backup_db)
            assert backup_db.exists()
            assert backup_db.with_suffix(".db.manifest.json").exists()

            # 2. Check backup integrity
            ok, msg, ver = check_integrity(backup_db)
            assert ok and ver in (3, 4, 5), f"Integrity check failed: {msg} (version {ver})"

            # 3. Perform offline restore
            perform_restore(backup_db, restored_db)
            assert restored_db.exists()
            ok_res, msg_res, ver_res = check_integrity(restored_db)
            assert ok_res and ver_res in (3, 4, 5)

        elapsed = (time.monotonic() - start) * 1000
        self.record(
            "Disaster Recovery: Backup & Restore Pre-Flight",
            "Fault-Injection",
            "PASSED",
            elapsed,
            details="LOCAL temporary empty DB only; not deployed backup/recovery evidence",
        )

    def run_all(self) -> int:
        print("=" * 75)
        print("    SWFW_5S_12: GCE Automated Acceptance Test Suite")
        fault_mode = "NOT IMPLEMENTED (flag cannot enable scenarios)"
        print(f"    Mode: {'MOCK (Isolated)' if self.mock else 'LIVE GCE CLOUD'}")
        print(f"    Fault-Injection: {fault_mode}")
        print("=" * 75)

        try:
            for method in sorted(name for name in dir(self) if re.match(r"test_\d{2}_", name)):
                started = time.monotonic()
                try:
                    getattr(self, method)()
                except Exception as exc:
                    # Never echo remote response bodies or credentials into reports.
                    self.record(
                        method,
                        "Acceptance",
                        "FAILED",
                        (time.monotonic() - started) * 1000,
                        f"Verification failed ({type(exc).__name__}); inspect this check locally",
                    )
        finally:
            self.cleanup()

        print("\n" + "=" * 75)
        print("                         ACCEPTANCE TEST SUMMARY")
        print("=" * 75)
        passed = sum(1 for r in self.results if r.status == "PASSED")
        skipped = sum(1 for r in self.results if r.status == "SKIPPED")
        failed = sum(1 for r in self.results if r.status == "FAILED")
        not_impl = sum(1 for r in self.results if r.status == "NOT_IMPLEMENTED")

        print(
            f"Total Tests: {len(self.results)} | Passed: {passed} | "
            f"Skipped: {skipped} | Failed: {failed} | Not Implemented: {not_impl}"
        )
        if not_impl > 0:
            print(
                f"\nNOTE: {not_impl} test(s) are NOT IMPLEMENTED in automated form. "
                "Follow the manual procedures in DEPLOYMENT-RUNBOOK.md Section 15."
            )
        print("=" * 75)

        print(
            "Incomplete/manual gates are not acceptance success. "
            "Offline results are not GCE evidence."
        )
        return 1 if failed else (2 if skipped or not_impl else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="GCE Acceptance Test Suite for Fleet Manager")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Fleet Manager host (default: 127.0.0.1)"
    )
    parser.add_argument("--port", type=int, default=8000, help="Fleet Manager port (default: 8000)")
    parser.add_argument(
        "--grafana-port", type=int, default=3000, help="Grafana port (default: 3000)"
    )
    parser.add_argument(
        "--prometheus-port", type=int, default=9090, help="Prometheus port (default: 9090)"
    )
    parser.add_argument(
        "--token", default=None, help="Operator bearer token (or env FLEET_MANAGER_API_TOKEN)"
    )
    parser.add_argument(
        "--mock", action="store_true", help="Run in mock mode without live network or VMs"
    )
    parser.add_argument(
        "--allow-fault-injection",
        "--fault-injection",
        dest="allow_fault_injection",
        action="store_true",
        help="Reserved compatibility flag; scenarios 08-13 remain NOT IMPLEMENTED/SKIPPED",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose diagnostics")

    args = parser.parse_args()
    if not __debug__:
        parser.error("Assertions are required; do not run with -O or PYTHONOPTIMIZE")

    try:
        runner = AcceptanceRunner(
            base_url=f"http://{args.host}:{args.port}",
            grafana_url=f"http://{args.host}:{args.grafana_port}",
            prometheus_url=f"http://{args.host}:{args.prometheus_port}",
            token=args.token,
            mock=args.mock,
            allow_fault_injection=args.allow_fault_injection,
            verbose=args.verbose,
        )
        return runner.run_all()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
