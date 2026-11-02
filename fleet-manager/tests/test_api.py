"""HTTP contract and persistence behavior for node inventory."""

import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from fleet_manager.main import create_app


def test_empty_inventory(client: TestClient) -> None:
    response = client.get("/api/nodes")
    assert response.status_code == 200
    assert response.json() == {"nodes": []}


def test_register_and_list_node(client: TestClient) -> None:
    response = client.post(
        "/api/nodes",
        json={"name": "  web-01  ", "address": "NODE.Example", "ssh_port": 2222},
    )
    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "name": "web-01",
        "address": "node.example",
        "ssh_port": 2222,
        "observation_state": "NOT_CHECKED",
    }
    assert client.get("/api/nodes").json() == {"nodes": [response.json()]}


def test_multiple_registrations_and_ipv6(client: TestClient) -> None:
    first = client.post("/api/nodes", json={"name": "one", "address": "192.0.2.10"})
    second = client.post(
        "/api/nodes",
        json={"name": "two", "address": "2001:0db8:0000::1", "ssh_port": 2200},
    )
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["ssh_port"] == 22
    assert second.json()["address"] == "2001:db8::1"
    assert client.get("/api/nodes").json()["nodes"] == [first.json(), second.json()]


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({"name": "   ", "address": "node.example"}, "invalid_node"),
        ({"name": "node", "address": "999.1.2.3"}, "invalid_node"),
        ({"name": "node", "address": "bad_host"}, "invalid_node"),
        ({"name": "node", "address": "node.example", "ssh_port": 0}, "invalid_node"),
        ({"name": "node", "address": "node.example", "ssh_port": 65536}, "invalid_node"),
        ({"name": "node", "address": "node.example", "ssh_port": True}, "invalid_request"),
        ({"name": "node"}, "invalid_request"),
        ({"name": "node", "address": "node.example", "extra": "no"}, "invalid_request"),
        ({"name": "line\nbreak", "address": "node.example"}, "invalid_node"),
    ],
)
def test_invalid_registration_has_consistent_error(
    client: TestClient, payload: dict[str, object], error_code: str
) -> None:
    response = client.post("/api/nodes", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == error_code
    assert set(response.json()) == {"error"}
    assert client.get("/api/nodes").json() == {"nodes": []}


def test_duplicate_endpoint_uses_database_constraint(client: TestClient) -> None:
    first = client.post(
        "/api/nodes", json={"name": "first", "address": "NODE.EXAMPLE", "ssh_port": 22}
    )
    duplicate = client.post(
        "/api/nodes", json={"name": "second", "address": "node.example", "ssh_port": 22}
    )
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "error": {
            "code": "duplicate_node",
            "message": "Node endpoint is already registered",
        }
    }
    assert len(client.get("/api/nodes").json()["nodes"]) == 1


def test_inventory_survives_application_recreation(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str]
) -> None:
    database_path = tmp_path / "inventory.db"
    with TestClient(
        create_app(database_path, api_token=api_token), headers=auth_headers
    ) as first_client:
        saved = first_client.post(
            "/api/nodes", json={"name": "persistent", "address": "192.0.2.20"}
        )
        assert saved.status_code == 201
    with TestClient(
        create_app(database_path, api_token=api_token), headers=auth_headers
    ) as second_client:
        assert second_client.get("/api/nodes").json() == {"nodes": [saved.json()]}


def test_database_corruption_is_503_without_internal_details(
    tmp_path: Path, api_token: str, auth_headers: dict[str, str]
) -> None:
    database_path = tmp_path / "inventory.db"
    with TestClient(create_app(database_path, api_token=api_token), headers=auth_headers) as client:
        database_path.write_bytes(b"not a SQLite database")
        response = client.get("/api/nodes")
    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "storage_unavailable", "message": "Inventory storage is unavailable"}
    }


def test_register_and_list_never_open_remote_connection_or_subprocess(
    client: TestClient,
) -> None:
    with (
        patch.object(socket, "create_connection", side_effect=AssertionError("unexpected SSH")),
        patch.object(socket.socket, "connect", side_effect=AssertionError("unexpected socket")),
        patch.object(subprocess, "Popen", side_effect=AssertionError("unexpected process")),
        patch.object(subprocess, "run", side_effect=AssertionError("unexpected process")),
    ):
        created = client.post("/api/nodes", json={"name": "isolated", "address": "192.0.2.30"})
        listed = client.get("/api/nodes")
    assert created.status_code == 201
    assert listed.status_code == 200


def test_openapi_contract_declares_inventory_operations(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert set(paths["/api/nodes"]) == {"get", "post"}
    assert paths["/api/nodes"]["post"]["responses"]["201"]
