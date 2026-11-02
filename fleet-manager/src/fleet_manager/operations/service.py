"""Application service coordinating node operation authorization, execution, and persistence."""

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from fleet_manager.metrics.telemetry import Telemetry


class OperationService:
    """Coordinates allowlisted action validation, admission, remote execution, and audit trail."""

    def __init__(
        self,
        inventory_repository: SQLiteNodeRepository,
        operations_repository: SQLiteOperationsRepository,
        executor: OperationExecutor,
        ssh_settings: SSHSettings | None = None,
        telemetry: "Telemetry | None" = None,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.inventory_repository = inventory_repository
        self.operations_repository = operations_repository
        self.executor = executor
        self.ssh_settings = ssh_settings
        self.telemetry = telemetry
        self._monotonic_clock = monotonic_clock

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
        admitted = False
        start_mono: float | None = None

        def on_start() -> None:
            nonlocal started_at, admitted, start_mono
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
            start_mono = self._monotonic_clock()
            if self.telemetry is not None:
                self.telemetry.operations_active.inc(labels={"action": validated.action})
                admitted = True

        try:
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
                    terminal_outcome = (
                        OperationOutcome.FAILURE
                        if configuration_failure
                        else OperationOutcome.UNCERTAIN
                    )
                    try:
                        self.operations_repository.update_completion(
                            operation_id=operation_id,
                            started_at=started_at,
                            completed_at=datetime.now(UTC),
                            result=OperationExecutionResult(
                                outcome=terminal_outcome,
                                failure_category=OperationFailureCategory.UNAVAILABLE,
                                exit_code=None,
                                stdout=None,
                                stderr="Operation worker failed before a confirmed result",
                                output_truncated=False,
                            ),
                        )
                    except Exception:
                        pass

                    if self.telemetry is not None and start_mono is not None:
                        duration = max(0.0, self._monotonic_clock() - start_mono)
                        self.telemetry.operations_total.inc(
                            labels={"action": validated.action, "outcome": terminal_outcome.value}
                        )
                        self.telemetry.operation_duration_seconds.observe(
                            duration,
                            labels={"action": validated.action, "outcome": terminal_outcome.value},
                        )
                raise

            completed_at = datetime.now(UTC)
            duration = (
                max(0.0, self._monotonic_clock() - start_mono) if start_mono is not None else 0.0
            )
            try:
                record = self.operations_repository.update_completion(
                    operation_id=operation_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    result=result,
                )
            except Exception:
                if self.telemetry is not None:
                    # Remote execution finished, but storage failed.
                    self.telemetry.operations_total.inc(
                        labels={
                            "action": validated.action,
                            "outcome": OperationOutcome.UNCERTAIN.value,
                        }
                    )
                    self.telemetry.operation_duration_seconds.observe(
                        duration,
                        labels={
                            "action": validated.action,
                            "outcome": OperationOutcome.UNCERTAIN.value,
                        },
                    )
                raise

            if self.telemetry is not None:
                self.telemetry.operations_total.inc(
                    labels={"action": validated.action, "outcome": record.outcome.value}
                )
                self.telemetry.operation_duration_seconds.observe(
                    duration,
                    labels={"action": validated.action, "outcome": record.outcome.value},
                )
            return record
        finally:
            if admitted and self.telemetry is not None:
                self.telemetry.operations_active.dec(labels={"action": validated.action})

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        return self.operations_repository.get(operation_id)

    def list_operations_for_node(self, node_id: int, limit: int = 50) -> list[OperationRecord]:
        node = self.inventory_repository.get_node(node_id)
        if node is None:
            raise NodeNotFound(f"Node {node_id} is not registered")
        return self.operations_repository.list_for_node(node_id, limit=limit)
