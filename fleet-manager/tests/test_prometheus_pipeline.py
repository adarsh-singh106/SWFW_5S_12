"""Integration tests for the Prometheus metrics pipeline and scrape behavior."""

from pathlib import Path

from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.main import create_app


class FakeTransport:
    def __init__(self, outcome: ConnectivityOutcome = ConnectivityOutcome.CONNECTED) -> None:
        self.outcome = outcome

    def verify(self, _node: object, _settings: object) -> ConnectivityOutcome:
        return self.outcome


def test_metrics_pipeline_end_to_end(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str]
) -> None:
    db = tmp_path / "inventory.db"
    hosts = tmp_path / "known_hosts"
    hosts.write_text("10.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...\n")
    key = tmp_path / "id_ed25519"
    key.write_text("dummy-key")
    settings = SSHSettings("observer", hosts, key)
    transport = FakeTransport(ConnectivityOutcome.AUTH_FAILED)

    app = create_app(
        db,
        api_token=api_token,
        ssh_transport=transport,
        ssh_settings=settings,
    )

    with TestClient(app) as client:
        # 1. Scrape initial metrics without token
        initial_scrape = client.get("/metrics")
        assert initial_scrape.status_code == 200
        text = initial_scrape.text
        assert 'fleet_connectivity_checks_total{outcome="AUTH_FAILED"} 0.0' in text
        assert 'fleet_connectivity_checks_total{outcome="CONNECTED"} 0.0' in text
        assert "fleet_connectivity_max_concurrent 4.0" in text
        assert "fleet_connectivity_active_checks 0.0" in text
        assert "fleet_scheduler_running 1.0" in text

        # 2. Register two nodes
        n1 = client.post(
            "/api/nodes", json={"name": "node-1", "address": "10.0.0.1"}, headers=auth_headers
        ).json()["id"]
        n2 = client.post(
            "/api/nodes", json={"name": "node-2", "address": "10.0.0.2"}, headers=auth_headers
        ).json()["id"]

        after_reg = client.get("/metrics").text
        assert 'fleet_nodes_by_status{status="NOT_CHECKED"} 2.0' in after_reg
        assert 'fleet_nodes_by_status{status="REACHABLE"} 0.0' in after_reg

        # 3. Check node 1 (will fail with AUTH_FAILED)
        client.post(f"/api/nodes/{n1}/connectivity-check", headers=auth_headers)

        after_check1 = client.get("/metrics").text
        assert 'fleet_connectivity_checks_total{outcome="AUTH_FAILED"} 1.0' in after_check1
        assert 'fleet_connectivity_checks_total{outcome="CONNECTED"} 0.0' in after_check1
        assert 'fleet_nodes_by_status{status="CHECK_ERROR"} 1.0' in after_check1
        assert 'fleet_nodes_by_status{status="NOT_CHECKED"} 1.0' in after_check1

        # 4. Recover node 1 and check node 2 with CONNECTED
        transport.outcome = ConnectivityOutcome.CONNECTED
        client.post(f"/api/nodes/{n1}/connectivity-check", headers=auth_headers)
        client.post(f"/api/nodes/{n2}/connectivity-check", headers=auth_headers)

        after_check2 = client.get("/metrics").text
        assert 'fleet_connectivity_checks_total{outcome="AUTH_FAILED"} 1.0' in after_check2
        assert 'fleet_connectivity_checks_total{outcome="CONNECTED"} 2.0' in after_check2
        assert 'fleet_nodes_by_status{status="REACHABLE"} 2.0' in after_check2
        assert 'fleet_nodes_by_status{status="NOT_CHECKED"} 0.0' in after_check2
        assert 'fleet_nodes_by_status{status="CHECK_ERROR"} 0.0' in after_check2


def test_metrics_distinguishes_ssh_failure_from_scrape(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str]
) -> None:
    """Demonstrate that an SSH check failure does not fail HTTP /metrics scraping."""
    db = tmp_path / "inventory.db"
    transport = FakeTransport(ConnectivityOutcome.CONNECTION_REFUSED)
    app = create_app(
        db,
        api_token=api_token,
        ssh_transport=transport,
        ssh_settings=SSHSettings("observer", tmp_path / "hosts", tmp_path / "key"),
    )
    with TestClient(app) as client:
        node_id = client.post(
            "/api/nodes",
            json={"name": "refused-node", "address": "127.0.0.1"},
            headers=auth_headers,
        ).json()["id"]

        # SSH connectivity check fails (refused)
        check_res = client.post(f"/api/nodes/{node_id}/connectivity-check", headers=auth_headers)
        assert check_res.status_code == 200
        assert check_res.json()["outcome"] == "CONNECTION_REFUSED"

        # HTTP /metrics scrape nevertheless SUCCEEDS with HTTP 200
        scrape_res = client.get("/metrics")
        assert scrape_res.status_code == 200
        assert (
            'fleet_connectivity_checks_total{outcome="CONNECTION_REFUSED"} 1.0' in scrape_res.text
        )
        assert 'fleet_nodes_by_status{status="UNREACHABLE"} 1.0' in scrape_res.text
