"""The inventory boundary denies requests without exposing the shared secret."""

import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fleet_manager.main import create_app


@pytest.mark.parametrize("method", ["get", "post"])
def test_missing_credential_is_401(unauthenticated_client: TestClient, method: str) -> None:
    request = getattr(unauthenticated_client, method)
    response = request(
        "/api/nodes",
        **({"json": {"name": "test", "address": "192.0.2.1"}} if method == "post" else {}),
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Authentication required"}
    }


@pytest.mark.parametrize("method", ["get", "post"])
def test_invalid_credential_is_401(unauthenticated_client: TestClient, method: str) -> None:
    wrong_token = secrets.token_urlsafe(32)
    request = getattr(unauthenticated_client, method)
    response = request(
        "/api/nodes",
        headers={"Authorization": f"Bearer {wrong_token}"},
        **({"json": {"name": "test", "address": "192.0.2.1"}} if method == "post" else {}),
    )
    assert response.status_code == 401
    assert wrong_token not in response.text
    assert (
        unauthenticated_client.get(
            "/api/nodes", headers={"Authorization": f"Bearer {wrong_token}"}
        ).status_code
        == 401
    )


def test_malformed_authentication_header_is_401(
    unauthenticated_client: TestClient, api_token: str
) -> None:
    for header in ("Basic credentials", "Bearer", f"Bearer  {api_token}", "Bearer short"):
        response = unauthenticated_client.get("/api/nodes", headers={"Authorization": header})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"


def test_duplicate_authorization_headers_are_rejected(
    unauthenticated_client: TestClient, api_token: str
) -> None:
    response = unauthenticated_client.get(
        "/api/nodes",
        headers=[
            ("Authorization", f"Bearer {api_token}"),
            ("Authorization", f"Bearer {api_token}"),
        ],
    )
    assert response.status_code == 401


def test_valid_credential_allows_get_and_post(client: TestClient) -> None:
    created = client.post("/api/nodes", json={"name": "authorized", "address": "192.0.2.2"})
    assert created.status_code == 201
    assert client.get("/api/nodes").json() == {"nodes": [created.json()]}


def test_unauthorized_post_does_not_validate_or_write_inventory(
    unauthenticated_client: TestClient, auth_headers: dict[str, str]
) -> None:
    denied = unauthenticated_client.post("/api/nodes", json={"name": ""})
    assert denied.status_code == 401
    assert unauthenticated_client.get("/api/nodes", headers=auth_headers).json() == {"nodes": []}


def test_token_is_absent_from_responses_openapi_and_logs(
    unauthenticated_client: TestClient,
    api_token: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    invalid_token = secrets.token_urlsafe(32)
    denied = unauthenticated_client.get(
        "/api/nodes", headers={"Authorization": f"Bearer {invalid_token}"}
    )
    contract = unauthenticated_client.get("/openapi.json")
    assert denied.status_code == 401
    assert contract.status_code == 200
    for secret in (api_token, invalid_token):
        assert secret not in denied.text
        assert secret not in contract.text
        assert secret not in caplog.text
    operations = contract.json()["paths"]["/api/nodes"]
    assert operations["get"]["security"] == [{"OperatorToken": []}]
    assert operations["post"]["security"] == [{"OperatorToken": []}]


def test_missing_token_prevents_startup_and_storage_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FLEET_MANAGER_API_TOKEN", raising=False)
    database_path = tmp_path / "inventory.db"
    with pytest.raises(RuntimeError, match="FLEET_MANAGER_API_TOKEN"):
        with TestClient(create_app(database_path)):
            pass
    assert not database_path.exists()


def test_short_token_prevents_startup(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="FLEET_MANAGER_API_TOKEN"):
        with TestClient(create_app(tmp_path / "inventory.db", api_token="weak")):
            pass


def test_deployment_database_path_is_used_on_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "state" / "inventory.db"
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("FLEET_MANAGER_DATABASE_PATH", str(database_path))

    with TestClient(create_app(api_token=token)) as client:
        created = client.post(
            "/api/nodes",
            json={"name": "deployment-node", "address": "192.0.2.18"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 201

    assert database_path.exists()
