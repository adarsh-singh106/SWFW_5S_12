"""Pydantic request and response schemas for authentication operations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    setup_required: bool
    password_change_required: bool


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(..., min_length=12, max_length=128)
    confirm_password: str = Field(..., min_length=12, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=12, max_length=128)
    confirm_password: str = Field(..., min_length=12, max_length=128)


class AuthSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authenticated: bool
    must_change_password: bool = False
    csrf_token: str | None = None


class AuthActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    must_change_password: bool = False
    csrf_token: str | None = None
    message: str | None = None
