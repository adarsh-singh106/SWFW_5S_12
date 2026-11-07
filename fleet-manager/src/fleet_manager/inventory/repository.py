"""SQLite persistence for node inventory."""

import sqlite3
from contextlib import closing
from pathlib import Path

from fleet_manager.errors import DuplicateNode, StorageError
from fleet_manager.inventory.models import NewNode, Node, ObservationState

_SCHEMA = """
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 100),
    address TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(address)) > 0),
    ssh_port INTEGER NOT NULL CHECK (typeof(ssh_port) = 'integer' AND ssh_port BETWEEN 1 AND 65535),
    observation_state TEXT NOT NULL DEFAULT 'NOT_CHECKED',
    UNIQUE (address, ssh_port)
)
"""


def _node_from_row(row: sqlite3.Row) -> Node:
    try:
        return Node(
            id=int(row["id"]),
            name=str(row["name"]),
            address=str(row["address"]),
            ssh_port=int(row["ssh_port"]),
            observation_state=ObservationState(row["observation_state"]),
        )
    except (KeyError, ValueError) as exc:
        raise StorageError("Inventory contains an invalid node record") from exc


class SQLiteNodeRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Create the first schema atomically; refuse unknown pre-existing schemas."""
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                    exists = (
                        connection.execute(
                            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'nodes'"
                        ).fetchone()
                        is not None
                    )
                    if (exists and version not in (1, 2, 3, 4, 5, 6)) or (
                        not exists and version != 0
                    ):
                        raise StorageError("Inventory schema requires an explicit migration")
                    if not exists:
                        connection.execute(_SCHEMA)
                        connection.execute("PRAGMA user_version = 1")
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except (OSError, sqlite3.Error) as exc:
            raise StorageError("Could not initialize inventory storage") from exc

    def check_ready(self) -> None:
        """Verify storage accessibility and table presence without modifying state."""
        try:
            with closing(self._connect()) as connection:
                connection.execute("SELECT 1 FROM nodes LIMIT 1").fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise StorageError("Inventory storage is not ready") from exc

    def add_node(self, node: NewNode) -> Node:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        "INSERT INTO nodes (name, address, ssh_port) VALUES (?, ?, ?)",
                        (node.name, node.address, node.ssh_port),
                    )
                    row = connection.execute(
                        "SELECT id, name, address, ssh_port, observation_state "
                        "FROM nodes WHERE id = ?",
                        (cursor.lastrowid,),
                    ).fetchone()
                    if row is None:
                        raise StorageError("Inserted node could not be read back")
                    result = _node_from_row(row)
                return result
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise DuplicateNode("Node endpoint is already registered") from exc
            raise StorageError("Inventory rejected the node record") from exc
        except sqlite3.Error as exc:
            raise StorageError("Could not save node inventory") from exc

    def list_nodes(self) -> list[Node]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT id, name, address, ssh_port, observation_state FROM nodes ORDER BY id"
                ).fetchall()
                return [_node_from_row(row) for row in rows]
        except sqlite3.Error as exc:
            raise StorageError("Could not read node inventory") from exc

    def get_node(self, node_id: int) -> Node | None:
        """Find the registered endpoint used for a single connectivity check."""
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT id, name, address, ssh_port, observation_state FROM nodes WHERE id = ?",
                    (node_id,),
                ).fetchone()
                return _node_from_row(row) if row is not None else None
        except sqlite3.Error as exc:
            raise StorageError("Could not read node inventory") from exc
