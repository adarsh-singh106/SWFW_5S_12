"""Deterministic Phase 10 recovery regressions; no external services."""

import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

import paramiko
import pytest

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.errors import StorageError
from fleet_manager.inventory.models import Node, ObservationState
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.operations.models import OperationOutcome
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.transport import ParamikoOperationTransport


@pytest.mark.parametrize("statement", ["CREATE INDEX", "PRAGMA user_version = 3"])
def test_migration_failure_preserves_v2(tmp_path, monkeypatch, statement):
    path = tmp_path / "inventory.db"
    SQLiteNodeRepository(path).initialize()
    SQLiteConnectivityRepository(path).initialize()

    class Interrupted(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if statement in sql:
                raise sqlite3.OperationalError("injected interruption")
            return super().execute(sql, parameters)

        def executescript(self, sql):
            # Model interruption after SQLite's implicit pre-script commit.
            super().executescript(sql.split("CREATE INDEX")[0])
            raise sqlite3.OperationalError("injected interruption")

    repo = SQLiteOperationsRepository(path)
    monkeypatch.setattr(repo, "_connect", lambda: sqlite3.connect(path, factory=Interrupted))
    with pytest.raises(StorageError):
        repo.initialize()
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='operation_executions'"
        ).fetchall()


@pytest.mark.parametrize("lost_ack", [True, False])
def test_dispatch_without_confirmed_exit_is_uncertain(tmp_path, monkeypatch, lost_ack):
    client = MagicMock()
    client.__enter__.return_value = client
    channel = client.get_transport.return_value.open_session.return_value
    channel.recv_ready.return_value = False
    channel.recv_stderr_ready.return_value = False
    channel.exit_status_ready.return_value = True
    channel.recv_exit_status.return_value = -1
    if lost_ack:
        channel.exec_command.side_effect = EOFError("ack lost")
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(paramiko.PKey, "from_path", lambda _: MagicMock())
    result = ParamikoOperationTransport().execute(
        Node(1, "test", "192.0.2.1", 22, ObservationState.NOT_CHECKED),
        "uptime",
        SSHSettings("observer", tmp_path / "hosts", tmp_path / "key"),
    )
    assert result.outcome == OperationOutcome.UNCERTAIN
    assert channel.exec_command.call_count == 1


@pytest.mark.parametrize("version", [0, 99, 3])
def test_incompatible_restore_preserves_target_and_snapshot(tmp_path, version):
    from scripts.backup_restore import perform_restore

    backup = tmp_path / "unsupported.db"
    with closing(sqlite3.connect(backup)) as conn:
        conn.execute("CREATE TABLE unrelated (value TEXT)")
        conn.execute(f"PRAGMA user_version={version}")
        conn.commit()
    target = tmp_path / "target.db"
    SQLiteNodeRepository(target).initialize()
    before = target.read_bytes()
    snapshot = target.with_suffix(".db.pre_restore.bak")
    snapshot.write_bytes(b"preserve me")
    with pytest.raises(RuntimeError, match="Unsupported application"):
        perform_restore(backup, target, allow_missing_manifest=True)
    assert target.read_bytes() == before
    assert snapshot.read_bytes() == b"preserve me"


def test_backup_publication_and_recovery_failure_preserves_previous(tmp_path, monkeypatch):
    from scripts import backup_restore as backup

    source = tmp_path / "source.db"
    SQLiteNodeRepository(source).initialize()
    dest = tmp_path / "backup.db"
    backup.perform_backup(source, dest)
    original = dest.read_bytes()
    original_replace = backup._atomic_replace

    def fail_publication(source, target):
        if source.name.endswith(".staged") or source.name.endswith(".prev"):
            raise OSError("injected publication/recovery failure")
        original_replace(source, target)

    monkeypatch.setattr(backup, "_atomic_replace", fail_publication)
    with pytest.raises(OSError):
        backup.perform_backup(source, dest)
    assert dest.with_suffix(".db.prev").read_bytes() == original
    assert dest.with_suffix(".db.manifest.json.prev").exists()
    monkeypatch.setattr(backup, "_atomic_replace", original_replace)
    backup.recover_backup_generation(dest)
    assert dest.read_bytes() == original


def test_completion_recovers_without_replaying(client, monkeypatch):
    from fleet_manager.operations.models import OperationExecutionResult

    app = client.app
    service = app.state.operation_service
    service.ssh_settings = SSHSettings("observer", Path("hosts"), Path("key"))
    calls = []

    def run(**kwargs):
        calls.append(1)
        kwargs["on_start"]()
        return OperationExecutionResult(OperationOutcome.SUCCESS, None, 0, "ok", "", False)

    monkeypatch.setattr(service.executor, "run", run)
    repo = service.operations_repository
    original = repo.update_completion
    monkeypatch.setattr(repo, "update_completion", MagicMock(side_effect=StorageError("secret")))
    node = client.post(
        "/api/nodes", json={"name": "test", "address": "192.0.2.1", "ssh_port": 22}
    ).json()
    response = client.post(f"/api/nodes/{node['id']}/operations", json={"action": "system.uptime"})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["persisted_outcome"] == "RUNNING"
    assert "secret" not in response.text
    monkeypatch.setattr(repo, "update_completion", original)
    recovered = client.get(error["operation_url"])
    assert recovered.json()["id"] == error["operation_id"]
    assert recovered.json()["outcome"] == "UNCERTAIN"
    assert recovered.json()["stdout"] == "ok"
    assert calls == [1]


def test_worker_failure_exposes_durable_tracking_id(client, monkeypatch):
    service = client.app.state.operation_service
    service.ssh_settings = SSHSettings("observer", Path("hosts"), Path("key"))

    def run(**kwargs):
        kwargs["on_start"]()
        raise RuntimeError("sensitive failure")

    monkeypatch.setattr(service.executor, "run", run)
    node = client.post(
        "/api/nodes", json={"name": "test", "address": "192.0.2.1", "ssh_port": 22}
    ).json()
    response = client.post(f"/api/nodes/{node['id']}/operations", json={"action": "system.uptime"})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["persisted_outcome"] == "UNCERTAIN"
    assert client.get(error["operation_url"]).json()["id"] == error["operation_id"]
    assert "sensitive" not in response.text
