"""SSH observation use case, API contract, and version-1 database migration."""

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings, load_connectivity_limits, load_ssh_settings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.errors import (
    ConnectivityBusy,
    ConnectivityConfigurationError,
    ConnectivityInProgress,
    ConnectivityUnavailable,
)
from fleet_manager.inventory.models import NewNode, Node
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.main import create_app


class FakeSSHTransport:
    def __init__(self, outcome: ConnectivityOutcome = ConnectivityOutcome.CONNECTED) -> None:
        self.outcome = outcome
        self.calls: list[tuple[Node, SSHSettings]] = []
        self.failure: Exception | None = None

    def verify(self, node: Node, settings: SSHSettings) -> ConnectivityOutcome:
        self.calls.append((node, settings))
        if self.failure is not None:
            raise self.failure
        return self.outcome


@pytest.fixture
def ssh_settings(tmp_path: Path) -> SSHSettings:
    return SSHSettings("fleet-observer", tmp_path / "known_hosts", tmp_path / "observer-key")


@pytest.fixture
def fake_transport() -> FakeSSHTransport:
    return FakeSSHTransport()


@pytest.fixture
def connectivity_client(
    tmp_path: Path,
    api_token: str,
    auth_headers: dict[str, str],
    ssh_settings: SSHSettings,
    fake_transport: FakeSSHTransport,
) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "inventory.db",
            api_token=api_token,
            ssh_transport=fake_transport,
            ssh_settings=ssh_settings,
        ),
        headers=auth_headers,
    )


def test_registered_node_check_and_latest_observation(
    connectivity_client: TestClient,
    fake_transport: FakeSSHTransport,
    ssh_settings: SSHSettings,
) -> None:
    with connectivity_client as client:
        created = client.post(
            "/api/nodes", json={"name": "observer", "address": "node.example", "ssh_port": 2222}
        )
        assert created.status_code == 201
        node_id = created.json()["id"]
        before = client.get(f"/api/nodes/{node_id}/connectivity")
        assert before.status_code == 200
        assert before.json() == {"observation": None}

        checked = client.post(f"/api/nodes/{node_id}/connectivity-check")
        assert checked.status_code == 200
        body = checked.json()
        assert body["node_id"] == node_id
        assert body["outcome"] == "CONNECTED"
        assert body["error_category"] is None
        assert body["observed_at"].endswith("Z")
        assert client.get(f"/api/nodes/{node_id}/connectivity").json() == {"observation": body}
        assert client.get("/api/nodes").json()["nodes"] == [created.json()]
        assert created.json()["observation_state"] == "NOT_CHECKED"
    assert len(fake_transport.calls) == 1
    assert fake_transport.calls[0][0].address == "node.example"
    assert fake_transport.calls[0][0].ssh_port == 2222
    assert fake_transport.calls[0][1] == ssh_settings


@pytest.mark.parametrize(
    "outcome",
    [
        ConnectivityOutcome.HOST_KEY_UNKNOWN,
        ConnectivityOutcome.HOST_KEY_MISMATCH,
        ConnectivityOutcome.AUTH_FAILED,
        ConnectivityOutcome.CONNECTION_REFUSED,
        ConnectivityOutcome.CONNECTION_TIMEOUT,
        ConnectivityOutcome.TIMEOUT,
        ConnectivityOutcome.EXECUTION_TIMEOUT,
        ConnectivityOutcome.DNS_ERROR,
        ConnectivityOutcome.UNKNOWN_ERROR,
    ],
)
def test_failed_check_is_recorded_as_failure_not_health(
    connectivity_client: TestClient,
    fake_transport: FakeSSHTransport,
    outcome: ConnectivityOutcome,
) -> None:
    fake_transport.outcome = outcome
    with connectivity_client as client:
        created = client.post("/api/nodes", json={"name": "node", "address": "192.0.2.5"})
        node_id = created.json()["id"]
        response = client.post(f"/api/nodes/{node_id}/connectivity-check")
        assert response.status_code == 200
        assert response.json()["outcome"] == outcome.value
        assert response.json()["error_category"] == outcome.value
        assert client.get("/api/nodes").json()["nodes"][0]["observation_state"] == "NOT_CHECKED"


def test_transport_exception_is_unknown_and_persisted(
    connectivity_client: TestClient, fake_transport: FakeSSHTransport
) -> None:
    fake_transport.failure = RuntimeError("secret transport diagnostics")
    with connectivity_client as client:
        node_id = client.post("/api/nodes", json={"name": "node", "address": "192.0.2.6"}).json()[
            "id"
        ]
        response = client.post(f"/api/nodes/{node_id}/connectivity-check")
        assert response.status_code == 200
        assert response.json()["outcome"] == "UNKNOWN_ERROR"
        assert "secret transport diagnostics" not in response.text


def test_missing_ssh_configuration_does_not_contact_node_or_record_observation(
    tmp_path: Path,
    api_token: str,
    auth_headers: dict[str, str],
    fake_transport: FakeSSHTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "FLEET_MANAGER_SSH_USERNAME",
        "FLEET_MANAGER_SSH_KNOWN_HOSTS",
        "FLEET_MANAGER_SSH_PRIVATE_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)
    with TestClient(
        create_app(tmp_path / "inventory.db", api_token=api_token, ssh_transport=fake_transport),
        headers=auth_headers,
    ) as client:
        node_id = client.post("/api/nodes", json={"name": "node", "address": "192.0.2.7"}).json()[
            "id"
        ]
        response = client.post(f"/api/nodes/{node_id}/connectivity-check")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "connectivity_unavailable"
        assert client.get(f"/api/nodes/{node_id}/connectivity").json() == {"observation": None}
        assert client.post("/api/nodes/999/connectivity-check").status_code == 404
    assert fake_transport.calls == []


def test_missing_node_returns_404_without_transport(
    connectivity_client: TestClient, fake_transport: FakeSSHTransport
) -> None:
    with connectivity_client as client:
        response = client.post("/api/nodes/999/connectivity-check")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "node_not_found"
        assert client.get("/api/nodes/999/connectivity").status_code == 404
    assert fake_transport.calls == []


def test_connectivity_endpoints_require_bearer_token(
    tmp_path: Path, api_token: str, ssh_settings: SSHSettings, fake_transport: FakeSSHTransport
) -> None:
    with TestClient(
        create_app(
            tmp_path / "inventory.db",
            api_token=api_token,
            ssh_transport=fake_transport,
            ssh_settings=ssh_settings,
        )
    ) as client:
        assert client.post("/api/nodes/1/connectivity-check").status_code == 401
        assert client.get("/api/nodes/1/connectivity").status_code == 401
    assert fake_transport.calls == []


def test_v1_inventory_migrates_without_changing_node_and_persists_observation(
    tmp_path: Path,
    api_token: str,
    auth_headers: dict[str, str],
    ssh_settings: SSHSettings,
    fake_transport: FakeSSHTransport,
) -> None:
    database_path = tmp_path / "inventory.db"
    original = SQLiteNodeRepository(database_path)
    original.initialize()
    saved = original.add_node(NewNode("legacy", "192.0.2.8", 22))
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    with TestClient(
        create_app(
            database_path,
            api_token=api_token,
            ssh_transport=fake_transport,
            ssh_settings=ssh_settings,
        ),
        headers=auth_headers,
    ) as client:
        assert client.get("/api/nodes").json()["nodes"][0]["id"] == saved.id
        checked = client.post(f"/api/nodes/{saved.id}/connectivity-check")
        assert checked.status_code == 200
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] in (2, 3, 4, 5, 6)
        assert connection.execute("SELECT count(*) FROM nodes").fetchone()[0] == 1
    with TestClient(create_app(database_path, api_token=api_token), headers=auth_headers) as client:
        assert client.get(f"/api/nodes/{saved.id}/connectivity").json() == {
            "observation": checked.json()
        }


def test_configuration_error_does_not_become_unknown_observation(
    connectivity_client: TestClient, fake_transport: FakeSSHTransport
) -> None:
    fake_transport.failure = ConnectivityConfigurationError("private key unavailable")
    with connectivity_client as client:
        node_id = client.post("/api/nodes", json={"name": "node", "address": "192.0.2.9"}).json()[
            "id"
        ]
        response = client.post(f"/api/nodes/{node_id}/connectivity-check")
        assert response.status_code == 503
        assert "private key unavailable" not in response.text
        assert client.get(f"/api/nodes/{node_id}/connectivity").json() == {"observation": None}


def test_ssh_configuration_rejects_root_and_exposed_private_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    known_hosts = tmp_path / "known_hosts"
    private_key = tmp_path / "observer-key"
    known_hosts.write_text("", encoding="ascii")
    private_key.write_text("placeholder", encoding="ascii")
    monkeypatch.setenv("FLEET_MANAGER_SSH_KNOWN_HOSTS", str(known_hosts))
    monkeypatch.setenv("FLEET_MANAGER_SSH_PRIVATE_KEY", str(private_key))
    monkeypatch.setenv("FLEET_MANAGER_SSH_USERNAME", "root")
    with pytest.raises(ConnectivityConfigurationError):
        load_ssh_settings()

    if os.name == "posix":
        monkeypatch.setenv("FLEET_MANAGER_SSH_USERNAME", "fleet-observer")
        private_key.chmod(0o644)
        with pytest.raises(ConnectivityConfigurationError):
            load_ssh_settings()


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (ConnectivityBusy(), 429, "connectivity_busy"),
        (ConnectivityInProgress(), 409, "connectivity_in_progress"),
        (ConnectivityUnavailable(), 503, "connectivity_unavailable"),
    ],
)
def test_rejected_check_has_no_observation(
    tmp_path: Path,
    api_token: str,
    auth_headers: dict[str, str],
    ssh_settings: SSHSettings,
    fake_transport: FakeSSHTransport,
    failure: Exception,
    status: int,
    code: str,
) -> None:
    fake_transport.failure = failure
    with TestClient(
        create_app(
            tmp_path / "inventory.db",
            api_token=api_token,
            ssh_transport=fake_transport,
            ssh_settings=ssh_settings,
        ),
        headers=auth_headers,
    ) as client:
        node_id = client.post("/api/nodes", json={"name": "node", "address": "192.0.2.10"}).json()[
            "id"
        ]
        response = client.post(f"/api/nodes/{node_id}/connectivity-check")
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert client.get(f"/api/nodes/{node_id}/connectivity").json() == {"observation": None}


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("FLEET_MANAGER_SSH_MAX_CONCURRENT", "0"),
        ("FLEET_MANAGER_SSH_MAX_CONCURRENT", "17"),
        ("FLEET_MANAGER_SSH_TOTAL_TIMEOUT_SECONDS", "nan"),
        ("FLEET_MANAGER_SSH_TOTAL_TIMEOUT_SECONDS", "0"),
    ],
)
def test_invalid_executor_settings_fail_closed(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(RuntimeError):
        load_connectivity_limits()
