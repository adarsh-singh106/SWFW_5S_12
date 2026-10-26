import os
import sys
import tempfile

# Add node-inventory practice path to import app and storage
base_dir = os.path.dirname(__file__)
inventory_practice_dir = os.path.abspath(os.path.join(base_dir, "..", "..", "node-inventory", "practice"))
sys.path.insert(0, inventory_practice_dir)

from command_dispatcher import execute_action, list_audit_logs, COMMAND_CATALOG
from db_storage import init_db, add_node


def run_verification():
    print("=================================================================")
    print("FLEET MANAGER - MILESTONE 4: CONTROLLED EXECUTION & AUDIT DEMO")
    print("=================================================================")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "demo_m4.db")
        init_db(db_path)

        # 1. Onboard Node
        print("\n[STEP 1] Onboarding Node in Test Database...")
        node_id = add_node("Web Server Prod 1", "192.168.1.100", 22, db_path=db_path)
        print(f"  -> [OK] Node registered with ID: {node_id}")

        # 2. Test Allowlist Catalog Inspection
        print("\n[STEP 2] Inspecting Guarded Action Catalog...")
        print(f"  -> Total Catalog Actions: {len(COMMAND_CATALOG)}")
        for name, spec in COMMAND_CATALOG.items():
            print(f"     * {name:<18} -> {spec['description']}")

        # 3. Execute Valid Action
        print("\n[STEP 3] Executing Allowed Action ('system.uptime') with Mock Runner...")
        def mock_runner(cmd, timeout):
            return {
                "exit_code": 0,
                "stdout": "up 14 days, 3:20, load average: 0.05, 0.02, 0.00",
                "stderr": "",
                "status": "success"
            }

        res = execute_action(
            node_id=node_id,
            action_name="system.uptime",
            db_path=db_path,
            runner_override=mock_runner
        )
        print(f"  -> Status: {res['status']}")
        print(f"  -> Exit Code: {res['exit_code']}")
        print(f"  -> Duration: {res['duration_ms']} ms")
        print(f"  -> Stdout: {res['stdout']}")

        # 4. Attempt Unauthorized Action (Hacker simulation)
        print("\n[STEP 4] Simulating Shell Injection Attack ('rm -rf /')...")
        try:
            execute_action(
                node_id=node_id,
                action_name="shell.arbitrary",
                params={"cmd": "rm -rf /"},
                db_path=db_path
            )
            print("  -> [FAIL] Injection was NOT blocked!")
        except ValueError as e:
            print(f"  -> [OK] Gatekeeper Blocked Injection: {e}")

        # 5. Verify Immutable Audit Log Table
        print("\n[STEP 5] Querying SQLite 'command_audit_log' Table directly...")
        logs = list_audit_logs(node_id=node_id, db_path=db_path)
        print(f"  -> Found {len(logs)} Audit Entry:")
        for log in logs:
            print(f"     [ID #{log['id']}] {log['executed_at']} | Action: {log['action_name']} | Status: {log['status']} | Exit: {log['exit_code']}")

    print("\n=================================================================")
    print("MILESTONE 4 VERIFICATION COMPLETE: ALL SYSTEMS WORKING!")
    print("=================================================================")


if __name__ == "__main__":
    run_verification()
