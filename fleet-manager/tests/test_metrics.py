"""Tests for Prometheus control-plane metrics endpoint and exposition format."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.main import create_app


class MutableTransport:
    outcome = ConnectivityOutcome.CONNECTED

    def verify(self, _node: object, _settings: object) -> ConnectivityOutcome:
        return self.outcome


@pytest.fixture
def metrics_client(tmp_path: Path, api_token: str) -> Iterator[TestClient]:
    db = tmp_path / "inventory.db"
    transport = MutableTransport()
    app = create_app(
        db,
        api_token=api_token,
        ssh_transport=transport,
        ssh_settings=SSHSettings("observer", tmp_path / "hosts", tmp_path / "key"),
    )
    with TestClient(app) as client:
        yield client


def test_metrics_endpoint_unauthenticated_and_openmetrics_format(
    metrics_client: TestClient,
) -> None:
    # Prometheus scrape should succeed without bearer token
    res = metrics_client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    assert "version=0.0.4" in res.headers["content-type"]

    body = res.text
    # Verify standard header comments
    assert "# HELP fleet_connectivity_checks_total" in body
    assert "# TYPE fleet_connectivity_checks_total counter" in body
    assert "# HELP fleet_connectivity_active_checks" in body
    assert "# TYPE fleet_connectivity_active_checks gauge" in body
    assert "# HELP fleet_connectivity_max_concurrent" in body
    assert "# TYPE fleet_connectivity_max_concurrent gauge" in body
    assert "# HELP fleet_scheduler_running" in body
    assert "# TYPE fleet_scheduler_running gauge" in body
    assert "# HELP fleet_nodes_by_status" in body
    assert "# TYPE fleet_nodes_by_status gauge" in body

    # Verify trailing newline per Prometheus spec
    assert body.endswith("\n")


def test_metrics_bounded_label_cardinality(metrics_client: TestClient) -> None:
    res = metrics_client.get("/metrics")
    assert res.status_code == 200
    body = res.text

    # Verify no raw passwords, keys, tokens, or arbitrary address leaks in label keys
    allowed_label_keys = {"outcome", "status", "reason", "le", "collector", "action"}
    for line in body.splitlines():
        if line.startswith("#") or "{" not in line:
            continue
        label_part = line[line.find("{") + 1 : line.find("}")]
        for item in label_part.split(","):
            if not item:
                continue
            k = item.split("=")[0].strip()
            assert k in allowed_label_keys, f"Disallowed label key found: {k}"


def test_metrics_updates_with_node_and_checks(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str]
) -> None:
    db = tmp_path / "inventory.db"
    transport = MutableTransport()
    app = create_app(
        db,
        api_token=api_token,
        ssh_transport=transport,
        ssh_settings=SSHSettings("observer", tmp_path / "hosts", tmp_path / "key"),
    )
    with TestClient(app) as client:
        # Initial: no nodes
        res1 = client.get("/metrics")
        assert 'fleet_nodes_by_status{status="NOT_CHECKED"} 0' in res1.text

        # Register a node
        created = client.post(
            "/api/nodes", json={"name": "test-node", "address": "10.0.0.1"}, headers=auth_headers
        ).json()
        node_id = created["id"]

        # Status gauge should reflect NOT_CHECKED = 1
        res2 = client.get("/metrics")
        assert 'fleet_nodes_by_status{status="NOT_CHECKED"} 1.0' in res2.text
        assert 'fleet_nodes_by_status{status="REACHABLE"} 0.0' in res2.text

        # Run check
        transport.outcome = ConnectivityOutcome.CONNECTED
        check_res = client.post(f"/api/nodes/{node_id}/connectivity-check", headers=auth_headers)
        assert check_res.status_code == 200

        # Now metrics should record CONNECTED outcome and REACHABLE status
        res3 = client.get("/metrics")
        assert 'fleet_connectivity_checks_total{outcome="CONNECTED"} 1.0' in res3.text
        assert (
            'fleet_connectivity_check_duration_seconds_count{outcome="CONNECTED"} 1.0' in res3.text
        )
        assert 'fleet_nodes_by_status{status="REACHABLE"} 1.0' in res3.text
        assert 'fleet_nodes_by_status{status="NOT_CHECKED"} 0.0' in res3.text
