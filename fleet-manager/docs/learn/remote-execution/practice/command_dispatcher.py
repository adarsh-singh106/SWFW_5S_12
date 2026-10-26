import os
import re
import time
import sqlite3
import subprocess
from typing import Dict, Any, Optional, List


COMMAND_CATALOG = {
    "system.uptime": {
        "description": "Check node uptime and load average",
        "template": "uptime",
        "needs_params": False,
    },
    "system.disk_free": {
        "description": "Check disk space on root filesystem",
        "template": "df -h /",
        "needs_params": False,
    },
    "system.memory": {
        "description": "Check free and available memory",
        "template": "free -m",
        "needs_params": False,
    },
    "service.status": {
        "description": "Inspect status of an allowed systemd service",
        "template": "systemctl status {service}",
        "needs_params": True,
        "allowed_services": ["nginx", "node_exporter", "ssh", "docker", "cron"]
    },
    "service.restart": {
        "description": "Restart an allowed systemd service",
        "template": "systemctl restart {service}",
        "needs_params": True,
        "allowed_services": ["nginx", "node_exporter", "ssh", "docker"]
    }
}


def validate_action(action_name: str, params: Optional[Dict[str, str]] = None) -> str:
    """
    Validates an action against the guarded COMMAND_CATALOG.
    Rejects unauthorized actions, malformed parameters, and injection characters.
    Returns the sanitized raw command string.
    """
    if action_name not in COMMAND_CATALOG:
        raise ValueError(
            f"Unauthorized action: {action_name!r}. Must be one of: {list(COMMAND_CATALOG.keys())}"
        )

    spec = COMMAND_CATALOG[action_name]
    if not spec.get("needs_params"):
        return spec["template"]

    # Parameterized action validation
    if not params or "service" not in params:
        raise ValueError(f"Action {action_name!r} requires parameter 'service'")

    service = str(params["service"]).strip()
    if not re.match(r"^[a-zA-Z0-9_\-]+$", service):
        raise ValueError(f"Invalid service name format: {service!r}")

    allowed = spec.get("allowed_services", [])
    if service not in allowed:
        raise ValueError(f"Service {service!r} not permitted. Allowed: {allowed}")

    return spec["template"].format(service=service)


def init_audit_db(db_path: str = "inventory.db") -> None:
    """Initializes the immutable command_audit_log SQLite table."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS command_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id INTEGER NOT NULL,
                    action_name TEXT NOT NULL,
                    raw_command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    stdout TEXT,
                    stderr TEXT,
                    duration_ms REAL NOT NULL,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
    finally:
        conn.close()


def record_audit_log(
    node_id: int,
    action_name: str,
    raw_command: str,
    status: str,
    exit_code: Optional[int],
    stdout: str,
    stderr: str,
    duration_ms: float,
    db_path: str = "inventory.db"
) -> int:
    """Inserts a single execution audit event into the database."""
    init_audit_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO command_audit_log (
                    node_id, action_name, raw_command, status,
                    exit_code, stdout, stderr, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, action_name, raw_command, status,
                 exit_code, stdout, stderr, duration_ms)
            )
            return cursor.lastrowid
    finally:
        conn.close()


def list_audit_logs(node_id: Optional[int] = None, db_path: str = "inventory.db") -> List[Dict[str, Any]]:
    """Retrieves execution audit records, optionally filtered by node_id."""
    init_audit_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        if node_id is not None:
            cursor = conn.execute(
                "SELECT * FROM command_audit_log WHERE node_id = ? ORDER BY id DESC",
                (node_id,)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM command_audit_log ORDER BY id DESC"
            )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def execute_action(
    node_id: int,
    action_name: str,
    params: Optional[Dict[str, str]] = None,
    db_path: str = "inventory.db",
    timeout: float = 5.0,
    runner_override = None
) -> Dict[str, Any]:
    """
    Executes a catalogued action with bounded timeouts and stream isolation.
    Records the outcome in the audit database.
    
    runner_override: Optional callable(cmd_str, timeout) for deterministic testing.
    """
    raw_command = validate_action(action_name, params)
    
    start_time = time.perf_counter()
    status = "failed"
    exit_code = None
    stdout = ""
    stderr = ""

    try:
        if runner_override:
            res = runner_override(raw_command, timeout)
            exit_code = res["exit_code"]
            stdout = res.get("stdout", "")
            stderr = res.get("stderr", "")
            status = res.get("status", "success" if exit_code == 0 else "failed")
        else:
            # Standard bounded subprocess execution
            proc = subprocess.run(
                raw_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            exit_code = proc.returncode
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            status = "success" if exit_code == 0 else "failed"

    except subprocess.TimeoutExpired as e:
        status = "timed_out"
        exit_code = 124  # Standard Linux timeout exit code
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = f"Execution timed out after {timeout} seconds (SIGKILL applied)"
    except Exception as e:
        status = "failed"
        exit_code = -1
        stderr = f"Execution error: {str(e)}"

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    audit_id = record_audit_log(
        node_id=node_id,
        action_name=action_name,
        raw_command=raw_command,
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        db_path=db_path
    )

    return {
        "audit_id": audit_id,
        "node_id": node_id,
        "action_name": action_name,
        "raw_command": raw_command,
        "status": status,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms
    }
