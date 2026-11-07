"""Data models for administrator credentials and sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AdministratorCredential:
    id: int
    password_hash: str
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SessionData:
    verifier: bytes
    csrf_token: str
    created_at: float
    last_activity_at: float
    must_change_password: bool
