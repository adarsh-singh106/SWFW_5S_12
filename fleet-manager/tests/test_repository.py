"""Database guarantees that HTTP validation alone cannot provide."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from fleet_manager.errors import DuplicateNode, StorageError
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.inventory.service import NodeService


def test_database_rejects_invalid_port_even_without_api(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.db"
    SQLiteNodeRepository(database_path).initialize()
    with sqlite3.connect(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO nodes (name, address, ssh_port) VALUES (?, ?, ?)",
                ("node", "192.0.2.40", 0),
            )


def test_concurrent_duplicate_registration_has_one_winner(tmp_path: Path) -> None:
    repository = SQLiteNodeRepository(tmp_path / "inventory.db")
    repository.initialize()
    service = NodeService(repository)
    start = Barrier(2)

    def register() -> str:
        start.wait(timeout=5)
        try:
            service.register("node", "node.example", 22)
            return "created"
        except DuplicateNode:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _index: register(), range(2)))

    assert sorted(results) == ["created", "duplicate"]
    assert len(service.list_nodes()) == 1


def test_existing_unversioned_table_is_not_silently_adopted(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE nodes (id INTEGER PRIMARY KEY)")
    with pytest.raises(StorageError, match="explicit migration"):
        SQLiteNodeRepository(database_path).initialize()
