"""In-memory session management, CSRF validation, and login rate limiting."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

from fastapi import Request

from fleet_manager.security.models import SessionData

SESSION_COOKIE_NAME: Final[str] = "fleet_session"
DEFAULT_IDLE_TIMEOUT_SECONDS: Final[float] = 1800.0  # 30 minutes
DEFAULT_ABSOLUTE_TIMEOUT_SECONDS: Final[float] = 43200.0  # 12 hours


def is_secure_request(request: Request) -> bool:
    """Determine if request arrived over HTTPS without trusting arbitrary forwarded headers."""
    if request.url.scheme == "https":
        return True
    if request.scope.get("scheme") == "https":
        return True
    return False


class SessionStore:
    """Single-worker in-memory session verifier store.

    Stores only SHA-256 verifiers of session secrets to prevent credential extraction
    from server-side memory dumps.
    """

    def __init__(
        self,
        idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
        absolute_timeout_seconds: float = DEFAULT_ABSOLUTE_TIMEOUT_SECONDS,
    ) -> None:
        self._idle_timeout_seconds = idle_timeout_seconds
        self._absolute_timeout_seconds = absolute_timeout_seconds
        self._sessions: dict[bytes, SessionData] = {}

    @staticmethod
    def _verifier(raw_token: str) -> bytes:
        return hashlib.sha256(raw_token.encode("ascii")).digest()

    def create_session(self, must_change_password: bool = False) -> tuple[str, str]:
        """Create a new session; returns (raw_session_token, csrf_token)."""
        raw_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        verifier = self._verifier(raw_token)
        now = time.monotonic()
        data = SessionData(
            verifier=verifier,
            csrf_token=csrf_token,
            created_at=now,
            last_activity_at=now,
            must_change_password=must_change_password,
        )
        self._sessions[verifier] = data
        return raw_token, csrf_token

    def get_session(self, raw_token: str | None) -> SessionData | None:
        """Retrieve active session if valid, updating last_activity_at.

        Expires idle and absolute sessions.
        """
        if not raw_token:
            return None
        verifier = self._verifier(raw_token)
        session = self._sessions.get(verifier)
        if session is None:
            return None

        now = time.monotonic()
        if (now - session.created_at) > self._absolute_timeout_seconds:
            self._sessions.pop(verifier, None)
            return None
        if (now - session.last_activity_at) > self._idle_timeout_seconds:
            self._sessions.pop(verifier, None)
            return None

        # Touch last activity
        refreshed = SessionData(
            verifier=session.verifier,
            csrf_token=session.csrf_token,
            created_at=session.created_at,
            last_activity_at=now,
            must_change_password=session.must_change_password,
        )
        self._sessions[verifier] = refreshed
        return refreshed

    def revoke_session(self, raw_token: str | None) -> None:
        """Revoke a specific session."""
        if raw_token:
            self._sessions.pop(self._verifier(raw_token), None)

    def revoke_all_except(self, current_raw_token: str) -> None:
        """Revoke all sessions except the specified current session."""
        current_verifier = self._verifier(current_raw_token)
        to_remove = [v for v in self._sessions if v != current_verifier]
        for v in to_remove:
            self._sessions.pop(v, None)

    def rotate_session(
        self, current_raw_token: str, must_change_password: bool = False
    ) -> tuple[str, str]:
        """Safely rotate the current session identifier and CSRF token."""
        self.revoke_session(current_raw_token)
        return self.create_session(must_change_password=must_change_password)

    def clear(self) -> None:
        """Clear all active sessions (e.g. on shutdown)."""
        self._sessions.clear()


@dataclass(slots=True)
class RateLimitEntry:
    attempts: int
    first_attempt_time: float
    blocked_until: float


class LoginRateLimiter:
    """Bounded per-source failed login rate limiter to protect against brute-force attacks."""

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: float = 60.0,
        lockout_seconds: float = 300.0,
        max_tracked_sources: int = 1000,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self.max_tracked_sources = max_tracked_sources
        self._records: OrderedDict[str, RateLimitEntry] = OrderedDict()

    def is_rate_limited(self, source_ip: str) -> bool:
        """Check if source IP is currently locked out."""
        now = time.monotonic()
        entry = self._records.get(source_ip)
        if entry is None:
            return False
        if entry.blocked_until > now:
            return True
        if (now - entry.first_attempt_time) > self.window_seconds:
            self._records.pop(source_ip, None)
            return False
        return False

    def record_failure(self, source_ip: str) -> bool:
        """Record a failed attempt. Returns True if now rate limited."""
        now = time.monotonic()
        entry = self._records.get(source_ip)
        if entry is None:
            # Enforce bounded capacity
            if len(self._records) >= self.max_tracked_sources:
                self._records.popitem(last=False)
            entry = RateLimitEntry(attempts=1, first_attempt_time=now, blocked_until=0.0)
            self._records[source_ip] = entry
            return False

        self._records.move_to_end(source_ip)
        if (now - entry.first_attempt_time) > self.window_seconds:
            entry.attempts = 1
            entry.first_attempt_time = now
            entry.blocked_until = 0.0
            return False

        entry.attempts += 1
        if entry.attempts >= self.max_attempts:
            entry.blocked_until = now + self.lockout_seconds
            return True
        return False

    def reset(self, source_ip: str) -> None:
        """Reset failed attempt counters upon successful authentication."""
        self._records.pop(source_ip, None)


def validate_csrf(request: Request, session: SessionData) -> None:
    """Verify CSRF token and Origin/Referer on state-changing requests."""
    # 1. Strict Origin / Referer check
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    expected_host = request.url.netloc
    if origin:
        parsed_origin = urlparse(origin)
        if parsed_origin.scheme != request.url.scheme or parsed_origin.netloc != expected_host:
            from fleet_manager.errors import AuthenticationError

            raise AuthenticationError
    elif referer:
        parsed_referer = urlparse(referer)
        if parsed_referer.scheme != request.url.scheme or parsed_referer.netloc != expected_host:
            from fleet_manager.errors import AuthenticationError

            raise AuthenticationError
    else:
        # State-changing browser requests must provide either Origin or Referer
        from fleet_manager.errors import AuthenticationError

        raise AuthenticationError

    # 2. Synchronizer token check
    submitted_token = request.headers.get("x-csrf-token")
    if not submitted_token or not secrets.compare_digest(submitted_token, session.csrf_token):
        from fleet_manager.errors import AuthenticationError

        raise AuthenticationError
