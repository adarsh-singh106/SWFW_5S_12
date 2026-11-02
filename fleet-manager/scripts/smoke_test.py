#!/usr/bin/env python3
"""Release Smoke Test for Linux Fleet Manager Control Plane.

Verifies end-to-end integration:
  1. API Security & Auth Boundary: 401 on missing/invalid token, 200 on valid token.
  2. Inventory Operations: Node registration and listing (safe ephemeral or opt-in live).
  3. Status Derivation: Fleet status endpoint and DisplayStatus schema.
  4. Metrics Pipeline: Loopback /metrics exposition format and control plane metrics.
  5. UI Dashboard: HTML delivery and security headers (nosniff, DENY).
  6. Prometheus & Grafana Service Availability: Checks Prometheus target scrapes
     and Grafana service health when local monitoring services are running.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.freshness import DisplayStatus
from fleet_manager.main import create_app


def log_step(title: str) -> None:
    print(f"\n[*] {title}")


def run_smoke_test(
    base_url: str | None = None,
    allow_live_mutation: bool = False,
    isolated_test_env: bool = False,
) -> int:
    print("=" * 70)
    print("Fleet Manager Release Smoke Test")
    print("=" * 70)

    live_client: httpx.Client | None = None
    test_client: TestClient | None = None
    tmp_dir: Path | None = None

    # Determine execution target (live HTTP server or in-process TestClient)
    is_live = False
    target_url = base_url
    if target_url:
        is_live = True
    else:
        # Check if 127.0.0.1:8000 is listening
        try:
            probe = httpx.get("http://127.0.0.1:8000/metrics", timeout=0.5)
            if probe.status_code == 200:
                print("Detected running Fleet Manager server at http://127.0.0.1:8000")
                target_url = "http://127.0.0.1:8000"
                is_live = True
        except Exception:
            is_live = False

    # Security: Retrieve token strictly from environment when targeting a live server
    if is_live:
        token = os.getenv("FLEET_MANAGER_API_TOKEN")
        if not token or not token.strip():
            print(
                "Error: FLEET_MANAGER_API_TOKEN environment variable is required when "
                "verifying a live server.",
                file=sys.stderr,
            )
            return 1
        token = token.strip()
    else:
        token = os.getenv("FLEET_MANAGER_API_TOKEN") or secrets.token_urlsafe(32)

    headers = {"Authorization": f"Bearer {token}"}

    if is_live and target_url:
        print(f"Connecting to live server at: {target_url}")
        live_client = httpx.Client(base_url=target_url, timeout=5.0)
        client: httpx.Client | TestClient = live_client
    else:
        print("Spinning up ephemeral test instance with temporary database...")
        tmp_dir = Path(tempfile.mkdtemp(prefix="fm_smoke_"))
        db_path = tmp_dir / "smoke.db"
        known_hosts = tmp_dir / "known_hosts"
        known_hosts.write_text("")
        priv_key = tmp_dir / "key"
        priv_key.write_text("")
        if os.name == "posix":
            priv_key.chmod(0o600)
        ssh_settings = SSHSettings("fleet-observer", known_hosts, priv_key)
        app = create_app(
            database_path=db_path,
            api_token=token,
            ssh_settings=ssh_settings,
            enable_scheduler=False,
        )
        test_client = TestClient(app)
        test_client.__enter__()
        client = test_client

    try:
        # 1. Metrics Exposition
        log_step("1. Verifying Prometheus /metrics Endpoint...")
        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200, f"/metrics failed: {metrics_resp.status_code}"
        assert "fleet_connectivity_checks_total" in metrics_resp.text
        assert "fleet_nodes_by_status" in metrics_resp.text
        print("    [PASS] /metrics is accessible and exposes valid control-plane telemetry")

        # 2. Operations Dashboard Delivery & Security Headers
        log_step("2. Verifying Browser Operations Dashboard Delivery & Headers...")
        dash_resp = client.get("/dashboard")
        assert dash_resp.status_code == 200, f"/dashboard failed: {dash_resp.status_code}"
        assert dash_resp.headers.get("x-content-type-options") == "nosniff"
        assert dash_resp.headers.get("x-frame-options") == "DENY"
        assert "Fleet Operations Dashboard" in dash_resp.text
        print("    [PASS] /dashboard served 200 OK with strict nosniff & DENY security headers")

        # 3. Authentication Boundary Guardrails
        log_step("3. Verifying Bearer Authentication Security Guardrails...")
        unauth_resp = client.get("/api/nodes")
        assert unauth_resp.status_code == 401, f"Expected 401, got {unauth_resp.status_code}"
        assert unauth_resp.headers.get("www-authenticate") == "Bearer"

        bad_auth = client.get("/api/nodes", headers={"Authorization": "Bearer invalid-token"})
        assert bad_auth.status_code == 401
        print("    [PASS] Unauthenticated and invalid bearer requests strictly rejected (401)")

        # 4. Inventory Operations: Safe Read-Only vs Ephemeral vs Isolated Mutation
        if is_live:
            if not allow_live_mutation:
                log_step("4. Verifying Authenticated Inventory (Live Read-Only Guard Active)...")
                print(
                    "    [INFO] Live server detected; skipping node POST to protect "
                    "production inventory."
                )
                print("    [INFO] Verifying GET /api/nodes and GET /api/nodes/status read paths...")
                list_resp = client.get("/api/nodes", headers=headers)
                assert list_resp.status_code == 200, (
                    f"GET /api/nodes failed: {list_resp.status_code}"
                )
                status_resp = client.get("/api/nodes/status", headers=headers)
                assert status_resp.status_code == 200, (
                    f"GET /api/nodes/status failed: {status_resp.status_code}"
                )
                nodes = list_resp.json().get("nodes", [])
                print(
                    f"    [PASS] Authenticated inventory read endpoints verified without mutation "
                    f"({len(nodes)} node(s) present)"
                )
            else:
                if not isolated_test_env:
                    print(
                        "    [FAIL] Refusing persistent live mutation: "
                        "Fleet Manager has no safe deletion API.",
                        file=sys.stderr,
                    )
                    print(
                        "           Refusing to leave permanent smoke test nodes in inventory.",
                        file=sys.stderr,
                    )
                    print(
                        "           Must specify both --allow-live-mutation and "
                        "--isolated-test-env.",
                        file=sys.stderr,
                    )
                    return 1

                log_step(
                    "4. Verifying Authenticated Inventory Operations (Live Mutation Opt-In)..."
                )
                test_node_name = f"smoke-node-{secrets.token_hex(4)}"
                reg_resp = client.post(
                    "/api/nodes",
                    json={"name": test_node_name, "address": "127.0.0.1", "ssh_port": 2222},
                    headers=headers,
                )
                assert reg_resp.status_code == 201, f"Node registration failed: {reg_resp.text}"
                node_id = reg_resp.json()["id"]
                print(f"    [PASS] Registered test node '{test_node_name}' (ID {node_id})")

                list_resp = client.get("/api/nodes", headers=headers)
                assert list_resp.status_code == 200
                node_ids = [n["id"] for n in list_resp.json()["nodes"]]
                assert node_id in node_ids
                print(f"    [PASS] GET /api/nodes verified node {node_id} present in inventory")

                status_resp = client.get("/api/nodes/status", headers=headers)
                assert status_resp.status_code == 200
                status_data = status_resp.json()
                target_entry = next(n for n in status_data["nodes"] if n["node"]["id"] == node_id)
                assert target_entry["display_status"] == DisplayStatus.NOT_CHECKED.value
                disp_st = target_entry["display_status"]
                print(f"    [PASS] Derived status for node {node_id} is '{disp_st}'")
        else:
            # Ephemeral TestClient with temporary DB
            log_step("4. Verifying Authenticated Inventory Operations (Ephemeral Instance)...")
            test_node_name = f"smoke-node-{secrets.token_hex(4)}"
            reg_resp = client.post(
                "/api/nodes",
                json={"name": test_node_name, "address": "127.0.0.1", "ssh_port": 2222},
                headers=headers,
            )
            assert reg_resp.status_code == 201, f"Node registration failed: {reg_resp.text}"
            node_id = reg_resp.json()["id"]
            print(f"    [PASS] Registered node '{test_node_name}' (ID {node_id})")

            list_resp = client.get("/api/nodes", headers=headers)
            assert list_resp.status_code == 200
            node_ids = [n["id"] for n in list_resp.json()["nodes"]]
            assert node_id in node_ids
            print(f"    [PASS] GET /api/nodes verified node {node_id} present in inventory")

            status_resp = client.get("/api/nodes/status", headers=headers)
            assert status_resp.status_code == 200
            status_data = status_resp.json()
            target_entry = next(n for n in status_data["nodes"] if n["node"]["id"] == node_id)
            assert target_entry["display_status"] == DisplayStatus.NOT_CHECKED.value
            disp_st = target_entry["display_status"]
            print(f"    [PASS] Derived status for node {node_id} is '{disp_st}'")

        # 5. External Monitoring Pipeline Integration
        log_step("5. Probing Local Monitoring Services (Prometheus & Grafana)...")
        # Prometheus check
        try:
            prom_resp = httpx.get("http://127.0.0.1:9090/api/v1/targets", timeout=1.0)
            if prom_resp.status_code == 200:
                active_targets = prom_resp.json().get("data", {}).get("activeTargets", [])
                print(f"    [PASS] Prometheus active: scraping {len(active_targets)} targets")
            else:
                print(f"    [INFO] Prometheus responded with status {prom_resp.status_code}")
        except Exception:
            print("    [INFO] Prometheus (port 9090) not listening on host (skipping probe)")

        # Grafana check
        try:
            graf_resp = httpx.get("http://127.0.0.1:3000/api/health", timeout=1.0)
            if graf_resp.status_code == 200:
                print(f"    [PASS] Grafana active: health={graf_resp.json().get('database')}")
            else:
                print(f"    [INFO] Grafana responded with status {graf_resp.status_code}")
        except Exception:
            print("    [INFO] Grafana (port 3000) not currently running on host (skipping probe)")

        print("\n" + "=" * 70)
        print("ALL SMOKE TEST VERIFICATIONS PASSED SUCCESSFULLY!")
        print("=" * 70)
        return 0

    except Exception as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1

    finally:
        if live_client:
            live_client.close()
        if test_client:
            test_client.close()
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fleet Manager Release Smoke Test")
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Optional base URL of a running Fleet Manager instance",
    )
    parser.add_argument(
        "--allow-live-mutation",
        action="store_true",
        help="Opt-in to mutating inventory on a live server (requires --isolated-test-env)",
    )
    parser.add_argument(
        "--isolated-test-env",
        action="store_true",
        help="Confirm target live server is a dedicated isolated test environment",
    )
    args = parser.parse_args()
    sys.exit(
        run_smoke_test(
            base_url=args.base_url,
            allow_live_mutation=args.allow_live_mutation,
            isolated_test_env=args.isolated_test_env,
        )
    )
