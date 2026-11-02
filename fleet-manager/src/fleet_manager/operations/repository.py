"""Versioned SQLite persistence for operation execution records."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from fleet_manager.errors import StorageError
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationFailureCategory,
    OperationOutcome,
    OperationRecord,
)

_SCHEMA = """
CREATE TABLE operation_executions (
    id TEXT PRIMARY KEY,
    node_id INTEGER NOT NULL REFERENCES nodes(id),
    action TEXT NOT NULL,
    arguments TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    outcome TEXT NOT NULL,
    failure_category TEXT,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    output_truncated INTEGER NOT NULL DEFAULT 0,
    audit_metadata TEXT NOT NULL,
    CHECK (outcome IN ('RUNNING', 'SUCCESS', 'FAILURE', 'TIMEOUT', 'UNCERTAIN')),
    CHECK (output_truncated IN (0, 1))
);
CREATE INDEX idx_operations_node_id ON operation_executions(node_id, id DESC);
"""


def _record_from_row(row: sqlite3.Row) -> OperationRecord:
    try:
        failure_cat = row["failure_category"]
        started = row["started_at"]
        completed = row["completed_at"]
        return OperationRecord(
            id=str(row["id"]),
            node_id=int(row["node_id"]),
            action=str(row["action"]),
            arguments=json.loads(str(row["arguments"])),
            requested_at=datetime.fromisoformat(str(row["requested_at"])),
            started_at=datetime.fromisoformat(str(started)) if started else None,
            completed_at=datetime.fromisoformat(str(completed)) if completed else None,
            outcome=OperationOutcome(row["outcome"]),
            failure_category=OperationFailureCategory(failure_cat) if failure_cat else None,
            exit_code=int(row["exit_code"]) if row["exit_code"] is not None else None,
            stdout=str(row["stdout"]) if row["stdout"] is not None else None,
            stderr=str(row["stderr"]) if row["stderr"] is not None else None,
            output_truncated=bool(row["output_truncated"]),
            audit_metadata=json.loads(str(row["audit_metadata"])),
        )
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise StorageError("Storage contains an invalid operation record") from exc


class SQLiteOperationsRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Upgrade version-2 inventory to version-3 with operation_executions table."""
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                    exists = (
                        connection.execute(
                            "SELECT 1 FROM sqlite_master "
                            "WHERE type = 'table' AND name = 'operation_executions'"
                        ).fetchone()
                        is not None
                    )
                    if version == 2 and not exists:
                        connection.executescript(_SCHEMA)
                        connection.execute("PRAGMA user_version = 3")
                    elif version != 3 or not exists:
                        raise StorageError("Inventory schema requires an explicit migration")
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except sqlite3.Error as exc:
            raise StorageError("Could not initialize operations storage") from exc

    def reconcile_in_flight(self) -> int:
        """Mark any leftover RUNNING operations as UNCERTAIN after a control-plane restart."""
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        "UPDATE operation_executions "
                        "SET outcome = 'UNCERTAIN', failure_category = 'CONTROL_PLANE_RESTARTED', "
                        "completed_at = ? WHERE outcome = 'RUNNING'",
                        (now,),
                    )
                    return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageError("Could not reconcile in-flight operations") from exc

    def create(self, record: OperationRecord) -> OperationRecord:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO operation_executions ("
                        "id, node_id, action, arguments, requested_at, started_at, completed_at, "
                        "outcome, failure_category, exit_code, stdout, stderr, "
                        "output_truncated, audit_metadata"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            record.id,
                            record.node_id,
                            record.action,
                            json.dumps(record.arguments),
                            record.requested_at.isoformat(),
                            record.started_at.isoformat() if record.started_at else None,
                            record.completed_at.isoformat() if record.completed_at else None,
                            record.outcome.value,
                            record.failure_category.value if record.failure_category else None,
                            record.exit_code,
                            record.stdout,
                            record.stderr,
                            1 if record.output_truncated else 0,
                            json.dumps(record.audit_metadata),
                        ),
                    )
                    return record
        except sqlite3.Error as exc:
            raise StorageError("Could not record operation request") from exc

    def update_completion(
        self,
        operation_id: str,
        started_at: datetime | None,
        completed_at: datetime,
        result: OperationExecutionResult,
    ) -> OperationRecord:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        "UPDATE operation_executions SET "
                        "started_at = ?, completed_at = ?, outcome = ?, failure_category = ?, "
                        "exit_code = ?, stdout = ?, stderr = ?, output_truncated = ? "
                        "WHERE id = ?",
                        (
                            started_at.isoformat() if started_at else None,
                            completed_at.isoformat(),
                            result.outcome.value,
                            result.failure_category.value if result.failure_category else None,
                            result.exit_code,
                            result.stdout,
                            result.stderr,
                            1 if result.output_truncated else 0,
                            operation_id,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM operation_executions WHERE id = ?",
                        (operation_id,),
                    ).fetchone()
                    if row is None:
                        raise StorageError("Updated operation record could not be read back")
                    return _record_from_row(row)
        except sqlite3.Error as exc:
            raise StorageError("Could not update operation record") from exc

    def get(self, operation_id: str) -> OperationRecord | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM operation_executions WHERE id = ?",
                    (operation_id,),
                ).fetchone()
                return _record_from_row(row) if row is not None else None
        except sqlite3.Error as exc:
            raise StorageError("Could not read operation record") from exc

    def list_for_node(self, node_id: int, limit: int = 50) -> list[OperationRecord]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT * FROM operation_executions WHERE node_id = ? "
                    "ORDER BY requested_at DESC, id DESC LIMIT ?",
                    (node_id, limit),
                ).fetchall()
                return [_record_from_row(row) for row in rows]
        except sqlite3.Error as exc:
            raise StorageError("Could not list operation records") from exc
