"""Application service coordinating node operation authorization, execution, and persistence."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fleet_manager.config import SSHSettings, load_ssh_settings
from fleet_manager.errors import ConnectivityConfigurationError, NodeNotFound
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.operations.catalog import validate_action
from fleet_manager.operations.executor import OperationExecutor
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationFailureCategory,
    OperationOutcome,
    OperationRecord,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository


class OperationService:
    """Coordinates allowlisted action validation, admission, remote execution, and audit trail."""

    def __init__(
        self,
        inventory_repository: SQLiteNodeRepository,
        operations_repository: SQLiteOperationsRepository,
        executor: OperationExecutor,
        ssh_settings: SSHSettings | None = None,
    ) -> None:
        self.inventory_repository = inventory_repository
        self.operations_repository = operations_repository
        self.executor = executor
        self.ssh_settings = ssh_settings

    def execute(
        self,
        node_id: int,
        action: str,
        arguments: dict[str, Any] | None,
        operator_digest: bytes,
    ) -> OperationRecord:
        node = self.inventory_repository.get_node(node_id)
        if node is None:
            raise NodeNotFound(f"Node {node_id} is not registered")

        validated = validate_action(action, arguments)

        settings = self.ssh_settings
        if settings is None:
            try:
                settings = load_ssh_settings()
            except ConnectivityConfigurationError:
                raise

        operation_id = f"op_{uuid.uuid4().hex}"
        requested_at = datetime.now(UTC)
        audit_metadata = {
            "operator_type": "bearer_token",
            "operator_digest_prefix": operator_digest.hex()[:8],
        }

        started_at: datetime | None = None

        def on_start() -> None:
            nonlocal started_at
            start_time = datetime.now(UTC)
            initial_record = OperationRecord(
                id=operation_id,
                node_id=node.id,
                action=validated.action,
                arguments=validated.sanitized_arguments,
                requested_at=requested_at,
                started_at=start_time,
                completed_at=None,
                outcome=OperationOutcome.RUNNING,
                failure_category=None,
                exit_code=None,
                stdout=None,
                stderr=None,
                output_truncated=False,
                audit_metadata=audit_metadata,
            )
            self.operations_repository.create(initial_record)
            started_at = start_time

        try:
            result = self.executor.run(
                node=node,
                command=validated.remote_command,
                settings=settings,
                on_start=on_start,
            )
        except Exception as exc:
            if started_at is not None:
                # The worker may have dispatched the command before failing. Do not
                # leave a durable RUNNING row or claim the command never ran.
                configuration_failure = isinstance(exc, ConnectivityConfigurationError)
                self.operations_repository.update_completion(
                    operation_id=operation_id,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    result=OperationExecutionResult(
                        outcome=(
                            OperationOutcome.FAILURE
                            if configuration_failure
                            else OperationOutcome.UNCERTAIN
                        ),
                        failure_category=OperationFailureCategory.UNAVAILABLE,
                        exit_code=None,
                        stdout=None,
                        stderr="Operation worker failed before a confirmed result",
                        output_truncated=False,
                    ),
                )
            raise

        completed_at = datetime.now(UTC)
        return self.operations_repository.update_completion(
            operation_id=operation_id,
            started_at=started_at,
            completed_at=completed_at,
            result=result,
        )

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        return self.operations_repository.get(operation_id)

    def list_operations_for_node(self, node_id: int, limit: int = 50) -> list[OperationRecord]:
        node = self.inventory_repository.get_node(node_id)
        if node is None:
            raise NodeNotFound(f"Node {node_id} is not registered")
        return self.operations_repository.list_for_node(node_id, limit=limit)
