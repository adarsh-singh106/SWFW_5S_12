"""Single-operator loopback API authentication."""

import hashlib
import re
import secrets
from typing import Annotated

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fleet_manager.errors import AuthenticationError

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}", re.ASCII)
_BEARER = HTTPBearer(
    auto_error=False,
    scheme_name="OperatorToken",
    description="Single-operator development token; set it outside the repository.",
)


def require_operator_token(
    request: Request,
    _parsed: Annotated[HTTPAuthorizationCredentials | None, Security(_BEARER)],
) -> None:
    """Deny malformed or incorrect credentials without echoing submitted values."""
    headers = request.headers.getlist("authorization")
    if len(headers) != 1:
        raise AuthenticationError

    scheme, separator, token = headers[0].partition(" ")
    if separator != " " or scheme.lower() != "bearer" or _TOKEN_PATTERN.fullmatch(token) is None:
        raise AuthenticationError

    expected = getattr(request.app.state, "operator_token_digest", None)
    if not isinstance(expected, bytes):
        raise AuthenticationError
    submitted = hashlib.sha256(token.encode("ascii")).digest()
    if not secrets.compare_digest(submitted, expected):
        raise AuthenticationError
