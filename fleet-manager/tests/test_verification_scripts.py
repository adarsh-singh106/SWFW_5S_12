"""Windows-compatible tests for verification script safety, credentials, and lifecycle."""

from __future__ import annotations

import io
import json
import os
import socket
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from scripts import (
    setup_three_endpoints,
    smoke_test,
    verify_dashboard_live,
    verify_live_monitoring,
    verify_remote_operations,
)

from fleet_manager.operations.executor import DirectOperationExecutor
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationOutcome,
)
from fleet_manager.operations.transport import OperationTransport


# ---------------------------------------------------------------------------
# 1. Missing Token Configuration
# ---------------------------------------------------------------------------
def test_missing_token_configuration_live_monitoring(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_live_monitoring fails immediately when FLEET_MANAGER_API_TOKEN is missing."""
    monkeypatch.delenv("FLEET_MANAGER_API_TOKEN", raising=False)
    with pytest.raises(
        ValueError, match="Missing required environment variable 'FLEET_MANAGER_API_TOKEN'"
    ):
        verify_live_monitoring.get_api_token()

    # main() returns 1 when token is missing
    ret = verify_live_monitoring.main(argv=[])
    assert ret == 1


def test_missing_token_configuration_smoke_test_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """smoke_test refuses live execution when FLEET_MANAGER_API_TOKEN is missing."""
    monkeypatch.delenv("FLEET_MANAGER_API_TOKEN", raising=False)
    ret = smoke_test.run_smoke_test(base_url="http://127.0.0.1:8000")
    assert ret == 1


# ---------------------------------------------------------------------------
# 2. Token Retrieval Without Logging or Echoing
# ---------------------------------------------------------------------------
def test_token_retrieval_without_logging_or_echoing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tokens are retrieved from env and never echoed in HTTP error diagnostics."""
    secret_token = "SUPER_SECRET_TOKEN_DO_NOT_LEAK_987654321"
    monkeypatch.setenv("FLEET_MANAGER_API_TOKEN", secret_token)

    retrieved = verify_live_monitoring.get_api_token()
    assert retrieved == secret_token

    # Verify stdout/stderr do not contain token
    captured = capsys.readouterr()
    assert secret_token not in captured.out
    assert secret_token not in captured.err

    # Verify HTTP error sanitization does not echo Authorization header or token
    fake_error = urllib.error.HTTPError(
        url="http://127.0.0.1:8000/api/nodes",
        code=401,
        msg="Unauthorized",
        hdrs=MagicMock(),
        fp=io.BytesIO(b'{"detail":"Invalid bearer token"}'),
    )

    with patch("urllib.request.urlopen", side_effect=fake_error):
        with pytest.raises(RuntimeError) as exc_info:
            verify_live_monitoring.fm_request(
                base_url="http://127.0.0.1:8000",
                path="/api/nodes",
                token=secret_token,
            )
        err_msg = str(exc_info.value)
        assert secret_token not in err_msg
        assert "Authorization" not in err_msg
        assert "Bearer" not in err_msg
        assert "HTTP error 401 accessing Fleet Manager endpoint /api/nodes" in err_msg


def test_grafana_auth_rejects_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Grafana authentication fails when environment variables are missing."""
    monkeypatch.delenv("GRAFANA_USER", raising=False)
    monkeypatch.delenv("GRAFANA_PASSWORD", raising=False)
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)
    with pytest.raises(
        ValueError, match="Grafana authentication requires environment configuration"
    ):
        verify_live_monitoring.get_grafana_auth_header()


def test_grafana_auth_rejects_default_admin_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Grafana authentication strictly rejects default admin/admin credentials."""
    monkeypatch.setenv("GRAFANA_USER", "admin")
    monkeypatch.setenv("GRAFANA_PASSWORD", "admin")
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)
    with pytest.raises(
        ValueError, match="Known default credentials \\(admin/admin\\) are rejected"
    ):
        verify_live_monitoring.get_grafana_auth_header()


def test_grafana_auth_accepts_custom_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Grafana authentication accepts valid distinct credentials or tokens."""
    monkeypatch.setenv("GRAFANA_USER", "ops_engineer")
    monkeypatch.setenv("GRAFANA_PASSWORD", "StrongP@ssw0rd99!")
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)
    header = verify_live_monitoring.get_grafana_auth_header()
    assert header.startswith("Basic ")

    monkeypatch.setenv("GRAFANA_TOKEN", "glsa_my_custom_token")
    token_header = verify_live_monitoring.get_grafana_auth_header()
    assert token_header == "Bearer glsa_my_custom_token"


# ---------------------------------------------------------------------------
# 3. Default Read-Only Script Behavior
# ---------------------------------------------------------------------------
def test_smoke_test_default_read_only_on_live_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """smoke_test does not POST nodes against live servers by default."""
    monkeypatch.setenv("FLEET_MANAGER_API_TOKEN", "valid-test-token")

    mock_client = MagicMock()
    mock_metrics = MagicMock(
        status_code=200, text="fleet_connectivity_checks_total fleet_nodes_by_status"
    )
    mock_dash = MagicMock(
        status_code=200,
        headers={"x-content-type-options": "nosniff", "x-frame-options": "DENY"},
        text="Fleet Operations Dashboard",
    )
    mock_unauth = MagicMock(status_code=401, headers={"www-authenticate": "Bearer"})
    mock_nodes_list = MagicMock(status_code=200, json=lambda: {"nodes": []})
    mock_status = MagicMock(status_code=200, json=lambda: {"nodes": []})

    def mock_get(url: str, **kwargs):
        if url == "/metrics":
            return mock_metrics
        if url == "/dashboard":
            return mock_dash
        if url == "/api/nodes":
            headers = kwargs.get("headers", {})
            auth = headers.get("Authorization", "")
            if not auth or "invalid-token" in auth:
                return mock_unauth
            return mock_nodes_list
        if url == "/api/nodes/status":
            return mock_status
        return MagicMock(status_code=404)

    mock_client.get.side_effect = mock_get

    with patch("httpx.Client", return_value=mock_client):
        ret = smoke_test.run_smoke_test(
            base_url="http://127.0.0.1:8000",
            allow_live_mutation=False,
        )
        assert ret == 0

        # Assert client.post was NEVER called for node registration
        for call in mock_client.post.call_args_list:
            assert call[0][0] != "/api/nodes", (
                "POST /api/nodes must not be called in read-only mode"
            )


def test_verify_live_monitoring_read_only_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_live_monitoring does not register nodes or trigger checks by default."""
    monkeypatch.setenv("FLEET_MANAGER_API_TOKEN", "test-token")

    with (
        patch("scripts.verify_live_monitoring.fm_request") as mock_fm_req,
        patch("scripts.verify_live_monitoring.prom_query", return_value=[]),
        patch("scripts.verify_live_monitoring.grafana_get") as mock_grafana,
        patch("time.sleep"),
    ):
        mock_fm_req.return_value = {"nodes": []}
        mock_grafana.side_effect = [
            {
                "name": "Prometheus",
                "uid": "prom-1",
                "type": "prometheus",
                "url": "http://127.0.0.1:9090",
            },
            {"status": "OK", "message": "Datasource is working"},
            {"dashboard": {"title": "Fleet Overview", "version": 1, "panels": []}},
        ]

        ret = verify_live_monitoring.main(
            argv=["--fm-url", "http://127.0.0.1:8000", "--prom-url", "http://127.0.0.1:9090"]
        )
        assert ret == 0

        # Verify no POST requests were issued
        for call in mock_fm_req.call_args_list:
            method = call[1].get("method", "GET")
            assert method == "GET", f"Expected only GET requests, got {method}"


# ---------------------------------------------------------------------------
# 4. Explicit Live-Mutation Opt-In
# ---------------------------------------------------------------------------
def test_smoke_test_explicit_live_mutation_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """smoke_test allows node POST on live server only when both flags are provided."""
    monkeypatch.setenv("FLEET_MANAGER_API_TOKEN", "valid-test-token")

    mock_client = MagicMock()
    mock_metrics = MagicMock(
        status_code=200, text="fleet_connectivity_checks_total fleet_nodes_by_status"
    )
    mock_dash = MagicMock(
        status_code=200,
        headers={"x-content-type-options": "nosniff", "x-frame-options": "DENY"},
        text="Fleet Operations Dashboard",
    )
    mock_unauth = MagicMock(status_code=401, headers={"www-authenticate": "Bearer"})
    mock_nodes_list = MagicMock(status_code=200, json=lambda: {"nodes": [{"id": 42}]})
    mock_status = MagicMock(
        status_code=200,
        json=lambda: {"nodes": [{"node": {"id": 42}, "display_status": "NOT_CHECKED"}]},
    )

    def mock_get(url: str, **kwargs):
        if url == "/metrics":
            return mock_metrics
        if url == "/dashboard":
            return mock_dash
        if url == "/api/nodes":
            headers = kwargs.get("headers", {})
            auth = headers.get("Authorization", "")
            if not auth or "invalid-token" in auth:
                return mock_unauth
            return mock_nodes_list
        if url == "/api/nodes/status":
            return mock_status
        return MagicMock(status_code=404)

    mock_client.get.side_effect = mock_get
    mock_client.post.return_value = MagicMock(status_code=201, json=lambda: {"id": 42})

    with patch("httpx.Client", return_value=mock_client):
        ret = smoke_test.run_smoke_test(
            base_url="http://127.0.0.1:8000",
            allow_live_mutation=True,
            isolated_test_env=True,
        )
        assert ret == 0
        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0] == "/api/nodes"


# ---------------------------------------------------------------------------
# 5. Missing Live-Mutation Permission
# ---------------------------------------------------------------------------
def test_smoke_test_refuses_live_mutation_without_isolated_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """smoke_test rejects live mutation without isolated environment confirmation."""
    monkeypatch.setenv("FLEET_MANAGER_API_TOKEN", "valid-test-token")

    mock_client = MagicMock()
    mock_metrics = MagicMock(
        status_code=200, text="fleet_connectivity_checks_total fleet_nodes_by_status"
    )
    mock_dash = MagicMock(
        status_code=200,
        headers={"x-content-type-options": "nosniff", "x-frame-options": "DENY"},
        text="Fleet Operations Dashboard",
    )
    mock_unauth = MagicMock(status_code=401, headers={"www-authenticate": "Bearer"})

    def mock_get(url: str, **kwargs):
        if url == "/metrics":
            return mock_metrics
        if url == "/dashboard":
            return mock_dash
        if url == "/api/nodes":
            return mock_unauth
        return MagicMock(status_code=404)

    mock_client.get.side_effect = mock_get

    with patch("httpx.Client", return_value=mock_client):
        ret = smoke_test.run_smoke_test(
            base_url="http://127.0.0.1:8000",
            allow_live_mutation=True,
            isolated_test_env=False,
        )
        assert ret == 1
        err = capsys.readouterr().err
        assert "Refusing persistent live mutation: Fleet Manager has no safe deletion API" in err


# ---------------------------------------------------------------------------
# 6. HTTP Timeout Behavior
# ---------------------------------------------------------------------------
def test_http_timeout_behavior_in_monitoring() -> None:
    """Verify bounded HTTP timeouts in verify_live_monitoring."""
    assert verify_live_monitoring.DEFAULT_HTTP_TIMEOUT_SECONDS == 5.0
    assert verify_dashboard_live.HTTP_TIMEOUT_SECONDS == 5.0

    # Ensure timeout error from urlopen raises sanitized RuntimeError
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("timed out"),
    ):
        with pytest.raises(RuntimeError, match="Network error accessing Fleet Manager endpoint"):
            verify_live_monitoring.fm_request(
                base_url="http://127.0.0.1:8000",
                path="/api/nodes",
                token="test-token",
            )


# ---------------------------------------------------------------------------
# 7. Service Restart Prevention by Default
# ---------------------------------------------------------------------------
def test_service_restart_prevention_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    """verify_service_restart does not invoke systemctl or restart services by default."""
    with patch("subprocess.run") as mock_subproc:
        verify_live_monitoring.verify_service_restart(
            allow_service_restart=False,
            prom_url="http://127.0.0.1:9090",
        )
        mock_subproc.assert_not_called()
        out = capsys.readouterr().out
        assert "Service restart test disabled by default (read-only mode)" in out


# ---------------------------------------------------------------------------
# 8. Endpoint PID Ownership and Cleanup
# ---------------------------------------------------------------------------
def test_endpoint_pid_ownership_and_cleanup(tmp_path: Path) -> None:
    """setup_three_endpoints terminates owned processes and cleans up PID files."""
    base_dir = tmp_path / "fleet_three_endpoints"
    pids_dir = base_dir / "pids"
    pids_dir.mkdir(parents=True, exist_ok=True)

    marker = base_dir / ".fleet_managed"
    marker.write_text(json.dumps({"managed_by": "setup_three_endpoints.py"}), encoding="utf-8")

    # Write dummy PID files
    sshd_pid_file = pids_dir / "sshd_endpoint-alpha.pid"
    sshd_pid_file.write_text("12345\n", encoding="ascii")
    exp_pid_file = pids_dir / "exporter_endpoint-alpha.pid"
    exp_pid_file.write_text("12346\n", encoding="ascii")

    killed_pids: list[int] = []

    def mock_kill(pid: int, sig: int):
        killed_pids.append(pid)

    with (
        patch("scripts.setup_three_endpoints.is_process_owned", return_value=True),
        patch("os.kill", side_effect=mock_kill),
        patch("time.sleep"),
    ):
        ret = setup_three_endpoints.stop(
            base_dir=base_dir,
            targets_path=tmp_path / "targets.json",
            backup_path=tmp_path / "backup.json",
        )
        assert ret == 0
        assert 12345 in killed_pids
        assert 12346 in killed_pids
        assert not base_dir.exists()


# ---------------------------------------------------------------------------
# 9. Partial Endpoint Startup Rollback
# ---------------------------------------------------------------------------
def test_partial_endpoint_startup_rollback(tmp_path: Path) -> None:
    """setup_three_endpoints rolls back partially started resources on failure."""
    base_dir = tmp_path / "fleet_three_endpoints"
    targets_file = tmp_path / "targets.json"
    targets_file.write_text("[]", encoding="utf-8")
    backup_file = tmp_path / "targets.json.fleet_orig"

    with (
        patch("scripts.setup_three_endpoints.check_port_conflicts", return_value=[]),
        patch("scripts.setup_three_endpoints.is_setup_active", return_value=False),
        patch(
            "scripts.setup_three_endpoints._run_cmd",
            side_effect=RuntimeError("ssh-keygen failed"),
        ),
    ):
        ret = setup_three_endpoints.start(
            base_dir=base_dir,
            targets_path=targets_file,
            backup_path=backup_file,
        )
        assert ret == 1
        # Directory should have been cleaned up by rollback
        assert not base_dir.exists()


# ---------------------------------------------------------------------------
# 10. Port Conflict Detection
# ---------------------------------------------------------------------------
def test_port_conflict_detection(tmp_path: Path) -> None:
    """setup_three_endpoints aborts before starting if any port is already bound."""
    with patch("scripts.setup_three_endpoints.check_port_conflicts", return_value=[2201]):
        ret = setup_three_endpoints.start(
            base_dir=tmp_path / "fleet_three_endpoints",
            targets_path=tmp_path / "targets.json",
            backup_path=tmp_path / "backup.json",
        )
        assert ret == 1


def test_real_port_conflict_detection_helper() -> None:
    """check_port_conflicts identifies real bound listening sockets."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    bound_port = s.getsockname()[1]

    try:
        endpoints = [{"name": "test-ep", "ssh_port": bound_port, "exporter_port": 9999}]
        conflicts = setup_three_endpoints.check_port_conflicts(endpoints)
        assert bound_port in conflicts
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 11. Safe Handling of Temporary Prometheus Configuration
# ---------------------------------------------------------------------------
def test_safe_handling_of_temporary_prometheus_configuration(tmp_path: Path) -> None:
    """setup_three_endpoints backs up targets.json and restores it cleanly on teardown."""
    base_dir = tmp_path / "fleet_three_endpoints"
    targets_file = tmp_path / "targets.json"
    backup_file = tmp_path / "targets.json.fleet_orig"

    original_targets_content = json.dumps([{"targets": ["127.0.0.1:9100"]}])
    targets_file.write_text(original_targets_content, encoding="utf-8")

    def mock_run_cmd(cmd: list[str], timeout: float = 10.0) -> str:
        if cmd[0] == "ssh-keygen" and "-f" in cmd:
            key_path = Path(cmd[cmd.index("-f") + 1])
            key_path.write_text("dummy-private-key\n")
            Path(f"{key_path}.pub").write_text(
                "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... observer\n"
            )
        return ""

    # Simulate start backing up targets.json
    with (
        patch("scripts.setup_three_endpoints.check_port_conflicts", return_value=[]),
        patch("scripts.setup_three_endpoints.is_setup_active", return_value=False),
        patch("scripts.setup_three_endpoints._run_cmd", side_effect=mock_run_cmd),
        patch("subprocess.run"),
        patch("subprocess.Popen"),
    ):
        ret = setup_three_endpoints.start(
            base_dir=base_dir,
            targets_path=targets_file,
            backup_path=backup_file,
        )
        assert ret == 0
        assert backup_file.exists()
        assert backup_file.read_text(encoding="utf-8") == original_targets_content
        assert targets_file.read_text(encoding="utf-8") != original_targets_content

    # Simulate stop restoring targets.json
    with (
        patch("scripts.setup_three_endpoints.is_process_owned", return_value=True),
        patch("time.sleep"),
    ):
        ret = setup_three_endpoints.stop(
            base_dir=base_dir,
            targets_path=targets_file,
            backup_path=backup_file,
        )
        assert ret == 0
        assert targets_file.read_text(encoding="utf-8") == original_targets_content
        assert not backup_file.exists()


# ---------------------------------------------------------------------------
# 12. No Unrelated Process Termination
# ---------------------------------------------------------------------------
def test_no_unrelated_process_termination(tmp_path: Path) -> None:
    """setup_three_endpoints does not terminate an unrelated process if PID is recycled."""
    base_dir = tmp_path / "fleet_three_endpoints"
    pids_dir = base_dir / "pids"
    pids_dir.mkdir(parents=True, exist_ok=True)

    marker = base_dir / ".fleet_managed"
    marker.write_text(json.dumps({"managed_by": "setup_three_endpoints.py"}), encoding="utf-8")

    unrelated_pid = os.getpid()
    sshd_pid_file = pids_dir / "sshd_endpoint-alpha.pid"
    sshd_pid_file.write_text(str(unrelated_pid), encoding="ascii")

    killed_pids: list[int] = []

    def mock_kill(pid: int, sig: int):
        killed_pids.append(pid)

    with (
        patch("scripts.setup_three_endpoints.is_process_owned", return_value=False),
        patch("scripts.setup_three_endpoints.is_pid_alive", return_value=True),
        patch("os.kill", side_effect=mock_kill),
        patch("time.sleep"),
    ):
        ret = setup_three_endpoints.stop(
            base_dir=base_dir,
            targets_path=tmp_path / "targets.json",
            backup_path=tmp_path / "backup.json",
        )
        assert ret == 0
        assert unrelated_pid not in killed_pids


# ---------------------------------------------------------------------------
# Mock transport for remote operations verification
# ---------------------------------------------------------------------------
class MockTestTransport(OperationTransport):
    def execute(self, node, command, settings, timeout_seconds=10.0, max_output_bytes=65536):
        cmd = str(command)
        if "uptime" in cmd:
            out = " 22:00:00 up 10 days, 2 users, load average: 0.05, 0.03, 0.00\n"
        elif "free" in cmd:
            out = (
                "              total        used        free      shared  buff/cache   available\n"
                "Mem:        8192000     2048000     4096000      102400     2048000     5896000\n"
            )
        elif "df" in cmd:
            out = (
                "Filesystem     1K-blocks      Used Available Use% Mounted on\n"
                "/dev/sda1       61255492  12456789  45678901  22% /\n"
            )
        elif "systemctl" in cmd:
            out = (
                "● ssh.service - OpenBSD Secure Shell server\n"
                "   Loaded: loaded (/lib/systemd/system/ssh.service; enabled)\n"
                "   Active: active (running)\n"
            )
        else:
            out = "mock output\n"

        return OperationExecutionResult(
            outcome=OperationOutcome.SUCCESS,
            failure_category=None,
            exit_code=0,
            stdout=out,
            stderr="",
            output_truncated=False,
        )


def test_verify_remote_operations_runs_safely() -> None:
    """verify_remote_operations executes cleanly with mocked executor and cleans up."""
    mock_executor = DirectOperationExecutor(MockTestTransport())
    success = verify_remote_operations.run_verification(operation_executor=mock_executor)
    assert success is True
