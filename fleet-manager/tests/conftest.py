"""Isolated HTTP clients for the production package."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fleet_manager.main import create_app


@pytest.fixture
def api_token() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def auth_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}"}


@pytest.fixture
def client(tmp_path: Path, api_token: str, auth_headers: dict[str, str]) -> Iterator[TestClient]:
    with TestClient(
        create_app(tmp_path / "inventory.db", api_token=api_token), headers=auth_headers
    ) as test_client:
        yield test_client


@pytest.fixture
def unauthenticated_client(tmp_path: Path, api_token: str) -> Iterator[TestClient]:
    with TestClient(create_app(tmp_path / "inventory.db", api_token=api_token)) as test_client:
        yield test_client
