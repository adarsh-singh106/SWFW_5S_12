"""Standalone configuration and token-guard checks for Chunk 02."""

import hashlib
import secrets
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from fleet_manager.config import TOKEN_ENV, load_settings
from fleet_manager.errors import AuthenticationError
from fleet_manager.security.auth import require_operator_token


def test_missing_token_fails_before_database_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    database = tmp_path / "inventory.db"

    with pytest.raises(RuntimeError, match=TOKEN_ENV):
        load_settings(database)

    assert not database.exists()


@pytest.mark.parametrize("token", ["short", "a" * 32 + "!", "a" * 129])
def test_malformed_configured_token_is_rejected(tmp_path: Path, token: str) -> None:
    with pytest.raises(RuntimeError, match=TOKEN_ENV):
        load_settings(tmp_path / "inventory.db", api_token=token)


def test_settings_select_database_and_retain_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = secrets.token_urlsafe(32)
    database = tmp_path / "inventory.db"
    monkeypatch.setenv(TOKEN_ENV, token)
    monkeypatch.setenv("FLEET_MANAGER_DATABASE_PATH", str(database))

    settings = load_settings()

    assert settings.database_path == database
    assert settings.operator_token_digest == hashlib.sha256(token.encode("ascii")).digest()
    assert token not in repr(settings)
    assert not database.exists()


def _guard_client(token: str, *, include_digest: bool = True) -> TestClient:
    app = FastAPI()
    if include_digest:
        app.state.operator_token_digest = hashlib.sha256(token.encode("ascii")).digest()

    @app.exception_handler(AuthenticationError)
    async def denied(_request: Request, _error: AuthenticationError) -> JSONResponse:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    @app.get("/protected", dependencies=[Depends(require_operator_token)])
    def protected() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_correct_token_allows_request() -> None:
    token = secrets.token_urlsafe(32)
    with _guard_client(token) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_missing_malformed_and_wrong_tokens_are_denied() -> None:
    token = secrets.token_urlsafe(32)
    wrong = secrets.token_urlsafe(32)
    with _guard_client(token) as client:
        for header in (
            None,
            "Basic credential",
            "Bearer short",
            f"Bearer  {token}",
            f"Bearer {wrong}",
        ):
            headers = {} if header is None else {"Authorization": header}
            response = client.get("/protected", headers=headers)
            assert response.status_code == 401
            assert response.json() == {"error": "unauthorized"}
            assert token not in response.text
            assert wrong not in response.text


def test_duplicate_headers_and_missing_verifier_are_denied() -> None:
    token = secrets.token_urlsafe(32)
    header = ("Authorization", f"Bearer {token}")
    with _guard_client(token) as client:
        assert client.get("/protected", headers=[header, header]).status_code == 401
    with _guard_client(token, include_digest=False) as client:
        assert client.get("/protected", headers={header[0]: header[1]}).status_code == 401
