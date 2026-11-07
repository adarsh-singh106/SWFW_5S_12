"""Comprehensive tests for the single-administrator password authentication redesign."""

from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from scripts.reset_admin_password import reset_password

from fleet_manager.main import create_app
from fleet_manager.security.passwords import hash_password, verify_password
from fleet_manager.security.repository import SQLiteAuthRepository
from fleet_manager.security.session import SESSION_COOKIE_NAME


@pytest.fixture
def api_token() -> str:
    return secrets.token_urlsafe(32)


# ==============================================================================
# 1. BOOTSTRAP LIFECYCLE TESTS
# ==============================================================================


def test_first_startup_with_configured_initial_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    initial_pw = "CustomSecurePassword123!"
    monkeypatch.setenv("FLEET_MANAGER_INITIAL_PASSWORD", initial_pw)

    app = create_app(database_path=db_path)
    with TestClient(app) as client:
        # Check status endpoint
        status = client.get("/api/auth/status")
        assert status.status_code == 200
        data = status.json()
        assert data["setup_required"] is False
        assert data["password_change_required"] is True

        # Verify no plaintext password in the database
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT password_hash, must_change_password FROM administrator_credentials WHERE id = 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0].startswith("$argon2id$")
        assert initial_pw not in row[0]
        assert row[1] == 1
        assert verify_password(initial_pw, row[0]) is True


def test_first_startup_without_initial_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.delenv("FLEET_MANAGER_INITIAL_PASSWORD", raising=False)
    monkeypatch.delenv("FLEET_MANAGER_API_TOKEN", raising=False)

    app = create_app(database_path=db_path, enable_password_auth=True)
    with TestClient(app) as client:
        status = client.get("/api/auth/status")
        assert status.status_code == 200
        data = status.json()
        assert data["setup_required"] is True
        assert data["password_change_required"] is False

        # Attempting login before setup fails
        login_resp = client.post("/api/auth/login", json={"password": "any-password-attempt"})
        assert login_resp.status_code == 401


def test_setup_can_occur_only_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.delenv("FLEET_MANAGER_INITIAL_PASSWORD", raising=False)

    app = create_app(database_path=db_path, enable_password_auth=True)
    with TestClient(app) as client:
        # 1. Initial setup succeeds
        setup_resp = client.post(
            "/api/auth/setup",
            json={"password": "AdminPassword1234", "confirm_password": "AdminPassword1234"},
        )
        assert setup_resp.status_code == 200
        assert setup_resp.json()["ok"] is True
        assert SESSION_COOKIE_NAME in setup_resp.cookies

        # 2. Second setup attempt fails with 409 Conflict
        second_resp = client.post(
            "/api/auth/setup",
            json={"password": "AnotherPassword5678", "confirm_password": "AnotherPassword5678"},
        )
        assert second_resp.status_code == 409
        assert second_resp.json()["error"]["code"] == "setup_already_completed"


def test_setup_restricted_to_loopback(tmp_path: Path) -> None:
    db_path = tmp_path / "inventory.db"
    app = create_app(database_path=db_path, enable_password_auth=True)

    with TestClient(app, client=("198.51.100.25", 50000)) as client:
        resp = client.post(
            "/api/auth/setup",
            json={"password": "AdminPassword1234", "confirm_password": "AdminPassword1234"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"


def test_changeme_bootstrap_requires_immediate_password_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.setenv("FLEET_MANAGER_INITIAL_PASSWORD", "CHANGEME")

    app = create_app(database_path=db_path)
    with TestClient(app) as client:
        # Login with CHANGEME
        login_resp = client.post("/api/auth/login", json={"password": "CHANGEME"})
        assert login_resp.status_code == 200
        assert login_resp.json()["must_change_password"] is True
        cookie = login_resp.cookies[SESSION_COOKIE_NAME]

        # Protected dashboard action is denied before password change
        protected_resp = client.get("/api/nodes", cookies={SESSION_COOKIE_NAME: cookie})
        assert protected_resp.status_code == 401


def test_changeme_bootstrap_fails_closed_on_external_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.setenv("FLEET_MANAGER_INITIAL_PASSWORD", "CHANGEME")
    monkeypatch.setenv("FLEET_MANAGER_HOST", "0.0.0.0")

    app = create_app(database_path=db_path)
    with pytest.raises(RuntimeError, match="Unsafe external bootstrap configuration"):
        with TestClient(app):
            pass


def test_environment_initial_password_ignored_after_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.setenv("FLEET_MANAGER_INITIAL_PASSWORD", "InitialPassword123!")

    # 1. First run persists InitialPassword123!
    app1 = create_app(database_path=db_path)
    with TestClient(app1) as client1:
        assert (
            client1.post("/api/auth/login", json={"password": "InitialPassword123!"}).status_code
            == 200
        )

    # 2. Change environment variable to a new value
    monkeypatch.setenv("FLEET_MANAGER_INITIAL_PASSWORD", "BrandNewPassword999!")

    # 3. Second run must ignore the changed environment variable
    app2 = create_app(database_path=db_path)
    with TestClient(app2) as client2:
        # Old password still works
        assert (
            client2.post("/api/auth/login", json={"password": "InitialPassword123!"}).status_code
            == 200
        )
        # New environment password does NOT work
        assert (
            client2.post("/api/auth/login", json={"password": "BrandNewPassword999!"}).status_code
            == 401
        )


# ==============================================================================
# 2. PASSWORD AUTHENTICATION & SESSION MANAGEMENT TESTS
# ==============================================================================


def test_valid_login_and_logout_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.delenv("FLEET_MANAGER_INITIAL_PASSWORD", raising=False)

    app = create_app(database_path=db_path, enable_password_auth=True)
    with TestClient(app) as client:
        # Initial setup
        client.post(
            "/api/auth/setup",
            json={"password": "StrongPassword2026!", "confirm_password": "StrongPassword2026!"},
        )

        # Login
        login_resp = client.post("/api/auth/login", json={"password": "StrongPassword2026!"})
        assert login_resp.status_code == 200
        assert SESSION_COOKIE_NAME in login_resp.cookies
        csrf_token = login_resp.json()["csrf_token"]

        # Session check
        sess_resp = client.get("/api/auth/session")
        assert sess_resp.status_code == 200
        assert sess_resp.json()["authenticated"] is True
        assert sess_resp.json()["csrf_token"] == csrf_token

        # Logout
        logout_resp = client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": csrf_token, "Origin": "http://testserver"},
        )
        assert logout_resp.status_code == 200

        # Session check after logout
        after_logout = client.get("/api/auth/session")
        assert after_logout.status_code == 200
        assert after_logout.json()["authenticated"] is False


def test_logout_rejects_invalid_csrf_without_revoking_session(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "inventory.db", enable_password_auth=True)
    with TestClient(app) as client:
        setup = client.post(
            "/api/auth/setup",
            json={"password": "StrongPassword2026!", "confirm_password": "StrongPassword2026!"},
        )
        assert setup.status_code == 200
        rejected = client.post("/api/auth/logout", headers={"Origin": "http://testserver"})
        assert rejected.status_code == 401
        assert client.get("/api/auth/session").json()["authenticated"] is True
        valid = client.post(
            "/api/auth/logout",
            headers={"Origin": "http://testserver", "X-CSRF-Token": setup.json()["csrf_token"]},
        )
        assert valid.status_code == 200
        assert client.get("/api/auth/session").json()["authenticated"] is False


def test_login_rate_limiting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.delenv("FLEET_MANAGER_INITIAL_PASSWORD", raising=False)

    app = create_app(database_path=db_path, enable_password_auth=True)
    with TestClient(app) as client:
        # Setup
        client.post(
            "/api/auth/setup",
            json={"password": "CorrectPassword123!", "confirm_password": "CorrectPassword123!"},
        )

        # 5 failed login attempts
        for _ in range(5):
            bad = client.post("/api/auth/login", json={"password": "WrongPassword!"})
            assert bad.status_code == 401
            assert bad.json()["error"]["code"] == "unauthorized"

        # 6th attempt is rate-limited (429)
        locked = client.post("/api/auth/login", json={"password": "WrongPassword!"})
        assert locked.status_code == 429
        assert locked.json()["error"]["code"] == "rate_limited"


def test_change_password_revokes_other_sessions_and_rotates_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.setenv("FLEET_MANAGER_INITIAL_PASSWORD", "CHANGEME")

    app = create_app(database_path=db_path)
    with TestClient(app) as client:
        # Operator 1 logs in
        login1 = client.post("/api/auth/login", json={"password": "CHANGEME"})
        cookie1 = login1.cookies[SESSION_COOKIE_NAME]
        csrf1 = login1.json()["csrf_token"]

        # Operator 2 logs in (simulating second session)
        login2 = client.post("/api/auth/login", json={"password": "CHANGEME"})
        cookie2 = login2.cookies[SESSION_COOKIE_NAME]

        # Operator 1 changes password
        change_resp = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "CHANGEME",
                "new_password": "BrandNewSecurePassword123!",
                "confirm_password": "BrandNewSecurePassword123!",
            },
            headers={"X-CSRF-Token": csrf1, "Origin": "http://testserver"},
            cookies={SESSION_COOKIE_NAME: cookie1},
        )
        assert change_resp.status_code == 200
        new_cookie1 = change_resp.cookies[SESSION_COOKIE_NAME]
        assert new_cookie1 != cookie1

        # Operator 2's session (cookie2) is now invalidated
        op2_check = client.get("/api/auth/session", cookies={SESSION_COOKIE_NAME: cookie2})
        assert op2_check.json()["authenticated"] is False

        # Old password cannot log in
        assert client.post("/api/auth/login", json={"password": "CHANGEME"}).status_code == 401

        # New password logs in successfully
        assert (
            client.post(
                "/api/auth/login", json={"password": "BrandNewSecurePassword123!"}
            ).status_code
            == 200
        )


def test_change_password_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.setenv("FLEET_MANAGER_INITIAL_PASSWORD", "CHANGEME")

    app = create_app(database_path=db_path)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"password": "CHANGEME"})
        csrf = login.json()["csrf_token"]

        # Mismatched new password
        mismatch = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "CHANGEME",
                "new_password": "NewPassword1234",
                "confirm_password": "MismatchPassword5678",
            },
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
        )
        assert mismatch.status_code == 422
        assert mismatch.json()["error"]["code"] == "password_mismatch"

        # Too short new password (< 12 chars)
        short = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "CHANGEME",
                "new_password": "short",
                "confirm_password": "short",
            },
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
        )
        assert short.status_code == 422

        # Reusing CHANGEME
        reuse = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "CHANGEME",
                "new_password": "CHANGEME",
                "confirm_password": "CHANGEME",
            },
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
        )
        assert reuse.status_code == 422

        # Wrong current password
        wrong_curr = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "WrongPassword!",
                "new_password": "ValidNewPassword1234",
                "confirm_password": "ValidNewPassword1234",
            },
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
        )
        assert wrong_curr.status_code == 401


# ==============================================================================
# 3. BROWSER SESSION & CSRF SECURITY TESTS
# ==============================================================================


def test_csrf_protection_on_cookie_authenticated_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.delenv("FLEET_MANAGER_INITIAL_PASSWORD", raising=False)

    app = create_app(database_path=db_path, enable_password_auth=True)
    with TestClient(app) as client:
        # Setup
        setup = client.post(
            "/api/auth/setup",
            json={"password": "AdminPassword1234", "confirm_password": "AdminPassword1234"},
        )
        csrf_token = setup.json()["csrf_token"]

        # State-changing request without CSRF token fails
        no_csrf = client.post(
            "/api/nodes",
            json={"name": "node-csrf", "address": "10.0.0.1"},
            headers={"Origin": "http://testserver"},
        )
        assert no_csrf.status_code == 401

        # State-changing request with invalid CSRF token fails
        bad_csrf = client.post(
            "/api/nodes",
            json={"name": "node-csrf", "address": "10.0.0.1"},
            headers={"X-CSRF-Token": "invalid-csrf-token", "Origin": "http://testserver"},
        )
        assert bad_csrf.status_code == 401

        # State-changing request with cross-origin Origin fails
        bad_origin = client.post(
            "/api/nodes",
            json={"name": "node-csrf", "address": "10.0.0.1"},
            headers={"X-CSRF-Token": csrf_token, "Origin": "https://evil.attacker.com"},
        )
        assert bad_origin.status_code == 401

        wrong_scheme = client.post(
            "/api/nodes",
            json={"name": "node-csrf", "address": "10.0.0.1"},
            headers={"X-CSRF-Token": csrf_token, "Origin": "https://testserver"},
        )
        assert wrong_scheme.status_code == 401

        # State-changing request with valid CSRF token and matching Origin succeeds
        good = client.post(
            "/api/nodes",
            json={"name": "node-csrf", "address": "10.0.0.1"},
            headers={"X-CSRF-Token": csrf_token, "Origin": "http://testserver"},
        )
        assert good.status_code == 201


def test_cookie_attributes_httponly_and_samesite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.delenv("FLEET_MANAGER_INITIAL_PASSWORD", raising=False)

    app = create_app(database_path=db_path, enable_password_auth=True)
    with TestClient(app) as client:
        setup = client.post(
            "/api/auth/setup",
            json={"password": "AdminPassword1234", "confirm_password": "AdminPassword1234"},
        )
        set_cookie = setup.headers.get("set-cookie", "")
        assert "httponly" in set_cookie.lower()
        assert "samesite=lax" in set_cookie.lower()
        assert "path=/" in set_cookie.lower()


def test_process_restart_invalidates_in_memory_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.delenv("FLEET_MANAGER_INITIAL_PASSWORD", raising=False)

    app1 = create_app(database_path=db_path, enable_password_auth=True)
    cookie = None
    with TestClient(app1) as client1:
        setup = client1.post(
            "/api/auth/setup",
            json={"password": "AdminPassword1234", "confirm_password": "AdminPassword1234"},
        )
        cookie = setup.cookies[SESSION_COOKIE_NAME]

    # Process restarts: create new app instance with same DB
    app2 = create_app(database_path=db_path, enable_password_auth=True)
    with TestClient(app2) as client2:
        check = client2.get("/api/auth/session", cookies={SESSION_COOKIE_NAME: cookie})
        assert check.json()["authenticated"] is False


# ==============================================================================
# 4. BACKWARD COMPATIBILITY: API BEARER TOKEN
# ==============================================================================


def test_existing_valid_bearer_token_works_without_password_session(
    tmp_path: Path, api_token: str
) -> None:
    db_path = tmp_path / "inventory.db"
    app = create_app(database_path=db_path, api_token=api_token)

    with TestClient(app) as client:
        # Programmatic client authenticates using Bearer token
        reg = client.post(
            "/api/nodes",
            json={"name": "api-node", "address": "10.0.0.5"},
            headers={"Authorization": f"Bearer {api_token}"},
        )
        assert reg.status_code == 201

        # GET works with Bearer token
        nodes = client.get("/api/nodes", headers={"Authorization": f"Bearer {api_token}"})
        assert nodes.status_code == 200
        assert len(nodes.json()["nodes"]) == 1


def test_bearer_token_and_browser_session_coexist(
    tmp_path: Path, api_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inventory.db"
    monkeypatch.setenv("FLEET_MANAGER_INITIAL_PASSWORD", "BootstrapAdminPass123")

    app = create_app(database_path=db_path, api_token=api_token)
    with TestClient(app) as client:
        # Bearer token request works independently
        reg1 = client.post(
            "/api/nodes",
            json={"name": "token-node", "address": "10.0.0.10"},
            headers={"Authorization": f"Bearer {api_token}"},
        )
        assert reg1.status_code == 201

        # Browser session logs in
        login = client.post("/api/auth/login", json={"password": "BootstrapAdminPass123"})
        assert login.status_code == 200
        cookie = login.cookies[SESSION_COOKIE_NAME]
        csrf = login.json()["csrf_token"]

        # Browser changes password to clear must_change_password
        ch_resp = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "BootstrapAdminPass123",
                "new_password": "FreshPassword9876!",
                "confirm_password": "FreshPassword9876!",
            },
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert ch_resp.status_code == 200
        new_csrf = ch_resp.json()["csrf_token"]
        new_cookie = ch_resp.cookies[SESSION_COOKIE_NAME]

        # Now browser session can perform operations
        reg2 = client.post(
            "/api/nodes",
            json={"name": "browser-node", "address": "10.0.0.20"},
            headers={"X-CSRF-Token": new_csrf, "Origin": "http://testserver"},
            cookies={SESSION_COOKIE_NAME: new_cookie},
        )
        assert reg2.status_code == 201


# ==============================================================================
# 5. CLI PASSWORD RESET MAINTENANCE COMMAND TESTS
# ==============================================================================


def test_cli_password_reset_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "inventory.db"
    # Seed initial database
    repo = SQLiteAuthRepository(db_path)
    repo.initialize()
    repo.create_credential(hash_password("OldPassword1234"), must_change_password=True)

    # Run CLI reset
    inputs = iter(["BrandNewSecretPassword123!", "BrandNewSecretPassword123!"])
    exit_code = reset_password(db_path, password_getter=lambda prompt: next(inputs))
    assert exit_code == 0

    # Verify updated in DB and must_change_password is False
    cred = repo.get_credential()
    assert cred is not None
    assert cred.must_change_password is False
    assert verify_password("BrandNewSecretPassword123!", cred.password_hash) is True
    assert verify_password("OldPassword1234", cred.password_hash) is False


def test_cli_password_reset_mismatch(tmp_path: Path) -> None:
    db_path = tmp_path / "inventory.db"
    repo = SQLiteAuthRepository(db_path)
    repo.initialize()
    repo.create_credential(hash_password("OldPassword1234"))

    inputs = iter(["PasswordOne1234", "PasswordTwo5678"])
    exit_code = reset_password(db_path, password_getter=lambda prompt: next(inputs))
    assert exit_code == 2


def test_cli_password_reset_short_password(tmp_path: Path) -> None:
    db_path = tmp_path / "inventory.db"
    repo = SQLiteAuthRepository(db_path)
    repo.initialize()
    repo.create_credential(hash_password("OldPassword1234"))

    inputs = iter(["short", "short"])
    exit_code = reset_password(db_path, password_getter=lambda prompt: next(inputs))
    assert exit_code == 3
