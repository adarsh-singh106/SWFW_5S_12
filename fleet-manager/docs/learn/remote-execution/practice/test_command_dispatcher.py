import os
import tempfile
import subprocess
from command_dispatcher import (
    validate_action,
    execute_action,
    init_audit_db,
    list_audit_logs,
    COMMAND_CATALOG
)


def test_allowlist_rejection():
    """Arbitrary shell commands outside catalog must be rejected immediately."""
    try:
        validate_action("shell.arbitrary", {"cmd": "rm -rf /"})
        assert False, "Failed to reject unauthorized action"
    except ValueError as e:
        assert "Unauthorized action" in str(e)
    print("PASS: test_allowlist_rejection")


def test_parameter_sanitization():
    """Disallowed services or shell injection characters must be rejected."""
    # 1. Shell injection attempt
    try:
        validate_action("service.status", {"service": "nginx; reboot"})
        assert False, "Failed to reject injection characters"
    except ValueError as e:
        assert "Invalid service name format" in str(e)

    # 2. Disallowed service name
    try:
        validate_action("service.status", {"service": "crypto_miner"})
        assert False, "Failed to reject disallowed service"
    except ValueError as e:
        assert "not permitted" in str(e)

    # 3. Valid service name passes
    cmd = validate_action("service.status", {"service": "nginx"})
    assert cmd == "systemctl status nginx"
    print("PASS: test_parameter_sanitization")


def test_successful_execution_and_stream_isolation():
    """Verify clean exit code 0, stdout capture, and zero stderr pollution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "audit_test.db")

        # Mock runner returning clean uptime output
        def mock_runner(cmd, timeout):
            return {
                "exit_code": 0,
                "stdout": " 14:02:10 up 12 days, 4:15, 2 users, load average: 0.12, 0.08, 0.05",
                "stderr": "",
                "status": "success"
            }

        res = execute_action(
            node_id=1,
            action_name="system.uptime",
            db_path=db_path,
            runner_override=mock_runner
        )

        assert res["status"] == "success"
        assert res["exit_code"] == 0
        assert "up 12 days" in res["stdout"]
        assert res["stderr"] == ""
        assert res["duration_ms"] >= 0
    print("PASS: test_successful_execution_and_stream_isolation")


def test_bounded_timeout_enforcement():
    """Verify hanging command is terminated with exit code 124 and status timed_out."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "timeout_test.db")

        # Mock runner simulating subprocess.TimeoutExpired
        def hanging_runner(cmd, timeout):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

        res = execute_action(
            node_id=2,
            action_name="system.uptime",
            db_path=db_path,
            timeout=1.0,
            runner_override=hanging_runner
        )

        assert res["status"] == "timed_out"
        assert res["exit_code"] == 124
        assert "timed out after 1.0 seconds" in res["stderr"]
    print("PASS: test_bounded_timeout_enforcement")


def test_audit_persistence_e2e():
    """Verify executions are saved to SQLite command_audit_log table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "persistence_test.db")

        def mock_runner(cmd, timeout):
            return {"exit_code": 0, "stdout": "active (running)", "stderr": "", "status": "success"}

        res = execute_action(
            node_id=10,
            action_name="service.status",
            params={"service": "nginx"},
            db_path=db_path,
            runner_override=mock_runner
        )

        logs = list_audit_logs(node_id=10, db_path=db_path)
        assert len(logs) == 1
        assert logs[0]["action_name"] == "service.status"
        assert logs[0]["raw_command"] == "systemctl status nginx"
        assert logs[0]["status"] == "success"
        assert logs[0]["exit_code"] == 0
        assert logs[0]["stdout"] == "active (running)"
    print("PASS: test_audit_persistence_e2e")


if __name__ == "__main__":
    test_allowlist_rejection()
    test_parameter_sanitization()
    test_successful_execution_and_stream_isolation()
    test_bounded_timeout_enforcement()
    test_audit_persistence_e2e()
    print("\nALL 5 COMMAND DISPATCHER & AUDIT TESTS PASSED!")
