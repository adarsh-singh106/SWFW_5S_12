"""Pydantic schemas for the remote operations HTTP contract."""

from typing import Any

from pydantic import BaseModel, Field

from fleet_manager.operations.models import OperationRecord


class ExecuteOperationRequest(BaseModel):
    action: str = Field(..., description="Allowlisted operation identifier")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Typed arguments validated by catalog"
    )


class OperationRecordResponse(BaseModel):
    id: str
    node_id: int
    action: str
    arguments: dict[str, Any]
    requested_at: str
    started_at: str | None
    completed_at: str | None
    outcome: str
    failure_category: str | None
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    output_truncated: bool
    audit_metadata: dict[str, Any]

    @classmethod
    def from_record(cls, record: OperationRecord) -> "OperationRecordResponse":
        return cls(
            id=record.id,
            node_id=record.node_id,
            action=record.action,
            arguments=record.arguments,
            requested_at=record.requested_at.isoformat(),
            started_at=record.started_at.isoformat() if record.started_at else None,
            completed_at=record.completed_at.isoformat() if record.completed_at else None,
            outcome=record.outcome.value,
            failure_category=record.failure_category.value if record.failure_category else None,
            exit_code=record.exit_code,
            stdout=record.stdout,
            stderr=record.stderr,
            output_truncated=record.output_truncated,
            audit_metadata=record.audit_metadata,
        )


class OperationListResponse(BaseModel):
    operations: list[OperationRecordResponse]
