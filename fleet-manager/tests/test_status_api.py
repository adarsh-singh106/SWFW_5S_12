"""Authenticated display status keeps inventory and observation history separate."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.inventory.models import Node, ObservationState
from fleet_manager.main import create_app


class MutableTransport:
    outcome = ConnectivityOutcome.AUTH_FAILED

    def verify(self, _node: Node, _settings: SSHSettings) -> ConnectivityOutcome:
        return self.outcome


def test_status_api_never_checked_failure_recovery_and_auth(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str]
) -> None:
    transport = MutableTransport()
    database = tmp_path / "inventory.db"
    app = create_app(
        database,
        api_token=api_token,
        ssh_transport=transport,
        ssh_settings=SSHSettings("observer", tmp_path / "hosts", tmp_path / "key"),
    )
    with TestClient(app) as client:
        assert client.get("/api/nodes/status").status_code == 401
        created = client.post(
            "/api/nodes",
            headers=auth_headers,
            json={"name": "node", "address": "127.0.0.1"},
        ).json()
        node_id = created["id"]

        def status() -> dict[str, object]:
            response = client.get("/api/nodes/status", headers=auth_headers)
            assert response.status_code == 200
            assert response.json()["observation_ttl_seconds"] == 180
            return response.json()["nodes"][0]

        initial = status()
        assert initial["display_status"] == "NOT_CHECKED"
        assert initial["observation"] is None
        assert initial["node"] == created

        failed = client.post(f"/api/nodes/{node_id}/connectivity-check", headers=auth_headers)
        assert failed.status_code == 200
        checked = status()
        assert checked["display_status"] == "CHECK_ERROR"
        assert checked["reason"] == "AUTH_FAILED"
        assert checked["observation"]["outcome"] == "AUTH_FAILED"

        transport.outcome = ConnectivityOutcome.CONNECTED
        recovered = client.post(f"/api/nodes/{node_id}/connectivity-check", headers=auth_headers)
        assert recovered.status_code == 200
        current = status()
        assert current["display_status"] == "REACHABLE"
        assert current["observation"]["outcome"] == "CONNECTED"
        assert client.get("/api/nodes", headers=auth_headers).json()["nodes"] == [created]
    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT count(*) FROM connectivity_observations").fetchone()[0]
        assert count == 2


def test_status_api_stale_success_is_not_reachable(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str]
) -> None:
    database = tmp_path / "inventory.db"
    with TestClient(create_app(database, api_token=api_token), headers=auth_headers) as client:
        node_id = client.post("/api/nodes", json={"name": "node", "address": "127.0.0.1"}).json()[
            "id"
        ]
        SQLiteConnectivityRepository(database).save(
            node_id, datetime.now(UTC) - timedelta(seconds=181), ConnectivityOutcome.CONNECTED
        )
        response = client.get("/api/nodes/status")
        assert response.status_code == 200
        view = response.json()["nodes"][0]
        assert view["display_status"] == "STALE"
        assert view["reason"] == "TTL_EXPIRED"
        assert view["observation"]["outcome"] == "CONNECTED"
        assert view["node"]["observation_state"] == ObservationState.NOT_CHECKED
