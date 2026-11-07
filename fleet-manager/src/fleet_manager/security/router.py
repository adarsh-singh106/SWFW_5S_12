"""HTTP routes for administrator authentication, session lifecycle, and password setup."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from fleet_manager.inventory.schemas import ErrorResponse
from fleet_manager.security.passwords import (
    hash_password,
    validate_password_bounds,
    verify_password,
)
from fleet_manager.security.repository import SQLiteAuthRepository
from fleet_manager.security.schemas import (
    AuthActionResponse,
    AuthSessionResponse,
    ChangePasswordRequest,
    LoginRequest,
    SetupRequest,
    StatusResponse,
)
from fleet_manager.security.session import (
    SESSION_COOKIE_NAME,
    LoginRateLimiter,
    SessionStore,
    is_secure_request,
    validate_csrf,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_LOOPBACK_IPS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Report whether first-run setup or password change is required",
)
def get_auth_status(request: Request) -> StatusResponse:
    auth_repo: SQLiteAuthRepository = request.app.state.auth_repository
    credential = auth_repo.get_credential()
    if credential is None:
        return StatusResponse(setup_required=True, password_change_required=False)
    return StatusResponse(
        setup_required=False,
        password_change_required=credential.must_change_password,
    )


@router.post(
    "/setup",
    response_model=AuthActionResponse,
    responses={
        200: {"description": "Administrator credential created and session established"},
        403: {"model": ErrorResponse, "description": "Setup is only permitted from loopback"},
        409: {"model": ErrorResponse, "description": "Administrator setup already completed"},
        422: {"model": ErrorResponse, "description": "Password bounds or confirmation mismatch"},
    },
    summary="Create initial administrator credential from loopback",
)
def setup_administrator(body: SetupRequest, request: Request, response: Response) -> Response:
    host = _client_host(request)
    if host not in _LOOPBACK_IPS:
        return _error(403, "forbidden", "Initial administrator setup is restricted to loopback")

    auth_repo: SQLiteAuthRepository = request.app.state.auth_repository
    if auth_repo.has_credential():
        return _error(
            409, "setup_already_completed", "Administrator setup has already been completed"
        )

    if body.password != body.confirm_password:
        return _error(422, "password_mismatch", "Passwords do not match")

    try:
        validate_password_bounds(body.password)
    except ValueError as exc:
        return _error(422, "invalid_password", str(exc))

    hashed = hash_password(body.password)
    auth_repo.create_credential(hashed, must_change_password=False)

    session_store: SessionStore = request.app.state.session_store
    raw_token, csrf_token = session_store.create_session(must_change_password=False)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="lax",
        path="/",
        secure=is_secure_request(request),
    )
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "must_change_password": False,
            "csrf_token": csrf_token,
            "message": "Administrator setup completed",
        },
        headers=dict(response.headers),
    )


@router.post(
    "/login",
    response_model=AuthActionResponse,
    responses={
        200: {"description": "Session cookie issued"},
        401: {"model": ErrorResponse, "description": "Invalid administrator password"},
        403: {
            "model": ErrorResponse,
            "description": "Bootstrap placeholder login restricted to loopback",
        },
        422: {"model": ErrorResponse, "description": "Invalid login request"},
        429: {
            "model": ErrorResponse,
            "description": "Rate limited due to excessive failed attempts",
        },
    },
    summary="Authenticate administrator and issue server-managed session cookie",
)
def login(body: LoginRequest, request: Request, response: Response) -> Response:
    source_ip = _client_host(request)
    rate_limiter: LoginRateLimiter = request.app.state.login_rate_limiter

    if rate_limiter.is_rate_limited(source_ip):
        return _error(
            429, "rate_limited", "Too many failed login attempts. Please try again later."
        )

    auth_repo: SQLiteAuthRepository = request.app.state.auth_repository
    credential = auth_repo.get_credential()
    if credential is None:
        rate_limiter.record_failure(source_ip)
        return _error(401, "unauthorized", "Invalid administrator password")

    # Insecure placeholder bootstrap must not be accessible remotely
    if credential.must_change_password and source_ip not in _LOOPBACK_IPS:
        return _error(403, "forbidden", "Bootstrap authentication is restricted to loopback")

    if not verify_password(body.password, credential.password_hash):
        rate_limiter.record_failure(source_ip)
        return _error(401, "unauthorized", "Invalid administrator password")

    rate_limiter.reset(source_ip)
    session_store: SessionStore = request.app.state.session_store
    raw_token, csrf_token = session_store.create_session(
        must_change_password=credential.must_change_password
    )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="lax",
        path="/",
        secure=is_secure_request(request),
    )
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "must_change_password": credential.must_change_password,
            "csrf_token": csrf_token,
            "message": "Authentication successful",
        },
        headers=dict(response.headers),
    )


@router.get(
    "/session",
    response_model=AuthSessionResponse,
    summary="Report authenticated state and supply CSRF token",
)
def get_session(request: Request) -> AuthSessionResponse:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    session_store: SessionStore = request.app.state.session_store
    session = session_store.get_session(raw_token)
    if session is None:
        return AuthSessionResponse(authenticated=False)
    return AuthSessionResponse(
        authenticated=True,
        must_change_password=session.must_change_password,
        csrf_token=session.csrf_token,
    )


@router.post(
    "/change-password",
    response_model=AuthActionResponse,
    responses={
        200: {"description": "Password updated, other sessions revoked, current session rotated"},
        401: {
            "model": ErrorResponse,
            "description": "Session unauthorized or current password incorrect",
        },
        422: {"model": ErrorResponse, "description": "Invalid new password or mismatch"},
    },
    summary="Change administrator password, invalidate other sessions, and rotate current session",
)
def change_password(body: ChangePasswordRequest, request: Request, response: Response) -> Response:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    session_store: SessionStore = request.app.state.session_store
    session = session_store.get_session(raw_token)
    if session is None:
        return _error(401, "unauthorized", "Authentication required")

    try:
        validate_csrf(request, session)
    except Exception:
        return _error(401, "unauthorized", "CSRF verification failed")

    if body.new_password != body.confirm_password:
        return _error(422, "password_mismatch", "New passwords do not match")

    if body.new_password == body.current_password:
        return _error(422, "same_password", "New password must be different from current password")

    if body.new_password == "CHANGEME":
        return _error(422, "insecure_password", "Cannot use placeholder password CHANGEME")

    try:
        validate_password_bounds(body.new_password)
    except ValueError as exc:
        return _error(422, "invalid_password", str(exc))

    auth_repo: SQLiteAuthRepository = request.app.state.auth_repository
    credential = auth_repo.get_credential()
    if credential is None or not verify_password(body.current_password, credential.password_hash):
        return _error(401, "unauthorized", "Current password is incorrect")

    new_hash = hash_password(body.new_password)
    auth_repo.update_password(new_hash, must_change_password=False)

    # Invalidate other active sessions and rotate the current session
    assert raw_token is not None
    session_store.revoke_all_except(raw_token)
    new_raw_token, new_csrf = session_store.rotate_session(raw_token, must_change_password=False)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=new_raw_token,
        httponly=True,
        samesite="lax",
        path="/",
        secure=is_secure_request(request),
    )
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "must_change_password": False,
            "csrf_token": new_csrf,
            "message": "Password updated successfully",
        },
        headers=dict(response.headers),
    )


@router.post(
    "/logout",
    response_model=AuthActionResponse,
    summary="Revoke current session and clear cookie",
)
def logout(request: Request, response: Response) -> Response:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    session_store: SessionStore = request.app.state.session_store
    if raw_token:
        session = session_store.get_session(raw_token)
        if session:
            try:
                validate_csrf(request, session)
            except Exception:
                return _error(401, "unauthorized", "CSRF verification failed")
        session_store.revoke_session(raw_token)

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return JSONResponse(
        status_code=200,
        content={"ok": True, "message": "Session terminated"},
        headers=dict(response.headers),
    )
