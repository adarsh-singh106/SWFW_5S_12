"""Versioned SQLite storage for append-only SSH observations."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
from fleet_manager.errors import StorageError

_SCHEMA = """
CREATE TABLE connectivity_observations (
    id INTEGER PRIMARY KEY,
    node_id INTEGER NOT NULL REFERENCES nodes(id),
    observed_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    error_category TEXT,
    CHECK ((outcome = 'CONNECTED' AND error_category IS NULL)
        OR (outcome != 'CONNECTED' AND error_category = outcome))
)
"""


def _observation_from_row(row: sqlite3.Row) -> ConnectivityObservation:
    try:
        category = row["error_category"]
        return ConnectivityObservation(
            id=int(row["id"]),
            node_id=int(row["node_id"]),
            observed_at=datetime.fromisoformat(str(row["observed_at"])),
            outcome=ConnectivityOutcome(row["outcome"]),
            error_category=ConnectivityOutcome(category) if category is not None else None,
        )
    except (KeyError, ValueError) as exc:
        raise StorageError("Inventory contains an invalid connectivity observation") from exc


class SQLiteConnectivityRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Upgrade an existing version-1 inventory without changing its node rows."""
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                    exists = (
                        connection.execute(
                            "SELECT 1 FROM sqlite_master "
                            "WHERE type = 'table' AND name = 'connectivity_observations'"
                        ).fetchone()
                        is not None
                    )
                    if version == 1 and not exists:
                        connection.execute(_SCHEMA)
                        connection.execute("PRAGMA user_version = 2")
                    elif version not in (2, 3) or not exists:
                        raise StorageError("Inventory schema requires an explicit migration")
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except sqlite3.Error as exc:
            raise StorageError("Could not initialize connectivity storage") from exc

    def save(
        self, node_id: int, observed_at: datetime, outcome: ConnectivityOutcome
    ) -> ConnectivityObservation:
        if observed_at.utcoffset() is None:
            raise ValueError("Observation timestamp must include a timezone")
        observed_at = observed_at.astimezone(UTC)
        category = None if outcome is ConnectivityOutcome.CONNECTED else outcome.value
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        "INSERT INTO connectivity_observations "
                        "(node_id, observed_at, outcome, error_category) VALUES (?, ?, ?, ?)",
                        (node_id, observed_at.isoformat(), outcome.value, category),
                    )
                    row = connection.execute(
                        "SELECT id, node_id, observed_at, outcome, error_category "
                        "FROM connectivity_observations WHERE id = ?",
                        (cursor.lastrowid,),
                    ).fetchone()
                    if row is None:
                        raise StorageError("Saved observation could not be read back")
                    result = _observation_from_row(row)
                return result
        except sqlite3.Error as exc:
            raise StorageError("Could not save connectivity observation") from exc

    def latest(self, node_id: int) -> ConnectivityObservation | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT id, node_id, observed_at, outcome, error_category "
                    "FROM connectivity_observations WHERE node_id = ? ORDER BY id DESC LIMIT 1",
                    (node_id,),
                ).fetchone()
                return _observation_from_row(row) if row is not None else None
        except sqlite3.Error as exc:
            raise StorageError("Could not read connectivity observation") from exc
