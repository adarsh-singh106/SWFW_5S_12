"""Live loopback verification of Fleet Operations Dashboard over real Uvicorn server."""

from __future__ import annotations

import json
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from fleet_manager.config import SSHSettings
from fleet_manager.main import create_app
from fleet_manager.operations.executor import DirectOperationExecutor
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationOutcome,
)
from fleet_manager.operations.transport import OperationTransport

HTTP_TIMEOUT_SECONDS = 5.0


class MockDemoTransport(OperationTransport):
    def execute(self, node, command, settings, timeout_seconds=10.0, max_output_bytes=65536):
        return OperationExecutionResult(
            outcome=OperationOutcome.SUCCESS,
            failure_category=None,
            exit_code=0,
            stdout=" 20:30:00 up 14 days, 2 users, load average: 0.12, 0.05, 0.01\n",
            stderr="",
            output_truncated=False,
        )


def main() -> int:
    print("=" * 70)
    print("SWFW_5S_12: Live Uvicorn Dashboard Verification")
    print("=" * 70)

    work_dir = Path(tempfile.mkdtemp(prefix="fm_dash_demo_"))
    db_path = work_dir / "dash_inventory.db"
    if db_path.exists():
        db_path.unlink()

    api_token = secrets.token_urlsafe(32)
    known_hosts = work_dir / "known_hosts"
    known_hosts.write_text("127.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...\n")
    priv_key = work_dir / "op_key"
    priv_key_content = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    priv_key.write_text(priv_key_content)
    ssh_settings = SSHSettings("operator", known_hosts, priv_key)

    app = create_app(
        database_path=db_path,
        api_token=api_token,
        ssh_settings=ssh_settings,
        operation_executor=DirectOperationExecutor(MockDemoTransport()),
        enable_scheduler=False,
    )

    port = 8443
    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    time.sleep(1.0)
    base_url = f"http://127.0.0.1:{port}"

    try:
        # Step 1: GET / and /dashboard (Static HTML serving)
        print("\n1. Testing Dashboard HTML Delivery over Loopback HTTP...")
        for path in ["/", "/dashboard"]:
            req = urllib.request.Request(f"{base_url}{path}")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                assert resp.status == 200
                assert "text/html" in resp.headers.get("Content-Type", "")
                assert resp.headers.get("X-Content-Type-Options") == "nosniff"
                assert resp.headers.get("X-Frame-Options") == "DENY"
                body = resp.read().decode("utf-8")
                assert "Fleet Operations Dashboard" in body
                assert "Operator Authentication" in body
                assert "localStorage" not in body.split("<script>")[1].split("</script>")[0]
                print(f"   [PASS] {path} served 200 OK with security headers nosniff & DENY")

        # Step 2: Unauthenticated API Access Protection
        print("\n2. Testing Ephemeral In-Memory Auth Guardrail...")
        unauth_req = urllib.request.Request(f"{base_url}/api/nodes/status")
        try:
            urllib.request.urlopen(unauth_req, timeout=HTTP_TIMEOUT_SECONDS)
            raise AssertionError("Unauthenticated request should have failed")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            assert exc.headers.get("WWW-Authenticate") == "Bearer"
            print("   [PASS] GET /api/nodes/status rejected unauthenticated request with HTTP 401")

        # Step 3: Register Node with XSS Payload in Name
        print("\n3. Testing Safe Node Registration with Potential XSS Payload...")
        xss_name = "<script>alert('xss')</script>web-01"
        reg_payload = json.dumps(
            {"name": xss_name, "address": "127.0.0.1", "ssh_port": 2222}
        ).encode("utf-8")
        reg_req = urllib.request.Request(
            f"{base_url}/api/nodes",
            data=reg_payload,
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(reg_req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            assert resp.status == 201
            data = json.loads(resp.read().decode("utf-8"))
            node_id = data["id"]
            assert data["name"] == xss_name
            print(f"   [PASS] Node registered with ID {node_id} (stored safely as raw text)")

        # Step 4: Fetch Fleet Status
        print("\n4. Testing Fleet Status Endpoint...")
        status_req = urllib.request.Request(
            f"{base_url}/api/nodes/status",
            headers={"Authorization": f"Bearer {api_token}"},
        )
        with urllib.request.urlopen(status_req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            assert resp.status == 200
            status_data = json.loads(resp.read().decode("utf-8"))
            nodes = status_data["nodes"]
            assert len(nodes) == 1
            assert nodes[0]["node"]["id"] == node_id
            assert nodes[0]["display_status"] == "NOT_CHECKED"
            print(f"   [PASS] Fleet status returned node {node_id} with display_status=NOT_CHECKED")

        # Step 5: Execute Allowlisted Operation: system.uptime
        print("\n5. Testing Remote Operation Dispatch: system.uptime...")
        op_payload = json.dumps({"action": "system.uptime", "arguments": {}}).encode("utf-8")
        op_req = urllib.request.Request(
            f"{base_url}/api/nodes/{node_id}/operations",
            data=op_payload,
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(op_req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            assert resp.status == 200
            op_data = json.loads(resp.read().decode("utf-8"))
            assert op_data["outcome"] == "SUCCESS"
            assert op_data["exit_code"] == 0
            assert "up 14 days" in op_data["stdout"]
            out_sample = op_data["outcome"]
            code_sample = op_data["exit_code"]
            print(f"   [PASS] Executed system.uptime: exit={code_sample}, outcome={out_sample}")

        # Step 6: Operation History Retrieval
        print("\n6. Testing Operation History Endpoint...")
        hist_req = urllib.request.Request(
            f"{base_url}/api/nodes/{node_id}/operations",
            headers={"Authorization": f"Bearer {api_token}"},
        )
        with urllib.request.urlopen(hist_req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            assert resp.status == 200
            hist_data = json.loads(resp.read().decode("utf-8"))
            ops = hist_data["operations"]
            assert len(ops) == 1
            assert ops[0]["action"] == "system.uptime"
            print(f"   [PASS] Operation history retrieved {len(ops)} record(s)")

        print("\n" + "=" * 70)
        print("ALL LIVE UVICORN DASHBOARD TESTS PASSED!")
        print("=" * 70)
        return 0

    except Exception as exc:
        print(f"[!] Dashboard verification failed: {exc}", file=sys.stderr)
        return 1

    finally:
        server.should_exit = True
        server_thread.join(timeout=3.0)
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
