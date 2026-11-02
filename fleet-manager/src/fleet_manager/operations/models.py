"""Data models and execution records for controlled remote operations."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class OperationOutcome(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"
    UNCERTAIN = "UNCERTAIN"


class OperationFailureCategory(StrEnum):
    HOST_KEY_UNKNOWN = "HOST_KEY_UNKNOWN"
    HOST_KEY_MISMATCH = "HOST_KEY_MISMATCH"
    AUTH_FAILED = "AUTH_FAILED"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    DNS_ERROR = "DNS_ERROR"
    TIMEOUT = "TIMEOUT"
    COMMAND_ERROR = "COMMAND_ERROR"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    CONTROL_PLANE_RESTARTED = "CONTROL_PLANE_RESTARTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class OperationRecord:
    id: str
    node_id: int
    action: str
    arguments: dict[str, Any]
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    outcome: OperationOutcome
    failure_category: OperationFailureCategory | None
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    output_truncated: bool
    audit_metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OperationExecutionResult:
    outcome: OperationOutcome
    failure_category: OperationFailureCategory | None
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    output_truncated: bool
