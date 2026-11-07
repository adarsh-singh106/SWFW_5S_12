"""Single-operator API and browser session authentication."""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Annotated, Final

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fleet_manager.errors import AuthenticationError
from fleet_manager.security.session import SESSION_COOKIE_NAME, SessionStore, validate_csrf

_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_-]{32,128}", re.ASCII)
_BEARER: Final[HTTPBearer] = HTTPBearer(
    auto_error=False,
    scheme_name="OperatorToken",
    description="Single-operator development token; set it outside the repository.",
)

_STATE_CHANGING_METHODS: Final[set[str]] = {"POST", "PUT", "DELETE", "PATCH"}
_PASSWORD_CHANGE_ALLOWED_PATHS: Final[set[str]] = {
    "/api/auth/change-password",
    "/api/auth/session",
    "/api/auth/logout",
    "/api/auth/status",
}


def require_operator_token(
    request: Request,
    _parsed: Annotated[HTTPAuthorizationCredentials | None, Security(_BEARER)],
) -> None:
    """Authenticate request via Bearer token or server-managed browser session.

    Enforces:
      1. Programmatic clients: strictly validated single Authorization Bearer header.
      2. Browser dashboard clients: HttpOnly session cookie, bounded idle/absolute expiry,
         mandatory password change restrictions, and CSRF protection on state-changing requests.
    """
    headers = request.headers.getlist("authorization")
    if headers:
        if len(headers) != 1:
            raise AuthenticationError

        scheme, separator, token = headers[0].partition(" ")
        if (
            separator != " "
            or scheme.lower() != "bearer"
            or _TOKEN_PATTERN.fullmatch(token) is None
        ):
            raise AuthenticationError

        expected = getattr(request.app.state, "operator_token_digest", None)
        if not isinstance(expected, bytes):
            raise AuthenticationError
        submitted = hashlib.sha256(token.encode("ascii")).digest()
        if not secrets.compare_digest(submitted, expected):
            raise AuthenticationError
        return

    # Check for server-managed session cookie
    raw_session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_session_token:
        raise AuthenticationError

    session_store: SessionStore | None = getattr(request.app.state, "session_store", None)
    if session_store is None:
        raise AuthenticationError

    session = session_store.get_session(raw_session_token)
    if session is None:
        raise AuthenticationError

    # Restrict protected dashboard operations if password change is mandatory
    if session.must_change_password and request.url.path not in _PASSWORD_CHANGE_ALLOWED_PATHS:
        raise AuthenticationError

    # State-changing requests authenticated via cookie require strict CSRF validation
    if request.method in _STATE_CHANGING_METHODS:
        validate_csrf(request, session)

    request.state.session = session
    request.state.raw_session_token = raw_session_token
