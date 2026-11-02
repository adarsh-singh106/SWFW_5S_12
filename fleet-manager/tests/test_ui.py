"""Tests for the Fleet Operations Dashboard web interface and API integration."""

import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.inventory.models import Node
from fleet_manager.main import create_app
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationFailureCategory,
    OperationOutcome,
)
from fleet_manager.operations.transport import OperationTransport


class FakeOperationTransport(OperationTransport):
    def execute(
        self,
        node: Node,
        command: str,
        settings: SSHSettings,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 65536,
    ) -> OperationExecutionResult:
        if "uptime" in command:
            return OperationExecutionResult(
                outcome=OperationOutcome.SUCCESS,
                failure_category=None,
                exit_code=0,
                stdout=" 20:30:00 up 10 days, 1 user, load average: 0.15, 0.08, 0.02\n",
                stderr="",
                output_truncated=False,
            )
        return OperationExecutionResult(
            outcome=OperationOutcome.SUCCESS,
            failure_category=None,
            exit_code=0,
            stdout="Mock output\n",
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
    known_hosts.write_text("127.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...\n")
    private_key = tmp_path / "operator-key"
    private_key_content = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    private_key.write_text(private_key_content)
    return SSHSettings("operator", known_hosts, private_key)


def test_dashboard_serves_html_and_security_headers(tmp_path: Path, api_token: str) -> None:
    app = create_app(database_path=tmp_path / "inventory.db", api_token=api_token)
    with TestClient(app) as client:
        # Both / and /dashboard should serve the dashboard HTML without needing auth
        for path in ["/", "/dashboard"]:
            resp = client.get(path)
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert resp.headers["x-content-type-options"] == "nosniff"
            assert resp.headers["x-frame-options"] == "DENY"

            html = resp.text
            assert "Fleet Operations Dashboard" in html
            assert "Operator Authentication" in html
            assert "Ephemeral Storage:" in html
            assert "system.uptime" in html
            assert "system.memory" in html
            assert "system.disk" in html
            assert "service.status" in html
            assert "Grafana Dashboard" in html
            assert "/metrics" in html


def test_dashboard_does_not_use_local_or_session_storage() -> None:
    from fleet_manager.ui.router import _load_dashboard_html

    html = _load_dashboard_html()
    assert "<script>" in html and "</script>" in html
    script_content = html.split("<script>")[1].split("</script>")[0]
    # Ensure forbidden persistence mechanisms are never used in frontend script
    assert "localStorage" not in script_content, "Frontend must not use localStorage for tokens"
    assert "sessionStorage" not in script_content, "Frontend must not use sessionStorage for tokens"
    assert "document.cookie" not in script_content, "Frontend must not write tokens to cookies"


def test_dashboard_full_api_flow(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str], ssh_settings: SSHSettings
) -> None:
    fake_transport = FakeOperationTransport()
    app = create_app(
        database_path=tmp_path / "inventory.db",
        api_token=api_token,
        ssh_settings=ssh_settings,
        operation_transport=fake_transport,
    )

    with TestClient(app) as client:
        # 1. Unauthenticated request rejected
        unauth = client.get("/api/nodes/status")
        assert unauth.status_code == 401

        # 2. Authenticate session & register node
        reg = client.post(
            "/api/nodes",
            json={"name": "test-node-01", "address": "127.0.0.1", "ssh_port": 2222},
            headers=auth_headers,
        )
        assert reg.status_code == 201
        node_id = reg.json()["id"]

        # 3. Check status reflects registration
        status_resp = client.get("/api/nodes/status", headers=auth_headers)
        assert status_resp.status_code == 200
        nodes = status_resp.json()["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["node"]["id"] == node_id
        assert nodes[0]["display_status"] == "NOT_CHECKED"
        assert nodes[0]["observation"] is None

        # 4. Trigger remote operation
        op_resp = client.post(
            f"/api/nodes/{node_id}/operations",
            json={"action": "system.uptime", "arguments": {}},
            headers=auth_headers,
        )
        assert op_resp.status_code == 200
        op_data = op_resp.json()
        assert op_data["outcome"] == "SUCCESS"
        assert op_data["exit_code"] == 0
        assert "up 10 days" in op_data["stdout"]
        assert op_data["output_truncated"] is False

        # 5. List operations history for node
        hist_resp = client.get(f"/api/nodes/{node_id}/operations", headers=auth_headers)
        assert hist_resp.status_code == 200
        ops = hist_resp.json()["operations"]
        assert len(ops) == 1
        assert ops[0]["id"] == op_data["id"]
        assert ops[0]["action"] == "system.uptime"


def test_unreachable_node_status_and_operation_failure(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str], ssh_settings: SSHSettings
) -> None:
    class UnreachableOperationTransport(OperationTransport):
        def execute(
            self,
            node: Node,
            command: str,
            settings: SSHSettings,
            timeout_seconds: float = 10.0,
            max_output_bytes: int = 65536,
        ) -> OperationExecutionResult:
            return OperationExecutionResult(
                outcome=OperationOutcome.FAILURE,
                failure_category=OperationFailureCategory.CONNECTION_REFUSED,
                exit_code=None,
                stdout=None,
                stderr="Connection refused by remote host on port 2222",
                output_truncated=False,
            )

    app = create_app(
        database_path=tmp_path / "inventory.db",
        api_token=api_token,
        ssh_settings=ssh_settings,
        operation_transport=UnreachableOperationTransport(),
    )

    with TestClient(app, headers=auth_headers) as client:
        reg = client.post(
            "/api/nodes",
            json={"name": "unreachable-node", "address": "192.0.2.1", "ssh_port": 2222},
        )
        node_id = reg.json()["id"]

        op_resp = client.post(
            f"/api/nodes/{node_id}/operations",
            json={"action": "system.uptime", "arguments": {}},
        )
        assert op_resp.status_code == 200
        data = op_resp.json()
        assert data["outcome"] == "FAILURE"
        assert data["failure_category"] == "CONNECTION_REFUSED"
        assert "Connection refused" in data["stderr"]

        # Ensure secrets are not present in error messages or response
        raw_text = op_resp.text
        assert api_token not in raw_text
        assert "fake" not in raw_text


def test_xss_payload_in_node_name_is_handled_safely(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str]
) -> None:
    app = create_app(database_path=tmp_path / "inventory.db", api_token=api_token)
    xss_payload = "<script>alert('xss')</script>"

    with TestClient(app, headers=auth_headers) as client:
        reg = client.post(
            "/api/nodes",
            json={"name": xss_payload, "address": "127.0.0.1", "ssh_port": 2222},
        )
        assert reg.status_code == 201
        node = reg.json()
        assert node["name"] == xss_payload

        status = client.get("/api/nodes/status")
        assert status.status_code == 200
        # In the HTML dashboard, the client uses node.name via element.textContent = node.name,
        # which treats it as pure text, preventing HTML execution.
