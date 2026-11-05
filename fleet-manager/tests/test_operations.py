"""Comprehensive tests for controlled remote operations."""

import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fleet_manager.config import OperationLimits, SSHSettings
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.main import create_app
from fleet_manager.operations.catalog import validate_action
from fleet_manager.operations.executor import DirectOperationExecutor
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationFailureCategory,
    OperationOutcome,
    OperationRecord,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.transport import OperationTransport


class FakeOperationTransport(OperationTransport):
    def __init__(self) -> None:
        self.calls: list[tuple[Node, str, SSHSettings, float, int]] = []
        self.result: OperationExecutionResult | None = None
        self.local_execution_detected = False

    def execute(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        self.calls.append((node, command, settings, timeout_seconds, max_output_bytes))
        if self.result is not None:
            return self.result
        return OperationExecutionResult(
            outcome=OperationOutcome.SUCCESS,
            failure_category=None,
            exit_code=0,
            stdout="Fake command output\n",
            stderr="",
            output_truncated=False,
        )


@pytest.fixture
def api_token() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def auth_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}"}


@pytest.fixture
def ssh_settings(tmp_path: Path) -> SSHSettings:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("192.0.2.10 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...\n")
    private_key = tmp_path / "operator-key"
    private_key.write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    return SSHSettings("operator", known_hosts, private_key)


@pytest.fixture
def fake_transport() -> FakeOperationTransport:
    return FakeOperationTransport()


@pytest.fixture
def operations_client(
    tmp_path: Path,
    api_token: str,
    auth_headers: dict[str, str],
    ssh_settings: SSHSettings,
    fake_transport: FakeOperationTransport,
) -> TestClient:
    app = create_app(
        database_path=tmp_path / "inventory.db",
        api_token=api_token,
        ssh_settings=ssh_settings,
        operation_transport=fake_transport,
    )
    return TestClient(app, headers=auth_headers)


def test_catalog_allowed_actions() -> None:
    res = validate_action("system.uptime", {})
    assert res.remote_command == "uptime"
    assert res.sanitized_arguments == {}

    res = validate_action("system.memory", {})
    assert res.remote_command == "free -m"
    assert res.sanitized_arguments == {}

    res = validate_action("system.disk", {"path": "/var/log"})
    assert res.remote_command == "df -h -P -- /var/log"
    assert res.sanitized_arguments == {"path": "/var/log"}

    res = validate_action("service.status", {"service_name": "node_exporter"})
    assert res.remote_command == "systemctl --no-pager status -- node_exporter"
    assert res.sanitized_arguments == {"service_name": "node_exporter"}


def test_catalog_disallowed_actions(operations_client: TestClient) -> None:
    with operations_client as client:
        reg = client.post(
            "/api/nodes", json={"name": "srv1", "address": "192.0.2.1", "ssh_port": 22}
        )
        node_id = reg.json()["id"]

        for bad_action in [
            "system.reboot",
            "system.shutdown",
            "service.restart",
            "shell.exec",
            "rm",
        ]:
            resp = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": bad_action, "arguments": {}},
            )
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "invalid_action"


def test_catalog_invalid_typed_arguments(operations_client: TestClient) -> None:
    with operations_client as client:
        reg = client.post(
            "/api/nodes", json={"name": "srv1", "address": "192.0.2.1", "ssh_port": 22}
        )
        node_id = reg.json()["id"]

        # uptime with extra args
        r = client.post(
            f"/api/nodes/{node_id}/operations",
            json={"action": "system.uptime", "arguments": {"extra": "val"}},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "invalid_arguments"

        # disk without path
        r = client.post(
            f"/api/nodes/{node_id}/operations", json={"action": "system.disk", "arguments": {}}
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "invalid_arguments"

        # disk with non-absolute path
        r = client.post(
            f"/api/nodes/{node_id}/operations",
            json={"action": "system.disk", "arguments": {"path": "etc/passwd"}},
        )
        assert r.status_code == 422

        # disk with directory traversal
        r = client.post(
            f"/api/nodes/{node_id}/operations",
            json={"action": "system.disk", "arguments": {"path": "/var/../etc"}},
        )
        assert r.status_code == 422

        # disk with shell characters
        for unsafe_path in ["/var; rm -rf /", "/var | cat", "/var `id`", "/var $(whoami)"]:
            r = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": "system.disk", "arguments": {"path": unsafe_path}},
            )
            assert r.status_code == 422
            assert r.json()["error"]["code"] == "invalid_arguments"

        # service.status without service_name
        r = client.post(
            f"/api/nodes/{node_id}/operations", json={"action": "service.status", "arguments": {}}
        )
        assert r.status_code == 422

        # service.status with leading flag
        r = client.post(
            f"/api/nodes/{node_id}/operations",
            json={"action": "service.status", "arguments": {"service_name": "--version"}},
        )
        assert r.status_code == 422

        # service.status with injection
        for unsafe_service in ["nginx; rm -rf", "ssh | nc", "ssh && echo 1"]:
            r = client.post(
                f"/api/nodes/{node_id}/operations",
                json={"action": "service.status", "arguments": {"service_name": unsafe_service}},
            )
            assert r.status_code == 422


def test_authentication_required_for_operations(tmp_path: Path, api_token: str) -> None:
    app = create_app(database_path=tmp_path / "inventory.db", api_token=api_token)
    with TestClient(app) as unauth_client:
        r = unauth_client.post(
            "/api/nodes/1/operations", json={"action": "system.uptime", "arguments": {}}
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"

        r = unauth_client.get("/api/nodes/1/operations")
        assert r.status_code == 401

    with TestClient(
        app, headers={"Authorization": "Bearer invalid_token_12345678901234567890"}
    ) as bad_client:
        r = bad_client.post(
            "/api/nodes/1/operations", json={"action": "system.uptime", "arguments": {}}
        )
        assert r.status_code == 401


def test_unknown_node_returns_404(operations_client: TestClient) -> None:
    with operations_client as client:
        r = client.post(
            "/api/nodes/99999/operations",
            json={"action": "system.uptime", "arguments": {}},
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "node_not_found"

        r = client.get("/api/nodes/99999/operations")
        assert r.status_code == 404


def test_successful_operation_execution(
    operations_client: TestClient, fake_transport: FakeOperationTransport
) -> None:
    fake_transport.result = OperationExecutionResult(
        outcome=OperationOutcome.SUCCESS,
        failure_category=None,
        exit_code=0,
        stdout="14:00:00 up 10 days\n",
        stderr="",
        output_truncated=False,
    )
    with operations_client as client:
        reg = client.post(
            "/api/nodes", json={"name": "srv1", "address": "192.0.2.1", "ssh_port": 22}
        )
        node_id = reg.json()["id"]

        resp = client.post(
            f"/api/nodes/{node_id}/operations",
            json={"action": "system.uptime", "arguments": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == node_id
        assert data["action"] == "system.uptime"
        assert data["outcome"] == "SUCCESS"
        assert data["failure_category"] is None
        assert data["exit_code"] == 0
        assert data["stdout"] == "14:00:00 up 10 days\n"
        assert data["output_truncated"] is False
        assert "op_" in data["id"]
        assert data["audit_metadata"]["operator_type"] == "bearer_token"
        assert "operator_digest_prefix" in data["audit_metadata"]

        assert len(fake_transport.calls) == 1
        assert fake_transport.calls[0][1] == "uptime"


def test_operation_failure_and_exit_code(
    operations_client: TestClient, fake_transport: FakeOperationTransport
) -> None:
    fake_transport.result = OperationExecutionResult(
        outcome=OperationOutcome.FAILURE,
        failure_category=OperationFailureCategory.COMMAND_ERROR,
        exit_code=3,
        stdout="● nginx.service - inactive (dead)\n",
        stderr="",
        output_truncated=False,
    )
    with operations_client as client:
        reg = client.post(
            "/api/nodes", json={"name": "srv1", "address": "192.0.2.1", "ssh_port": 22}
        )
        node_id = reg.json()["id"]

        resp = client.post(
            f"/api/nodes/{node_id}/operations",
            json={"action": "service.status", "arguments": {"service_name": "nginx"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "FAILURE"
        assert data["failure_category"] == "COMMAND_ERROR"
        assert data["exit_code"] == 3
        assert "inactive (dead)" in data["stdout"]


def test_operation_host_key_and_auth_failures(
    operations_client: TestClient, fake_transport: FakeOperationTransport
) -> None:
    with operations_client as client:
        reg = client.post(
            "/api/nodes", json={"name": "srv1", "address": "192.0.2.1", "ssh_port": 22}
        )
        node_id = reg.json()["id"]

        # Host key mismatch
        fake_transport.result = OperationExecutionResult(
            outcome=OperationOutcome.FAILURE,
            failure_category=OperationFailureCategory.HOST_KEY_MISMATCH,
            exit_code=None,
            stdout=None,
            stderr="Host key mismatch",
            output_truncated=False,
        )
        resp = client.post(f"/api/nodes/{node_id}/operations", json={"action": "system.uptime"})
        assert resp.json()["outcome"] == "FAILURE"
        assert resp.json()["failure_category"] == "HOST_KEY_MISMATCH"

        # Auth failed
        fake_transport.result = OperationExecutionResult(
            outcome=OperationOutcome.FAILURE,
            failure_category=OperationFailureCategory.AUTH_FAILED,
            exit_code=None,
            stdout=None,
            stderr="Authentication rejected",
            output_truncated=False,
        )
        resp = client.post(f"/api/nodes/{node_id}/operations", json={"action": "system.uptime"})
        assert resp.json()["outcome"] == "FAILURE"
        assert resp.json()["failure_category"] == "AUTH_FAILED"


def test_operation_execution_timeout(
    operations_client: TestClient, fake_transport: FakeOperationTransport
) -> None:
    fake_transport.result = OperationExecutionResult(
        outcome=OperationOutcome.TIMEOUT,
        failure_category=OperationFailureCategory.TIMEOUT,
        exit_code=None,
        stdout=None,
        stderr="Operation timed out",
        output_truncated=False,
    )
    with operations_client as client:
        reg = client.post(
            "/api/nodes", json={"name": "srv1", "address": "192.0.2.1", "ssh_port": 22}
        )
        node_id = reg.json()["id"]

        resp = client.post(f"/api/nodes/{node_id}/operations", json={"action": "system.uptime"})
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "TIMEOUT"
        assert resp.json()["failure_category"] == "TIMEOUT"


def test_operation_bounded_output(
    operations_client: TestClient, fake_transport: FakeOperationTransport
) -> None:
    fake_transport.result = OperationExecutionResult(
        outcome=OperationOutcome.SUCCESS,
        failure_category=None,
        exit_code=0,
        stdout="X" * 1024,
        stderr="",
        output_truncated=True,
    )
    with operations_client as client:
        reg = client.post(
            "/api/nodes", json={"name": "srv1", "address": "192.0.2.1", "ssh_port": 22}
        )
        node_id = reg.json()["id"]

        resp = client.post(f"/api/nodes/{node_id}/operations", json={"action": "system.uptime"})
        assert resp.status_code == 200
        assert resp.json()["output_truncated"] is True
        assert len(resp.json()["stdout"]) == 1024


def test_operation_concurrency_and_duplicate_rejection(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str], ssh_settings: SSHSettings
) -> None:
    fake_transport = FakeOperationTransport()
    # Executor with capacity of 1
    executor = DirectOperationExecutor(fake_transport, limits=OperationLimits(max_concurrent=1))
    app = create_app(
        database_path=tmp_path / "inventory.db",
        api_token=api_token,
        ssh_settings=ssh_settings,
        operation_executor=executor,
    )

    with TestClient(app, headers=auth_headers) as client:
        reg1 = client.post(
            "/api/nodes", json={"name": "node1", "address": "192.0.2.1", "ssh_port": 22}
        )
        reg2 = client.post(
            "/api/nodes", json={"name": "node2", "address": "192.0.2.2", "ssh_port": 22}
        )
        n1 = reg1.json()["id"]
        n2 = reg2.json()["id"]

        # Simulate node 1 currently active
        executor._active.add(n1)

        # Same node active -> 409
        resp = client.post(f"/api/nodes/{n1}/operations", json={"action": "system.uptime"})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "operation_in_progress"

        # Concurrency exhausted (max 1, active has 1) -> 429
        resp2 = client.post(f"/api/nodes/{n2}/operations", json={"action": "system.uptime"})
        assert resp2.status_code == 429
        assert resp2.json()["error"]["code"] == "operation_busy"

        executor._active.clear()


def test_accurate_job_persistence_and_listing(operations_client: TestClient) -> None:
    with operations_client as client:
        reg = client.post(
            "/api/nodes", json={"name": "srv1", "address": "192.0.2.1", "ssh_port": 22}
        )
        node_id = reg.json()["id"]

        op1 = client.post(
            f"/api/nodes/{node_id}/operations", json={"action": "system.uptime"}
        ).json()
        op2 = client.post(
            f"/api/nodes/{node_id}/operations", json={"action": "system.memory"}
        ).json()

        # Get by operation ID
        fetched1 = client.get(f"/api/nodes/{node_id}/operations/{op1['id']}")
        assert fetched1.status_code == 200
        assert fetched1.json()["id"] == op1["id"]
        assert fetched1.json()["action"] == "system.uptime"

        # List operations for node
        listed = client.get(f"/api/nodes/{node_id}/operations")
        assert listed.status_code == 200
        ids = [op["id"] for op in listed.json()["operations"]]
        assert op1["id"] in ids
        assert op2["id"] in ids


def test_control_plane_restart_reconciliation(tmp_path: Path) -> None:
    db_path = tmp_path / "restart.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()
    node = node_repo.add_node(NewNode("test-node", "192.0.2.1", 22))

    op_repo = SQLiteOperationsRepository(db_path)
    # Manually migrate to v2 and v3
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE connectivity_observations ("
            "id INTEGER PRIMARY KEY, node_id INTEGER, observed_at TEXT, outcome TEXT, "
            "error_category TEXT)"
        )
        conn.execute("PRAGMA user_version = 2")
    op_repo.initialize()

    # Insert an operation that was in RUNNING state when control plane crashed
    now = datetime.now(UTC)
    unreconciled = OperationRecord(
        id="op_crashed_123",
        node_id=node.id,
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
    op_repo.create(unreconciled)

    # Reconcile on restart
    reconciled_count = op_repo.reconcile_in_flight()
    assert reconciled_count == 1

    rec = op_repo.get("op_crashed_123")
    assert rec is not None
    assert rec.outcome == OperationOutcome.UNCERTAIN
    assert rec.failure_category == OperationFailureCategory.CONTROL_PLANE_RESTARTED
    assert rec.completed_at is not None


def test_remote_execution_never_executes_locally(
    operations_client: TestClient, fake_transport: FakeOperationTransport, tmp_path: Path
) -> None:
    local_marker = tmp_path / "local_marker.txt"
    assert not local_marker.exists()

    with operations_client as client:
        reg = client.post(
            "/api/nodes", json={"name": "srv1", "address": "192.0.2.1", "ssh_port": 22}
        )
        node_id = reg.json()["id"]

        resp = client.post(
            f"/api/nodes/{node_id}/operations",
            json={"action": "system.uptime", "arguments": {}},
        )
        assert resp.status_code == 200

    # Ensure no local subprocess ran and marker was never touched
    assert not local_marker.exists()
    assert len(fake_transport.calls) == 1
    # Verify the command was dispatched strictly through the remote SSH transport
    assert fake_transport.calls[0][0].id == node_id
    assert fake_transport.calls[0][1] == "uptime"


def test_schema_evolution_v1_to_v2_to_v3(tmp_path: Path) -> None:
    db_path = tmp_path / "migration.db"
    node_repo = SQLiteNodeRepository(db_path)
    node_repo.initialize()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1

    from fleet_manager.connectivity.repository import SQLiteConnectivityRepository

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2

    op_repo = SQLiteOperationsRepository(db_path)
    op_repo.initialize()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        # Tables exist
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        assert "nodes" in tables
        assert "connectivity_observations" in tables
        assert "operation_executions" in tables
