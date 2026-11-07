"""Live verification and demonstration of controlled remote operations."""

from __future__ import annotations

import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.main import create_app
from fleet_manager.operations.executor import OperationExecutor
from fleet_manager.operations.models import OperationOutcome
from fleet_manager.operations.repository import SQLiteOperationsRepository


def run_verification(operation_executor: OperationExecutor | None = None) -> bool:
    print("=" * 70)
    print("SWFW_5S_12: Controlled Remote Operations Live Demonstration")
    print("=" * 70)

    work_dir = Path(tempfile.mkdtemp(prefix="fm_operations_demo_"))
    db_path = work_dir / "demo_inventory.db"
    if db_path.exists():
        db_path.unlink()

    known_hosts_path = work_dir / "known_hosts"

    configured_key = os.getenv("FLEET_MANAGER_SSH_KEY")
    if configured_key and Path(configured_key).exists():
        private_key_path = Path(configured_key)
    else:
        private_key_path = work_dir / "demo_key"
        private_key_path.write_text("fake-disposable-key\n")
        if os.name == "posix":
            private_key_path.chmod(0o600)

    # Set up host key trust for local Linux SSH target
    key_b64 = "AAAAC3NzaC1lZDI1NTE5AAAAIMZkiMiVmA2741TqT50Cbzso6L/AWJ0OYeWXGmkYVKOc"
    known_hosts_content = f"127.0.0.1 ssh-ed25519 {key_b64}\n[127.0.0.1]:22 ssh-ed25519 {key_b64}\n"
    known_hosts_path.write_text(known_hosts_content, encoding="ascii")

    ssh_username = os.getenv("FLEET_MANAGER_SSH_USER") or os.getenv("USER") or "operator"
    ssh_settings = SSHSettings(
        username=ssh_username,
        known_hosts_path=known_hosts_path,
        private_key_path=private_key_path,
    )

    api_token = secrets.token_urlsafe(32)
    headers = {"Authorization": f"Bearer {api_token}"}

    try:
        print(f"1. Initializing Fleet Manager app with DB: {db_path}")
        app = create_app(
            database_path=db_path,
            api_token=api_token,
            ssh_settings=ssh_settings,
            operation_executor=operation_executor,
            enable_scheduler=False,
        )

        with TestClient(app, headers=headers) as client:
            # Step 1: Authentication enforcement
            print("\n2. Testing Authentication Guardrails...")
            unauth_resp = client.post(
                "/api/nodes/1/operations",
                json={"action": "system.uptime", "arguments": {}},
                headers={"Authorization": "Bearer bad-token-00000000000000000000000000"},
            )
            assert unauth_resp.status_code == 401, f"Expected 401, got {unauth_resp.status_code}"
            print("   [PASS] Invalid bearer token rejected with HTTP 401 Unauthorized")

            # Step 2: Register target Linux node
            print("\n3. Registering Target Linux Node in Fleet Manager...")
            node_resp = client.post(
                "/api/nodes",
                json={"name": "debian-target", "address": "127.0.0.1", "ssh_port": 22},
            )
            assert node_resp.status_code == 201, f"Node registration failed: {node_resp.text}"
            node_id = node_resp.json()["id"]
            print(f"   [PASS] Registered node ID {node_id} (127.0.0.1:22)")

            # Step 3: Test Disallowed Action
            print("\n4. Testing Action Catalog Policy Enforcement...")
            disallowed = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": "service.restart", "arguments": {"service": "ssh"}},
            )
            assert disallowed.status_code == 422, f"Expected 422, got {disallowed.status_code}"
            assert disallowed.json()["error"]["code"] == "invalid_action"
            print(
                "   [PASS] Disallowed action 'service.restart' rejected with "
                "HTTP 422 invalid_action"
            )

            # Step 4: Test Injection Protection
            print("\n5. Testing Injection and Metacharacter Sanitization...")
            injected = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": "system.disk", "arguments": {"path": "/var; cat /etc/shadow"}},
            )
            assert injected.status_code == 422, f"Expected 422, got {injected.status_code}"
            assert injected.json()["error"]["code"] == "invalid_arguments"
            print(
                "   [PASS] Shell metacharacter injection rejected with HTTP 422 invalid_arguments"
            )

            # Step 5: Execute allowlisted action: system.uptime
            print("\n6. Executing Remote Operation: 'system.uptime'...")
            r_uptime = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": "system.uptime", "arguments": {}},
            )
            assert r_uptime.status_code == 200, f"Execution failed: {r_uptime.text}"
            d_uptime = r_uptime.json()
            print(f"   Outcome: {d_uptime['outcome']}")
            print(f"   Exit code: {d_uptime['exit_code']}")
            print(f"   Remote Output: {d_uptime['stdout'].strip()}")
            assert d_uptime["outcome"] == "SUCCESS"
            assert d_uptime["exit_code"] == 0
            assert "up" in d_uptime["stdout"]
            print("   [PASS] 'system.uptime' executed remotely and returned real Linux uptime")

            # Step 6: Execute allowlisted action: system.memory
            print("\n7. Executing Remote Operation: 'system.memory'...")
            r_mem = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": "system.memory", "arguments": {}},
            )
            assert r_mem.status_code == 200, f"Execution failed: {r_mem.text}"
            d_mem = r_mem.json()
            print(f"   Outcome: {d_mem['outcome']}")
            print(f"   Exit code: {d_mem['exit_code']}")
            print(f"   Remote Output:\n{d_mem['stdout'].strip()}")
            assert d_mem["outcome"] == "SUCCESS"
            assert "Mem:" in d_mem["stdout"]
            print("   [PASS] 'system.memory' returned real Linux memory statistics")

            # Step 7: Execute allowlisted action: system.disk
            print("\n8. Executing Remote Operation: 'system.disk' (path='/')...")
            r_disk = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": "system.disk", "arguments": {"path": "/"}},
            )
            assert r_disk.status_code == 200, f"Execution failed: {r_disk.text}"
            d_disk = r_disk.json()
            print(f"   Outcome: {d_disk['outcome']}")
            print(f"   Exit code: {d_disk['exit_code']}")
            print(f"   Remote Output:\n{d_disk['stdout'].strip()}")
            assert d_disk["outcome"] == "SUCCESS"
            assert "/" in d_disk["stdout"]
            print("   [PASS] 'system.disk' executed remotely and returned POSIX filesystem usage")

            # Step 8: Execute allowlisted action: service.status
            print("\n9. Executing Remote Operation: 'service.status' (service_name='ssh')...")
            r_svc = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": "service.status", "arguments": {"service_name": "ssh"}},
            )
            assert r_svc.status_code == 200, f"Execution failed: {r_svc.text}"
            d_svc = r_svc.json()
            print(f"   Outcome: {d_svc['outcome']}")
            print(f"   Exit code: {d_svc['exit_code']}")
            print(f"   Remote Output:\n{d_svc['stdout'].strip()[:200]}...")
            assert "ssh" in d_svc["stdout"].lower()
            print(
                "   [PASS] 'service.status' executed remotely and returned systemd service status"
            )

            # Step 9: Audit and Persistence Check
            print("\n10. Verifying Durable Audit Records and Listing...")
            r_list = client.get(f"/api/nodes/{node_id}/operations")
            assert r_list.status_code == 200
            ops = r_list.json()["operations"]
            print(f"   Total operations recorded in DB: {len(ops)}")
            assert len(ops) >= 4
            first_op = ops[0]
            assert first_op["audit_metadata"]["operator_type"] == "bearer_token"
            assert "operator_digest_prefix" in first_op["audit_metadata"]
            print(f"   Audit metadata recorded: {first_op['audit_metadata']}")
            print("   [PASS] Execution audit records persisted with bounded outputs and metadata")

            # Step 10: Control-Plane Restart Reconciliation Check
            print("\n11. Testing Control-Plane Crash/Restart Reconciliation...")
            op_repo = SQLiteOperationsRepository(db_path)
            # Verify schema version
            import sqlite3

            with sqlite3.connect(db_path) as conn:
                v = conn.execute("PRAGMA user_version").fetchone()[0]
                print(f"   Authoritative SQLite PRAGMA user_version: {v}")
                assert v in (3, 4, 5, 6), f"Expected user_version 3, 4, 5 or 6, got {v}"

            # Insert simulated in-flight crash record
            from datetime import UTC, datetime

            from fleet_manager.operations.models import OperationRecord

            now = datetime.now(UTC)
            crashed_job = OperationRecord(
                id="op_crash_test",
                node_id=node_id,
                action="system.uptime",
                arguments={},
                requested_at=now,
                started_at=now,
                completed_at=None,
                outcome=OperationOutcome.RUNNING,
                failure_category=None,
                exit_code=None,
                stdout=None,
                stderr=None,
                output_truncated=False,
                audit_metadata={"operator_type": "bearer_token"},
            )
            op_repo.create(crashed_job)

            # Simulate restart
            reconciled = op_repo.reconcile_in_flight()
            assert reconciled == 1
            rec = op_repo.get("op_crash_test")
            assert rec is not None
            assert rec.outcome == OperationOutcome.UNCERTAIN
            assert rec.failure_category is not None
            assert rec.failure_category.value == "CONTROL_PLANE_RESTARTED"
            print(f"   [PASS] In-flight job reconciled: outcome={rec.outcome.value}")

        print("\n" + "=" * 70)
        print("ALL REMOTE OPERATION CHECKS AND LIVE DEMONSTRATION PASSED!")
        print("=" * 70)
        return True

    except Exception as exc:
        print(f"[!] Operation verification failed: {exc}", file=sys.stderr)
        return False

    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
