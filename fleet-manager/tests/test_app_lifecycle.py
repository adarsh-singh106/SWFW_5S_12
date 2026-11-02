"""Tests for application composition, lifecycle hardening, health probes, and API contracts."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from fleet_manager.config import MonitoringSettings, SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.scheduler import ConnectivityScheduler
from fleet_manager.errors import StorageError
from fleet_manager.inventory.models import Node
from fleet_manager.main import create_app
from fleet_manager.metrics.telemetry import Telemetry


class DummyTransport:
    def verify(self, _node: Node, _settings: SSHSettings) -> ConnectivityOutcome:
        return ConnectivityOutcome.CONNECTED


@pytest.fixture
def base_app(tmp_path: Path, api_token: str) -> Iterator[tuple[TestClient, Path, Telemetry]]:
    db = tmp_path / "fleet.db"
    transport = DummyTransport()
    settings = SSHSettings("observer", tmp_path / "hosts", tmp_path / "key")
    monitoring = MonitoringSettings(
        enabled=True,
        polling_interval_seconds=60.0,
        observation_ttl_seconds=180,
        jitter_ratio=0.1,
    )
    app = create_app(
        database_path=db,
        api_token=api_token,
        ssh_transport=transport,
        ssh_settings=settings,
        monitoring_settings=monitoring,
    )
    with TestClient(app) as client:
        telemetry = client.app.state.telemetry
        yield client, db, telemetry


def test_import_and_factory_smoke() -> None:
    """Application module can be imported and factory instantiates a valid app."""
    from fleet_manager.main import app
    from fleet_manager.main import create_app as factory

    assert app is not None
    instance = factory()
    assert instance.title == "Fleet Manager Inventory API"


def test_shared_telemetry_instance_identity(
    base_app: tuple[TestClient, Path, Telemetry],
) -> None:
    """Verify that a single Telemetry instance is shared across all services and scheduler."""
    client, _, telemetry = base_app
    app = client.app

    assert app.state.telemetry is telemetry
    assert app.state.connectivity_service.telemetry is telemetry
    assert app.state.operation_service.telemetry is telemetry
    assert app.state.connectivity_scheduler.telemetry is telemetry


def test_healthz_liveness_probe_is_public(base_app: tuple[TestClient, Path, Telemetry]) -> None:
    """Liveness probe /healthz returns 200 without authentication or DB interaction."""
    client, _, _ = base_app
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    # Verify no credentials or internal details in headers or body
    assert "Authorization" not in res.headers
    assert "token" not in res.text.lower()


def test_readyz_readiness_probe_lifecycle_and_failure(tmp_path: Path, api_token: str) -> None:
    """Readiness probe /readyz accurately reflects startup, storage health, and shutdown."""
    db = tmp_path / "readyz_test.db"
    transport = DummyTransport()
    settings = SSHSettings("observer", tmp_path / "hosts", tmp_path / "key")

    app = create_app(
        database_path=db,
        api_token=api_token,
        ssh_transport=transport,
        ssh_settings=settings,
    )

    # 1. Before lifespan starts: state.is_ready is False -> 503
    unstarted_client = TestClient(app, raise_server_exceptions=False)
    unstarted_res = unstarted_client.get("/readyz")
    assert unstarted_res.status_code == 503
    assert unstarted_res.json() == {"status": "not_ready"}

    # 2. Inside lifespan: initialized storage -> 200
    with TestClient(app) as client:
        res = client.get("/readyz")
        assert res.status_code == 200
        assert res.json() == {"status": "ready"}

        # 3. Simulate database failure during runtime
        app.state.inventory_repository.check_ready = MagicMock(
            side_effect=StorageError("Simulated disk error")
        )
        fail_res = client.get("/readyz")
        assert fail_res.status_code == 503
        assert fail_res.json() == {"status": "not_ready"}
        # Ensure error message does not leak internal details
        assert "Simulated disk error" not in fail_res.text

    # 4. After lifespan exits (shutdown): state.is_ready is reset to False -> 503
    post_shutdown_res = unstarted_client.get("/readyz")
    assert post_shutdown_res.status_code == 503
    assert post_shutdown_res.json() == {"status": "not_ready"}


def test_public_vs_authenticated_endpoints(
    base_app: tuple[TestClient, Path, Telemetry], api_token: str
) -> None:
    """Public endpoints allow unauthenticated access; protected routes require bearer token."""
    client, _, _ = base_app

    # Public routes
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/metrics").status_code == 200
    assert client.get("/dashboard").status_code == 200
    assert client.get("/").status_code == 200

    # Protected routes: unauthenticated must be 401
    protected_paths = [
        ("GET", "/api/nodes"),
        ("POST", "/api/nodes"),
        ("GET", "/api/nodes/status"),
        ("POST", "/api/nodes/1/connectivity-check"),
        ("GET", "/api/nodes/1/connectivity"),
        ("GET", "/api/nodes/1/operations"),
        ("POST", "/api/nodes/1/operations"),
        ("GET", "/api/nodes/1/operations/op-123"),
    ]
    for method, path in protected_paths:
        res = getattr(client, method.lower())(path)
        assert res.status_code == 401, f"Expected 401 for unauthenticated {method} {path}"
        assert res.headers["www-authenticate"] == "Bearer"
        assert res.json() == {
            "error": {"code": "unauthorized", "message": "Authentication required"}
        }

    # Authenticated access succeeds
    auth_headers = {"Authorization": f"Bearer {api_token}"}
    res_auth = client.get("/api/nodes", headers=auth_headers)
    assert res_auth.status_code == 200


def test_scheduler_metrics_appear_in_exposition_after_events(
    base_app: tuple[TestClient, Path, Telemetry],
) -> None:
    """Scheduler metrics are correctly typed, updated by scheduler events, and exposed."""
    client, _, telemetry = base_app

    # Initial state: scheduler is running
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "fleet_scheduler_running 1.0" in res.text
    assert "fleet_scheduler_cycles_total 0.0" in res.text

    # Record scheduler events
    telemetry.scheduler_cycles_total.inc(2)
    telemetry.scheduler_checks_skipped_total.inc(1, labels={"reason": "capacity_busy"})
    telemetry.scheduler_errors_total.inc(1, labels={"reason": "storage_error"})

    updated_res = client.get("/metrics")
    assert updated_res.status_code == 200
    assert "fleet_scheduler_cycles_total 2.0" in updated_res.text
    assert 'fleet_scheduler_checks_skipped_total{reason="capacity_busy"} 1.0' in updated_res.text
    assert 'fleet_scheduler_errors_total{reason="storage_error"} 1.0' in updated_res.text


def test_scheduler_cannot_start_twice(base_app: tuple[TestClient, Path, Telemetry]) -> None:
    """ConnectivityScheduler enforces single-runner invariant and cannot start twice."""
    client, _, _ = base_app
    scheduler: ConnectivityScheduler = client.app.state.connectivity_scheduler

    assert scheduler.is_running
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            loop.run_until_complete(scheduler.start())
    finally:
        loop.close()


def test_startup_failure_cleanup(tmp_path: Path, api_token: str) -> None:
    """Partial startup failure cleanly shuts down previously allocated resources."""
    db = tmp_path / "fail_db.db"
    settings = SSHSettings("observer", tmp_path / "hosts", tmp_path / "key")

    mock_executor = MagicMock()
    mock_executor.close = MagicMock()

    monitoring = MonitoringSettings(
        enabled=True,
        polling_interval_seconds=60.0,
        observation_ttl_seconds=180,
    )

    app = create_app(
        database_path=db,
        api_token=api_token,
        ssh_executor=mock_executor,
        ssh_settings=settings,
        monitoring_settings=monitoring,
    )

    # Simulate scheduler startup failure occurring after executor allocation
    with patch.object(
        ConnectivityScheduler,
        "start",
        side_effect=RuntimeError("Simulated scheduler startup error"),
    ):
        with pytest.raises(RuntimeError, match="Simulated scheduler startup error"):
            with TestClient(app):
                pass

    # Ensure executor.close() was called in finally
    mock_executor.close.assert_called_once()
    assert app.state.is_ready is False


def test_repeated_app_lifespan_lifecycle(tmp_path: Path, api_token: str) -> None:
    """Repeated startup and shutdown lifespans do not leak scheduler tasks or metrics."""
    db = tmp_path / "repeated.db"
    transport = DummyTransport()
    settings = SSHSettings("observer", tmp_path / "hosts", tmp_path / "key")
    monitoring = MonitoringSettings(
        enabled=True,
        polling_interval_seconds=60.0,
        observation_ttl_seconds=180,
    )

    app = create_app(
        database_path=db,
        api_token=api_token,
        ssh_transport=transport,
        ssh_settings=settings,
        monitoring_settings=monitoring,
    )

    # First lifespan run
    with TestClient(app) as client1:
        assert client1.app.state.is_ready is True
        assert client1.app.state.connectivity_scheduler.is_running is True
        res = client1.get("/healthz")
        assert res.status_code == 200

    assert app.state.is_ready is False
    assert app.state.connectivity_scheduler.is_running is False

    # Second lifespan run
    with TestClient(app) as client2:
        assert client2.app.state.is_ready is True
        assert client2.app.state.connectivity_scheduler.is_running is True
        res = client2.get("/readyz")
        assert res.status_code == 200

    assert app.state.is_ready is False
    assert app.state.connectivity_scheduler.is_running is False


def test_openapi_security_scheme_and_error_responses() -> None:
    """OpenAPI schema correctly documents security schemes, protected routes, and errors."""
    app = create_app()
    schema = app.openapi()

    # Bearer security scheme definition
    security_schemes = schema.get("components", {}).get("securitySchemes", {})
    assert "OperatorToken" in security_schemes
    scheme_def = security_schemes["OperatorToken"]
    assert scheme_def["type"] == "http"
    assert scheme_def["scheme"] == "bearer"

    # Verify public endpoints declare no security
    public_paths = ["/healthz", "/readyz", "/metrics", "/dashboard", "/"]
    for path in public_paths:
        path_item = schema["paths"].get(path, {})
        for method, operation in path_item.items():
            assert operation.get("security") is None, f"{method} {path} should be public"

    # Verify protected endpoints declare OperatorToken security
    protected_prefixes = ["/api/nodes"]
    for path, path_item in schema["paths"].items():
        if any(path.startswith(p) for p in protected_prefixes):
            for method, operation in path_item.items():
                sec = operation.get("security")
                assert sec == [{"OperatorToken": []}], f"{method} {path} must require OperatorToken"

    # Verify no raw validation schemas or tokens in components
    schemas = schema.get("components", {}).get("schemas", {})
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas
    assert "ErrorResponse" in schemas
