"""Verify live Prometheus + Grafana pipeline with real Fleet Manager and Node Exporter."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_FM_URL = "http://127.0.0.1:8000"
DEFAULT_PROM_URL = "http://127.0.0.1:9090"
DEFAULT_GRAFANA_URL = "http://127.0.0.1:3000"
DEFAULT_HTTP_TIMEOUT_SECONDS = 5.0


def get_api_token() -> str:
    """Retrieve Fleet Manager API token from environment.

    Fails immediately if missing or blank. Never accepts secrets from CLI args.
    """
    token = os.getenv("FLEET_MANAGER_API_TOKEN")
    if not token or not token.strip():
        raise ValueError(
            "Missing required environment variable 'FLEET_MANAGER_API_TOKEN'. "
            "Set FLEET_MANAGER_API_TOKEN in your environment before running this script."
        )
    return token.strip()


def fm_request(
    base_url: str,
    path: str,
    token: str,
    method: str = "GET",
    data: dict | None = None,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> dict | list:
    """Execute an authenticated request to Fleet Manager without echoing credentials."""
    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    body: bytes | None = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        # Sanitize error message to prevent echoing Authorization headers or token
        raise RuntimeError(
            f"HTTP error {exc.code} accessing Fleet Manager endpoint {path}: {exc.reason}"
        ) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Network error accessing Fleet Manager endpoint {path}: {exc.reason}"
        ) from None


def prom_query(
    prom_url: str,
    expr: str,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> list[dict]:
    """Execute an instant query against Prometheus API with bounded timeout."""
    url = f"{prom_url.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': expr})}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") != "success":
                raise RuntimeError(
                    f"Prometheus query status '{data.get('status')}' for expression '{expr}'"
                )
            return data.get("data", {}).get("result", [])
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP error {exc.code} querying Prometheus: {exc.reason}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error querying Prometheus: {exc.reason}") from None


def get_grafana_auth_header() -> str:
    """Retrieve Grafana authentication header from environment.

    Requires explicit environment configuration. Never accepts known or shared
    default credentials such as admin/admin.
    """
    token = os.getenv("GRAFANA_TOKEN")
    if token and token.strip():
        return f"Bearer {token.strip()}"

    user = os.getenv("GRAFANA_USER")
    password = os.getenv("GRAFANA_PASSWORD")
    if not user or not user.strip() or not password or not password.strip():
        raise ValueError(
            "Grafana authentication requires environment configuration. "
            "Set GRAFANA_USER and GRAFANA_PASSWORD (or GRAFANA_TOKEN) before running."
        )
    if user.strip().lower() == "admin" and password.strip().lower() == "admin":
        raise ValueError(
            "Known default credentials (admin/admin) are rejected. "
            "Configure distinct non-default credentials in GRAFANA_USER and GRAFANA_PASSWORD."
        )
    raw_auth = f"{user.strip()}:{password.strip()}".encode()
    return "Basic " + base64.b64encode(raw_auth).decode("ascii")


def grafana_get(
    grafana_url: str,
    path: str,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> dict:
    """Query Grafana API using credentials from environment with bounded timeout."""
    auth_header = get_grafana_auth_header()

    req = urllib.request.Request(
        f"{grafana_url.rstrip('/')}{path}",
        headers={"Accept": "application/json", "Authorization": auth_header},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP error {exc.code} accessing Grafana {path}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error accessing Grafana {path}: {exc.reason}") from None


def verify_service_restart(allow_service_restart: bool, prom_url: str) -> None:
    """Optionally test exporter unavailability handling under explicit opt-in."""
    if not allow_service_restart:
        print("\n=== 6. Skipping Service Restart Verification ===")
        print("[INFO] Service restart test disabled by default (read-only mode).")
        print("[INFO] Pass --allow-service-restart to explicitly authorize this test.")
        return

    target_service = "prometheus-node-exporter"
    print("\n=== 6. Testing Exporter Unavailability Handling ===")
    print(f"[*] Explaining action: will stop and restart systemd service '{target_service}'")
    print("    Fleet Manager itself will NOT be restarted.")

    if os.name != "posix" or shutil.which("systemctl") is None:
        print(f"[!] Systemctl not found on current platform ({sys.platform}); skipping restart.")
        return

    # Check whether the service is currently running
    active_check = subprocess.run(
        ["systemctl", "is-active", "--quiet", target_service],
        check=False,
    )
    if active_check.returncode != 0:
        print(f"[!] Service '{target_service}' is not currently active; cannot test stop/restart.")
        return

    # Stop service safely and restore in finally
    print(f"[*] Stopping '{target_service}' via systemctl...")
    subprocess.run(["sudo", "systemctl", "stop", target_service], check=True)
    try:
        print("Waiting 6 seconds for Prometheus scrape detection...")
        time.sleep(6)
        up_node_down = prom_query(prom_url, 'up{job="node_exporter"}')
        assert up_node_down and up_node_down[0]["value"][1] == "0", (
            "Prometheus did not detect node_exporter down"
        )
        print(f"After stop: up{{job='node_exporter'}} = {up_node_down[0]['value'][1]}")

        up_fm_still_up = prom_query(prom_url, 'up{job="fleet-manager"}')
        assert up_fm_still_up and up_fm_still_up[0]["value"][1] == "1", (
            "fleet-manager should remain up"
        )
        print(f"After stop: up{{job='fleet-manager'}} = {up_fm_still_up[0]['value'][1]}")
    finally:
        print(f"[*] Restoring service state: restarting '{target_service}'...")
        subprocess.run(["sudo", "systemctl", "start", target_service], check=True)
        time.sleep(6)
        up_node_recovered = prom_query(prom_url, 'up{job="node_exporter"}')
        assert up_node_recovered and up_node_recovered[0]["value"][1] == "1", (
            "node_exporter did not recover"
        )
        print(f"After restart: up{{job='node_exporter'}} = {up_node_recovered[0]['value'][1]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify live Prometheus + Grafana pipeline with Fleet Manager",
    )
    parser.add_argument(
        "--fm-url",
        default=DEFAULT_FM_URL,
        help="Base URL of Fleet Manager instance (default: %(default)s)",
    )
    parser.add_argument(
        "--prom-url",
        default=DEFAULT_PROM_URL,
        help="Base URL of Prometheus instance (default: %(default)s)",
    )
    parser.add_argument(
        "--grafana-url",
        default=DEFAULT_GRAFANA_URL,
        help="Base URL of Grafana instance (default: %(default)s)",
    )
    parser.add_argument(
        "--allow-live-mutation",
        action="store_true",
        help="Explicitly permit registering test nodes and triggering connectivity checks",
    )
    parser.add_argument(
        "--allow-service-restart",
        action="store_true",
        help="Explicitly authorize stopping and restarting prometheus-node-exporter",
    )
    args = parser.parse_args(argv)

    try:
        token = get_api_token()
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    try:
        print("=== 1. Checking Nodes in Fleet Manager ===")
        res = fm_request(args.fm_url, "/api/nodes", token=token)
        nodes = res.get("nodes", []) if isinstance(res, dict) else res

        node: dict | None = None
        if nodes:
            node = nodes[0]
            print(
                f"Reusing existing node: ID={node['id']} Name={node['name']} Addr={node['address']}"
            )
        else:
            if args.allow_live_mutation:
                created = fm_request(
                    args.fm_url,
                    "/api/nodes",
                    token=token,
                    method="POST",
                    data={"name": "demo-local-target", "address": "127.0.0.1"},
                )
                node = created if isinstance(created, dict) else None
                if node:
                    print(
                        f"Registered test node: ID={node['id']} Name={node['name']} "
                        f"Addr={node['address']}"
                    )
            else:
                print(
                    "[INFO] No nodes in inventory and --allow-live-mutation not set; "
                    "skipping node registration."
                )

        if node and args.allow_live_mutation:
            print("\n=== 2. Triggering Node Connectivity Check ===")
            check = fm_request(
                args.fm_url,
                f"/api/nodes/{node['id']}/connectivity-check",
                token=token,
                method="POST",
            )
            if isinstance(check, dict):
                obs = check.get("observed_at")
                print(f"Check outcome: {check.get('outcome')} (Observed: {obs})")
        else:
            print("\n=== 2. Skipping Node Connectivity Check ===")
            print(
                "[INFO] Connectivity check skipped "
                "(requires existing node and --allow-live-mutation)."
            )

        print("\n=== 3. Waiting for Prometheus scrape cycle ===")
        time.sleep(2)

        print("\n=== 4. Querying Prometheus Targets and Metrics ===")
        up_fm = prom_query(args.prom_url, 'up{job="fleet-manager"}')
        if up_fm:
            print(f"up{{job='fleet-manager'}}: {up_fm[0]['value'][1]}")
            assert up_fm[0]["value"][1] == "1", "fleet-manager scrape target is down"

        up_node = prom_query(args.prom_url, 'up{job="node_exporter"}')
        if up_node:
            print(f"up{{job='node_exporter'}}: {up_node[0]['value'][1]}")
            assert up_node[0]["value"][1] == "1", "node_exporter scrape target is down"

        checks_total = prom_query(args.prom_url, "fleet_connectivity_checks_total")
        print("fleet_connectivity_checks_total series:")
        for series in checks_total:
            val = float(series["value"][1])
            if val > 0:
                print(f"  {series['metric']}: {val}")

        nodes_status = prom_query(args.prom_url, "fleet_nodes_by_status")
        print("fleet_nodes_by_status series:")
        for series in nodes_status:
            val = float(series["value"][1])
            if val > 0:
                print(f"  {series['metric']}: {val}")

        cpu = prom_query(
            args.prom_url,
            '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)',
        )
        if cpu:
            print(f"Linux host CPU usage (%): {float(cpu[0]['value'][1]):.2f}%")

        mem = prom_query(
            args.prom_url,
            "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100",
        )
        if mem:
            print(f"Linux host Memory usage (%): {float(mem[0]['value'][1]):.2f}%")

        disk = prom_query(args.prom_url, 'node_filesystem_avail_bytes{mountpoint="/"}')
        if disk:
            avail_gb = float(disk[0]["value"][1]) / (1024**3)
            print(f"Linux host Disk available on /: {avail_gb:.2f} GiB")

        print("\n=== 5. Verifying Grafana Datasource and Dashboard Provisioning ===")
        ds = grafana_get(args.grafana_url, "/api/datasources/name/Prometheus")
        print(f"Datasource '{ds['name']}': UID={ds['uid']}, Type={ds['type']}, URL={ds['url']}")

        ds_health = grafana_get(args.grafana_url, f"/api/datasources/uid/{ds['uid']}/health")
        h_stat = ds_health.get("status")
        h_msg = ds_health.get("message")
        print(f"Datasource Health: status={h_stat} message={h_msg}")
        assert ds_health.get("status") == "OK", "Grafana Prometheus datasource is not healthy"

        dash = grafana_get(args.grafana_url, "/api/dashboards/uid/fleet-manager-overview")
        v = dash["dashboard"]["version"]
        panels = len(dash["dashboard"]["panels"])
        print(f"Dashboard: '{dash['dashboard']['title']}' (version {v}, {panels} panels)")

        # Step 6: Service restart testing (opt-in only)
        verify_service_restart(args.allow_service_restart, args.prom_url)

        print("\n=== ALL VERIFICATION CHECKS COMPLETED SUCCESSFULLY ===")
        return 0
    except Exception as exc:
        # Sanitize exception output
        print(f"Error during verification: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
