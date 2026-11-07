"""SQLite persistence and schema evolution for administrator credentials."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from fleet_manager.errors import StorageError
from fleet_manager.security.models import AdministratorCredential

_SCHEMA = """
CREATE TABLE administrator_credentials (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    password_hash TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _credential_from_row(row: sqlite3.Row) -> AdministratorCredential:
    try:
        return AdministratorCredential(
            id=int(row["id"]),
            password_hash=str(row["password_hash"]),
            must_change_password=bool(row["must_change_password"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
    except (KeyError, ValueError) as exc:
        raise StorageError("Authentication storage contains an invalid credential record") from exc


class SQLiteAuthRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Upgrade version-5 database to version-6 with administrator_credentials table."""
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                    exists = (
                        connection.execute(
                            "SELECT 1 FROM sqlite_master "
                            "WHERE type = 'table' AND name = 'administrator_credentials'"
                        ).fetchone()
                        is not None
                    )
                    if version in (0, 1, 2, 3, 4, 5) and not exists:
                        connection.execute(_SCHEMA)
                        connection.execute("PRAGMA user_version = 6")
                    elif version != 6 or not exists:
                        raise StorageError("Authentication schema requires an explicit migration")
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except (OSError, sqlite3.Error) as exc:
            raise StorageError("Could not initialize authentication storage") from exc

    def get_credential(self) -> AdministratorCredential | None:
        """Retrieve the single administrator credential record, or None if uninitialized."""
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT id, password_hash, must_change_password, created_at, updated_at "
                    "FROM administrator_credentials WHERE id = 1"
                ).fetchone()
                return _credential_from_row(row) if row is not None else None
        except sqlite3.Error as exc:
            raise StorageError("Could not read administrator credential") from exc

    def has_credential(self) -> bool:
        """Return True if an administrator credential exists in persistent storage."""
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT 1 FROM administrator_credentials WHERE id = 1"
                ).fetchone()
                return row is not None
        except sqlite3.Error as exc:
            raise StorageError("Could not verify administrator credential presence") from exc

    def create_credential(
        self, password_hash: str, must_change_password: bool = False
    ) -> AdministratorCredential:
        """Persist the initial administrator credential. Fails if one already exists."""
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        "INSERT INTO administrator_credentials "
                        "(id, password_hash, must_change_password, created_at, updated_at) "
                        "VALUES (1, ?, ?, ?, ?)",
                        (password_hash, 1 if must_change_password else 0, now, now),
                    )
                    row = connection.execute(
                        "SELECT id, password_hash, must_change_password, created_at, updated_at "
                        "FROM administrator_credentials WHERE id = ?",
                        (cursor.lastrowid,),
                    ).fetchone()
                    if row is None:
                        raise StorageError("Failed to retrieve created credential record")
                    return _credential_from_row(row)
        except sqlite3.IntegrityError as exc:
            raise StorageError("Administrator credential already exists") from exc
        except sqlite3.Error as exc:
            raise StorageError("Could not store administrator credential") from exc

    def update_password(self, password_hash: str, must_change_password: bool = False) -> None:
        """Update the administrator password hash and reset must_change_password flag."""
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        "UPDATE administrator_credentials "
                        "SET password_hash = ?, must_change_password = ?, updated_at = ? "
                        "WHERE id = 1",
                        (password_hash, 1 if must_change_password else 0, now),
                    )
                    if cursor.rowcount == 0:
                        raise StorageError(
                            "Cannot update password: no administrator credential exists"
                        )
        except sqlite3.Error as exc:
            raise StorageError("Could not update administrator password") from exc
