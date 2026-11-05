"""Comprehensive tests for SQLite online backup, restore, integrity, and safety guarantees."""

import os
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts import backup_restore
from scripts.backup_restore import (
    PreRestoreSnapshotExistsError,
    calculate_sha256,
    check_integrity,
    perform_backup,
    perform_restore,
    recover_backup_generation,
)

from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.inventory.models import NewNode
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.operations.models import (
    OperationOutcome,
    OperationRecord,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository

SeededDB = tuple[
    Path,
    SQLiteNodeRepository,
    SQLiteConnectivityRepository,
    SQLiteOperationsRepository,
]


@pytest.fixture
def seeded_db(tmp_path: Path) -> SeededDB:
    """Create a fully initialized v3 database with records across all three tables."""
    db_path = tmp_path / "live_inventory.db"

    inv_repo = SQLiteNodeRepository(db_path)
    inv_repo.initialize()

    conn_repo = SQLiteConnectivityRepository(db_path)
    conn_repo.initialize()

    ops_repo = SQLiteOperationsRepository(db_path)
    ops_repo.initialize()

    # Seed records
    n1 = inv_repo.add_node(NewNode("web-01", "10.0.0.1", 22))
    n2 = inv_repo.add_node(NewNode("db-01", "10.0.0.2", 2222))

    now = datetime.now(UTC)
    conn_repo.save(n1.id, now, ConnectivityOutcome.CONNECTED)
    conn_repo.save(n2.id, now, ConnectivityOutcome.AUTH_FAILED)

    ops_repo.create(
        OperationRecord(
            id="op-101",
            node_id=n1.id,
            action="system.uptime",
            arguments={"detail": True},
            requested_at=now,
            started_at=now,
            completed_at=now,
            outcome=OperationOutcome.SUCCESS,
            failure_category=None,
            exit_code=0,
            stdout="up 4 days",
            stderr="",
            output_truncated=False,
            audit_metadata={"operator": "test"},
        )
    )

    return db_path, inv_repo, conn_repo, ops_repo


def test_backup_success_and_manifest_creation(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Online backup generates a valid point-in-time snapshot and manifest."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "backups" / "fleet_backup.db"

    manifest = perform_backup(source_db, backup_file)

    assert backup_file.exists()
    assert backup_file.is_file()
    assert backup_file.stat().st_size > 0

    # Manifest assertions
    manifest_path = backup_file.with_suffix(".db.manifest.json")
    assert manifest_path.exists()
    assert manifest["schema_user_version"] == 5
    assert manifest["sha256"] == calculate_sha256(backup_file)
    assert manifest["backup_size_bytes"] == backup_file.stat().st_size
    assert manifest["table_counts"] == {
        "connectivity_observations": 2,
        "nodes": 2,
        "operation_executions": 1,
        "connectivity_validation": 0,
    }


def test_missing_source_database_rejection(tmp_path: Path) -> None:
    """Non-existent source database raises FileNotFoundError without creating dummy file."""
    missing_source = tmp_path / "nonexistent.db"
    backup_file = tmp_path / "out.db"

    with pytest.raises(FileNotFoundError, match="does not exist"):
        perform_backup(missing_source, backup_file)

    assert not missing_source.exists()
    assert not backup_file.exists()


def test_empty_database_rejection(tmp_path: Path) -> None:
    """Zero-byte source file raises ValueError."""
    empty_source = tmp_path / "empty.db"
    empty_source.touch()
    backup_file = tmp_path / "out.db"

    with pytest.raises(ValueError, match="empty"):
        perform_backup(empty_source, backup_file)

    assert not backup_file.exists()


def test_backup_wal_mode_uncheckpointed_data(tmp_path: Path) -> None:
    """Committed transactions in WAL mode are captured safely in the backup snapshot."""
    db_path = tmp_path / "wal_db.db"
    repo = SQLiteNodeRepository(db_path)
    repo.initialize()

    # Enable WAL mode
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute(
            "INSERT INTO nodes (name, address, ssh_port) VALUES ('wal-node', '127.0.0.1', 22);"
        )
        conn.commit()

    # Ensure WAL file exists on disk
    wal_file = db_path.with_name(db_path.name + "-wal")
    assert wal_file.exists()

    backup_file = tmp_path / "wal_backup.db"
    perform_backup(db_path, backup_file)

    # Restored database contains WAL-committed record
    restored_db = tmp_path / "wal_restored.db"
    perform_restore(backup_file, restored_db)

    with sqlite3.connect(restored_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert "wal-node" in names


def test_all_three_schemas_survive_backup_and_restore(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Full round-trip preserves nodes, observations, operations and user_version=3."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "full_backup.db"
    restored_db = tmp_path / "full_restored.db"

    perform_backup(source_db, backup_file)
    perform_restore(backup_file, restored_db)

    # Inspect using standard repositories
    restored_inv = SQLiteNodeRepository(restored_db)
    nodes = restored_inv.list_nodes()
    assert len(nodes) == 2
    assert {n.name for n in nodes} == {"web-01", "db-01"}

    restored_conn = SQLiteConnectivityRepository(restored_db)
    obs = restored_conn.latest(nodes[0].id)
    assert obs is not None
    assert obs.outcome == ConnectivityOutcome.CONNECTED

    restored_ops = SQLiteOperationsRepository(restored_db)
    ops = restored_ops.list_for_node(nodes[0].id)
    assert len(ops) == 1
    assert ops[0].action == "system.uptime"
    assert ops[0].outcome == OperationOutcome.SUCCESS

    # Schema version
    is_ok, msg, version = check_integrity(restored_db)
    assert is_ok is True
    assert version == 5


def test_sha256_and_manifest_validation(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Tampering with backup contents is detected and rejected during restore."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "tamper_backup.db"
    restored_db = tmp_path / "tamper_restored.db"

    perform_backup(source_db, backup_file)

    # Tamper with 1 byte of the backup file
    with open(backup_file, "r+b") as f:
        f.seek(100)
        f.write(b"\xff")

    with pytest.raises(RuntimeError, match="(checksum mismatch|corrupt)"):
        perform_restore(backup_file, restored_db)

    assert not restored_db.exists()


def test_schema_version_validation(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Integrity check verifies schema user_version."""
    source_db, _, _, _ = seeded_db
    is_ok, msg, version = check_integrity(source_db)
    assert is_ok is True
    assert version == 5
    assert msg == "ok"


def test_restore_into_fresh_destination(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Restore succeeds cleanly into a brand new destination path."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "fresh_backup.db"
    fresh_target = tmp_path / "new_dir" / "fresh_inventory.db"

    perform_backup(source_db, backup_file)
    res_info = perform_restore(backup_file, fresh_target)

    assert fresh_target.exists()
    assert res_info["schema_user_version"] == 5
    assert res_info["table_counts"]["nodes"] == 2


def test_existing_destination_safety_snapshot(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Restoring over an existing target creates a pre-restore safety snapshot."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "snap_backup.db"
    perform_backup(source_db, backup_file)

    # Create target database with distinct single node
    target_db = tmp_path / "existing_inventory.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("pre-existing-node", "192.168.1.1", 22))

    # Perform restore
    perform_restore(backup_file, target_db)

    # Verify safety snapshot was created
    safety_snapshot = target_db.with_suffix(".db.pre_restore.bak")
    assert safety_snapshot.exists()

    # Safety snapshot contains the pre-existing node
    with sqlite3.connect(safety_snapshot) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["pre-existing-node"]

    # Target now contains the restored nodes
    with sqlite3.connect(target_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert "web-01" in names
        assert "db-01" in names


def test_corrupt_backup_rejected_preflight(tmp_path: Path) -> None:
    """Corrupt backup files are rejected during pre-flight before touching the destination."""
    corrupt_backup = tmp_path / "corrupt.db"
    corrupt_backup.write_bytes(b"This is completely corrupt SQLite header garbage data.")

    target_db = tmp_path / "untouched_target.db"
    repo = SQLiteNodeRepository(target_db)
    repo.initialize()
    repo.add_node(NewNode("untouched", "10.0.0.9", 22))

    with pytest.raises(RuntimeError, match="Cannot restore corrupt backup"):
        perform_restore(corrupt_backup, target_db)

    # Target remains untouched
    with sqlite3.connect(target_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["untouched"]


def test_foreign_key_validation(tmp_path: Path) -> None:
    """Databases with broken foreign key constraints are detected and rejected."""
    fk_db = tmp_path / "broken_fk.db"
    with sqlite3.connect(fk_db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("CREATE TABLE nodes (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute(
            "CREATE TABLE connectivity_observations ("
            "id INTEGER PRIMARY KEY, node_id INTEGER REFERENCES nodes(id));"
        )
        conn.execute("PRAGMA user_version = 3;")
        # Insert orphan observation pointing to non-existent node 999
        conn.execute("INSERT INTO connectivity_observations (id, node_id) VALUES (1, 999);")
        conn.commit()

    is_ok, msg, _ = check_integrity(fk_db)
    assert is_ok is False
    assert "Foreign key violations found" in msg

    # Backup must reject the source with broken foreign keys
    with pytest.raises(RuntimeError, match="Foreign key violations"):
        perform_backup(fk_db, tmp_path / "should_fail.db")


def test_failed_restore_rollback(tmp_path: Path, seeded_db: SeededDB) -> None:
    """When restore replacement fails, target is cleanly rolled back from safety snapshot."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "rollback_backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "rollback_target.db"
    repo = SQLiteNodeRepository(target_db)
    repo.initialize()
    repo.add_node(NewNode("original-node", "10.0.0.50", 22))

    # Mock _atomic_replace on temp_restore to simulate an unexpected error during replacement
    orig_atomic_replace = backup_restore._atomic_replace

    def fail_on_temp_restore(source: Path, target: Path) -> None:
        if str(source).endswith(".restoring.tmp"):
            raise OSError("Disk failure simulation")
        orig_atomic_replace(source, target)

    with patch("scripts.backup_restore._atomic_replace", side_effect=fail_on_temp_restore):
        with pytest.raises(OSError, match="Disk failure simulation"):
            perform_restore(backup_file, target_db)

    # Live target was rolled back to original
    with sqlite3.connect(target_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["original-node"]


def test_interrupted_backup_cleanup(tmp_path: Path, seeded_db: tuple[Path, ...]) -> None:
    """Temporary backup file is cleanly removed if backup is interrupted."""
    source_db = seeded_db[0]
    backup_file = tmp_path / "interrupted.db"
    temp_file = backup_file.with_suffix(backup_file.suffix + ".tmp")

    with patch(
        "scripts.backup_restore._copy_database_pages",
        side_effect=RuntimeError("Interrupted copy"),
    ):
        with pytest.raises(RuntimeError, match="Interrupted copy"):
            perform_backup(source_db, backup_file)

    assert not temp_file.exists()
    assert not backup_file.exists()


def test_interrupted_restore_cleanup(tmp_path: Path, seeded_db: tuple[Path, ...]) -> None:
    """Temporary restore file is cleanly removed if restore is interrupted."""
    source_db = seeded_db[0]
    backup_file = tmp_path / "int_backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "target_clean.db"
    temp_restore = target_db.with_suffix(target_db.suffix + ".restoring.tmp")

    with patch(
        "scripts.backup_restore._copy_database_pages",
        side_effect=RuntimeError("Interrupted restore"),
    ):
        with pytest.raises(RuntimeError, match="Interrupted restore"):
            perform_restore(backup_file, target_db)

    assert not temp_restore.exists()


def test_existing_backup_handling(tmp_path: Path, seeded_db: tuple[Path, ...]) -> None:
    """Overwriting an older backup at the same destination succeeds atomically."""
    source_db = seeded_db[0]
    backup_file = tmp_path / "repeat_backup.db"

    # First backup
    perform_backup(source_db, backup_file)
    first_size = backup_file.stat().st_size

    # Second backup to same destination
    manifest = perform_backup(source_db, backup_file)
    assert backup_file.exists()
    assert manifest["backup_size_bytes"] == first_size


def test_manifest_publication_failure_preserves_previous_backup(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """If manifest publication fails, previous known-good backup and manifest are preserved."""
    source_db, inv_repo, _, _ = seeded_db
    backup_file = tmp_path / "pub_fail_backup.db"
    manifest_path = backup_file.with_suffix(".db.manifest.json")

    # Initial successful backup
    init_manifest = perform_backup(source_db, backup_file)
    init_checksum = init_manifest["sha256"]

    # Modify source DB so second backup would differ
    inv_repo.add_node(NewNode("extra-node", "10.0.0.99", 22))

    # Mock _atomic_replace so it fails once when promoting the new manifest
    orig_atomic_replace = backup_restore._atomic_replace
    has_failed = False

    def fail_on_manifest_replace(source: Path, target: Path) -> None:
        nonlocal has_failed
        if not has_failed and str(target).endswith(".manifest.json"):
            has_failed = True
            raise OSError("Injected disk error during manifest replacement")
        orig_atomic_replace(source, target)

    with patch("scripts.backup_restore._atomic_replace", side_effect=fail_on_manifest_replace):
        with pytest.raises(OSError, match="manifest replacement"):
            perform_backup(source_db, backup_file)

    # Backup and manifest were safely rolled back to the first generation
    assert backup_file.exists()
    assert manifest_path.exists()
    assert calculate_sha256(backup_file) == init_checksum


def test_restore_over_wal_database_truncates_and_unlinks_sidecars(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Restoring over a WAL target database checkpoints, snapshots, and clears old sidecars."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "src_backup.db"
    perform_backup(source_db, backup_file)

    # Create target database with initial node
    target_db = tmp_path / "wal_target.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("pre-existing-node", "10.0.0.8", 22))

    # Simulate stale WAL and SHM sidecars left on disk from an uncheckpointed crash
    target_wal = target_db.with_name(target_db.name + "-wal")
    target_shm = target_db.with_name(target_db.name + "-shm")
    target_wal.write_bytes(b"simulated stale wal log frames from before crash")
    target_shm.write_bytes(b"simulated stale shm index from before crash")
    assert target_wal.exists()
    assert target_shm.exists()

    # Perform restore
    perform_restore(backup_file, target_db)

    # 1. Obsolete sidecars are cleanly unlinked prior to promotion
    assert not target_wal.exists()
    assert not target_shm.exists()

    # 2. Safety snapshot captured the pre-existing node
    safety_snapshot = target_db.with_suffix(".db.pre_restore.bak")
    assert safety_snapshot.exists()
    with sqlite3.connect(safety_snapshot) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert "pre-existing-node" in names

    # 3. Target now holds restored nodes without old WAL interference
    with sqlite3.connect(target_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert "web-01" in names
        assert "db-01" in names
        assert "pre-existing-node" not in names


def test_posix_permissions_0600(tmp_path: Path, seeded_db: SeededDB) -> None:
    """On POSIX systems, backup, manifest, and restored files have 0600 permissions."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "perm_backup.db"
    restored_db = tmp_path / "perm_restored.db"

    perform_backup(source_db, backup_file)
    perform_restore(backup_file, restored_db)

    manifest_file = backup_file.with_suffix(".db.manifest.json")

    if os.name == "posix":
        for p in (backup_file, manifest_file, restored_db):
            mode = stat.S_IMODE(p.stat().st_mode)
            assert mode == 0o600, f"Expected 0600 for {p}, got {oct(mode)}"
    else:
        # On non-POSIX (Windows), assert files exist and are readable
        for p in (backup_file, manifest_file, restored_db):
            assert p.exists()
            assert p.stat().st_size > 0


def test_manifest_required_by_default(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Missing manifest is rejected by default and allowed only with explicit flag."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "req_manifest_backup.db"
    target_db = tmp_path / "req_manifest_target.db"

    perform_backup(source_db, backup_file)
    manifest_file = backup_file.with_suffix(backup_file.suffix + ".manifest.json")
    assert manifest_file.exists()

    # Remove the manifest
    manifest_file.unlink()

    # Default restore must fail
    with pytest.raises(RuntimeError, match="Backup manifest .* is missing"):
        perform_restore(backup_file, target_db)
    assert not target_db.exists()

    # Restore with allow_missing_manifest=True must succeed
    res = perform_restore(backup_file, target_db, allow_missing_manifest=True)
    assert target_db.exists()
    assert res["schema_user_version"] == 5


def test_wal_checkpoint_busy_aborts_restore_before_sidecar_removal(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """If target WAL checkpoint reports busy, restore aborts without unlinking sidecars."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "busy_backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "busy_target.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("initial-busy-node", "10.0.0.99", 22))

    target_wal = target_db.with_name(target_db.name + "-wal")
    target_shm = target_db.with_name(target_db.name + "-shm")
    target_wal.write_bytes(b"wal content before restore attempt")
    target_shm.write_bytes(b"shm content before restore attempt")

    # Patch _wal_checkpoint_truncate to simulate a concurrent transaction holding the WAL lock
    with patch("scripts.backup_restore._wal_checkpoint_truncate", return_value=1):
        with pytest.raises(RuntimeError, match="WAL checkpoint reported busy"):
            perform_restore(backup_file, target_db)

    # Assert sidecars are untouched and original node remains intact
    assert target_wal.exists()
    assert target_shm.exists()
    with sqlite3.connect(target_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert "initial-busy-node" in names


def test_crash_recovery_before_staging_prev(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Interruption before staging previous files leaves active pair intact and cleans tmp."""
    source_db, inv_repo, _, _ = seeded_db
    backup_file = tmp_path / "crash_before_staging.db"
    manifest_file = backup_file.with_suffix(backup_file.suffix + ".manifest.json")

    init_manifest = perform_backup(source_db, backup_file)
    init_sha = init_manifest["sha256"]

    # Leave stranded staged files simulating crash right before staging prev
    inv_repo.add_node(NewNode("node-pre-stage", "10.0.0.77", 22))
    staged_backup = backup_file.with_suffix(backup_file.suffix + ".staged")
    staged_manifest = manifest_file.with_suffix(manifest_file.suffix + ".staged")
    staged_backup.write_bytes(b"stranded staged db")
    staged_manifest.write_text("{}", encoding="utf-8")

    recover_backup_generation(backup_file)

    assert backup_file.exists()
    assert calculate_sha256(backup_file) == init_sha
    assert not staged_backup.exists()
    assert not staged_manifest.exists()


def test_crash_recovery_after_prev_db_staged(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Crash after prev DB was staged rolls back to restore active pair."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "crash_after_prev_db.db"
    manifest_file = backup_file.with_suffix(backup_file.suffix + ".manifest.json")

    init_manifest = perform_backup(source_db, backup_file)
    init_sha = init_manifest["sha256"]

    # Simulate crash: backup_file renamed to .prev, manifest_file still active
    prev_backup = backup_file.with_suffix(backup_file.suffix + ".prev")
    backup_file.replace(prev_backup)
    assert not backup_file.exists()
    assert prev_backup.exists()

    recover_backup_generation(backup_file)

    assert backup_file.exists()
    assert manifest_file.exists()
    assert calculate_sha256(backup_file) == init_sha
    assert not prev_backup.exists()


def test_crash_recovery_after_prev_manifest_staged(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Crash after both DB and manifest were moved to .prev rolls back to prev pair."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "crash_after_prev_m.db"
    manifest_file = backup_file.with_suffix(backup_file.suffix + ".manifest.json")

    init_manifest = perform_backup(source_db, backup_file)
    init_sha = init_manifest["sha256"]

    prev_backup = backup_file.with_suffix(backup_file.suffix + ".prev")
    prev_manifest = manifest_file.with_suffix(manifest_file.suffix + ".prev")
    backup_file.replace(prev_backup)
    manifest_file.replace(prev_manifest)

    assert not backup_file.exists()
    assert not manifest_file.exists()

    recover_backup_generation(backup_file)

    assert backup_file.exists()
    assert manifest_file.exists()
    assert calculate_sha256(backup_file) == init_sha
    assert not prev_backup.exists()
    assert not prev_manifest.exists()


def test_crash_recovery_after_new_backup_published(tmp_path: Path, seeded_db: SeededDB) -> None:
    """Crash after new DB published but before manifest rolls back safely to prev generation."""
    source_db, inv_repo, _, _ = seeded_db
    backup_file = tmp_path / "crash_after_new_db.db"
    manifest_file = backup_file.with_suffix(backup_file.suffix + ".manifest.json")

    init_manifest = perform_backup(source_db, backup_file)
    init_sha = init_manifest["sha256"]

    # Stage prev files
    prev_backup = backup_file.with_suffix(backup_file.suffix + ".prev")
    prev_manifest = manifest_file.with_suffix(manifest_file.suffix + ".prev")
    backup_file.replace(prev_backup)
    manifest_file.replace(prev_manifest)

    # Publish half of new generation: new DB written, but manifest still missing
    backup_file.write_bytes(b"new half-published database without manifest")

    recover_backup_generation(backup_file)

    # Reconciles to previous known-good pair
    assert backup_file.exists()
    assert manifest_file.exists()
    assert calculate_sha256(backup_file) == init_sha
    assert not prev_backup.exists()
    assert not prev_manifest.exists()


def test_crash_recovery_after_new_manifest_published_cleans_prev(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Crash after both new files published unlinks stranded .prev artifacts."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "crash_after_all_pub.db"
    manifest_file = backup_file.with_suffix(backup_file.suffix + ".manifest.json")

    init_manifest = perform_backup(source_db, backup_file)

    # Leave stranded .prev files as if cleanup was killed
    prev_backup = backup_file.with_suffix(backup_file.suffix + ".prev")
    prev_manifest = manifest_file.with_suffix(manifest_file.suffix + ".prev")
    prev_backup.write_bytes(b"old backup")
    prev_manifest.write_text("{}", encoding="utf-8")

    recover_backup_generation(backup_file)

    assert backup_file.exists()
    assert manifest_file.exists()
    assert calculate_sha256(backup_file) == init_manifest["sha256"]
    assert not prev_backup.exists()
    assert not prev_manifest.exists()


def test_crash_recovery_idempotent_and_cleans_tmp(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Calling recover_backup_generation repeatedly is idempotent and cleans tmp files."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "idempotent_backup.db"
    manifest_file = backup_file.with_suffix(backup_file.suffix + ".manifest.json")

    init_manifest = perform_backup(source_db, backup_file)

    temp_backup = backup_file.with_suffix(backup_file.suffix + ".tmp")
    temp_manifest = manifest_file.with_suffix(manifest_file.suffix + ".tmp")
    temp_backup.write_bytes(b"garbage tmp")
    temp_manifest.write_text("garbage tmp", encoding="utf-8")

    # First recovery cleans tmp
    recover_backup_generation(backup_file)
    assert not temp_backup.exists()
    assert not temp_manifest.exists()
    assert calculate_sha256(backup_file) == init_manifest["sha256"]

    # Second recovery is a clean no-op
    recover_backup_generation(backup_file)
    assert calculate_sha256(backup_file) == init_manifest["sha256"]


def test_normal_restore_succeeds_when_no_previous_snapshot_exists(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Normal restore succeeds and creates safety snapshot when no previous snapshot exists."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "normal_backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "normal_target.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("initial-srv", "192.168.1.10", 22))

    safety_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")
    assert not safety_snapshot.exists()

    res_info = perform_restore(backup_file, target_db)
    assert res_info["schema_user_version"] == 5

    # Safety snapshot was created and holds initial node
    assert safety_snapshot.exists()
    with sqlite3.connect(safety_snapshot) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["initial-srv"]

    # Target contains restored nodes
    with sqlite3.connect(target_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert "web-01" in names
        assert "db-01" in names


def test_existing_safety_snapshot_causes_restore_to_fail_safely_and_preserves_hashes(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Existing safety snapshot causes restore refusal, preserving snapshot and active DB hashes."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "safety_test_backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "safety_test_target.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("active-target-srv", "192.168.1.100", 22))

    # Existing safety snapshot on disk
    safety_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")
    snap_repo = SQLiteNodeRepository(safety_snapshot)
    snap_repo.initialize()
    snap_repo.add_node(NewNode("prior-snapshot-srv", "192.168.1.200", 22))

    # Hashes before attempted restore
    active_sha_before = calculate_sha256(target_db)
    snap_sha_before = calculate_sha256(safety_snapshot)

    # Restore must fail closed
    with pytest.raises(PreRestoreSnapshotExistsError) as exc_info:
        perform_restore(backup_file, target_db)

    err_msg = str(exc_info.value)
    assert "pre-restore safety snapshot already exists" in err_msg.lower()
    assert "operator inspection and recovery" in err_msg.lower()

    # 1. Existing snapshot SHA-256 remains unchanged
    assert calculate_sha256(safety_snapshot) == snap_sha_before

    # 2. Active database SHA-256 remains unchanged
    assert calculate_sha256(target_db) == active_sha_before

    # 3. No partial restore staging files remain
    staging_file = target_db.with_suffix(target_db.suffix + ".restoring.tmp")
    assert not staging_file.exists()
    assert list(target_db.parent.glob("*.restoring.tmp")) == []

    # 4. Data records verified intact
    with sqlite3.connect(safety_snapshot) as conn:
        assert [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()] == [
            "prior-snapshot-srv"
        ]

    with sqlite3.connect(target_db) as conn:
        assert [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()] == [
            "active-target-srv"
        ]


def test_existing_snapshot_corrupt_empty_or_directory_detected_and_preserved(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Pre-existing snapshot is preserved even if empty, corrupt, or directory."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "corrupt_snap_backup.db"
    perform_backup(source_db, backup_file)

    # 1. Zero-byte snapshot file
    target_db1 = tmp_path / "zero_target.db"
    SQLiteNodeRepository(target_db1).initialize()
    snap1 = target_db1.with_suffix(target_db1.suffix + ".pre_restore.bak")
    snap1.touch()
    assert snap1.exists() and snap1.stat().st_size == 0
    with pytest.raises(PreRestoreSnapshotExistsError):
        perform_restore(backup_file, target_db1)
    assert snap1.exists() and snap1.stat().st_size == 0

    # 2. Corrupt/garbage snapshot file
    target_db2 = tmp_path / "corrupt_target.db"
    SQLiteNodeRepository(target_db2).initialize()
    snap2 = target_db2.with_suffix(target_db2.suffix + ".pre_restore.bak")
    snap2.write_bytes(b"NON_SQLITE_GARBAGE_PAYLOAD")
    sha_snap2 = calculate_sha256(snap2)
    with pytest.raises(PreRestoreSnapshotExistsError):
        perform_restore(backup_file, target_db2)
    assert snap2.exists()
    assert calculate_sha256(snap2) == sha_snap2

    # 3. Directory at snapshot path
    target_db3 = tmp_path / "dir_target.db"
    SQLiteNodeRepository(target_db3).initialize()
    snap3 = target_db3.with_suffix(target_db3.suffix + ".pre_restore.bak")
    snap3.mkdir()
    assert snap3.is_dir()
    with pytest.raises(PreRestoreSnapshotExistsError):
        perform_restore(backup_file, target_db3)
    assert snap3.is_dir()


def test_existing_snapshot_symlink_detected_and_preserved(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """A valid or broken symlink at .pre_restore.bak is detected and prevents restore."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "sym_src_backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "sym_target.db"
    repo = SQLiteNodeRepository(target_db)
    repo.initialize()
    repo.add_node(NewNode("sym-node", "10.0.0.1", 22))

    safety_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")

    # Try creating a real broken symlink; if OS privileges disallow, mock is_symlink/lexists
    can_symlink = False
    try:
        os.symlink(tmp_path / "nonexistent_target", safety_snapshot)
        can_symlink = True
    except OSError:
        pass

    if can_symlink:
        assert safety_snapshot.is_symlink()
        assert not safety_snapshot.exists()  # Broken symlink exists on disk but does not resolve
        with pytest.raises(PreRestoreSnapshotExistsError):
            perform_restore(backup_file, target_db)
        assert safety_snapshot.is_symlink()
    else:
        orig_lexists = os.path.lexists

        def mock_lexists(path: str | Path | os.PathLike[str]) -> bool:
            if str(path) == str(safety_snapshot):
                return True
            return orig_lexists(path)

        with (
            patch("os.path.lexists", side_effect=mock_lexists),
            patch.object(Path, "is_symlink", return_value=True),
        ):
            with pytest.raises(PreRestoreSnapshotExistsError):
                perform_restore(backup_file, target_db)


def test_refusal_happens_before_wal_checkpoint_or_mutation(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Refusal on existing snapshot happens before WAL checkpointing or active DB modification."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "wal_refusal_backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "wal_refusal_target.db"
    repo = SQLiteNodeRepository(target_db)
    repo.initialize()

    # Enable WAL mode and add node
    with sqlite3.connect(target_db) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute(
            "INSERT INTO nodes (name, address, ssh_port) VALUES ('wal-live-node', '127.0.0.1', 22);"
        )
        conn.commit()

    target_wal = target_db.with_name(target_db.name + "-wal")
    assert target_wal.exists()
    assert target_wal.stat().st_size > 0

    safety_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")
    safety_snapshot.write_bytes(b"existing-safety-snapshot-bytes")

    active_sha_before = calculate_sha256(target_db)
    wal_sha_before = calculate_sha256(target_wal)
    snap_sha_before = calculate_sha256(safety_snapshot)

    # Patch _wal_checkpoint_truncate to ensure it is never called
    with patch(
        "scripts.backup_restore._wal_checkpoint_truncate",
        side_effect=AssertionError("WAL checkpoint must not be called when snapshot exists!"),
    ):
        with pytest.raises(PreRestoreSnapshotExistsError):
            perform_restore(backup_file, target_db)

    # Hashes must remain 100% identical
    assert calculate_sha256(target_db) == active_sha_before
    assert calculate_sha256(target_wal) == wal_sha_before
    assert calculate_sha256(safety_snapshot) == snap_sha_before


def test_concurrent_restore_atomic_reservation_fails_second_caller(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Atomic exclusive reservation fails safely if another restore races to create snapshot."""
    source_db, _, _, _ = seeded_db
    backup_file = tmp_path / "race_backup.db"
    perform_backup(source_db, backup_file)

    target_db = tmp_path / "race_target.db"
    repo = SQLiteNodeRepository(target_db)
    repo.initialize()
    repo.add_node(NewNode("race-target-node", "10.0.0.1", 22))

    safety_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")
    assert not safety_snapshot.exists()

    # Simulate race: os.open fails with FileExistsError during atomic exclusive creation
    orig_open = os.open

    def fail_on_snapshot_reserve(
        path: os.PathLike[str] | str | bytes,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        if str(path) == str(safety_snapshot) and (flags & os.O_CREAT) and (flags & os.O_EXCL):
            raise FileExistsError(f"Simulated concurrent race: {safety_snapshot} already reserved")
        return orig_open(path, flags, *args, **kwargs)

    with patch("os.open", side_effect=fail_on_snapshot_reserve):
        with pytest.raises(PreRestoreSnapshotExistsError, match="already exists"):
            perform_restore(backup_file, target_db)

    # Active DB was not modified
    with sqlite3.connect(target_db) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM nodes;").fetchall()]
        assert names == ["race-target-node"]


def test_subsequent_restore_succeeds_after_operator_archives_snapshot(
    tmp_path: Path,
    seeded_db: SeededDB,
) -> None:
    """Subsequent restore is refused until operator archives snapshot, then succeeds."""
    source_db, _, _, _ = seeded_db
    backup_file_1 = tmp_path / "backup_1.db"
    perform_backup(source_db, backup_file_1)

    # Create a 2nd backup with different data
    db2 = tmp_path / "source2.db"
    repo2 = SQLiteNodeRepository(db2)
    repo2.initialize()
    repo2.add_node(NewNode("node-v2", "192.168.2.1", 22))
    backup_file_2 = tmp_path / "backup_2.db"
    perform_backup(db2, backup_file_2)

    # Target starts with original node-0
    target_db = tmp_path / "lifecycle_target.db"
    target_repo = SQLiteNodeRepository(target_db)
    target_repo.initialize()
    target_repo.add_node(NewNode("node-0", "192.168.0.1", 22))

    safety_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")

    # 1. First restore succeeds, creating safety snapshot containing node-0
    perform_restore(backup_file_1, target_db)
    assert safety_snapshot.exists()
    conn1 = sqlite3.connect(safety_snapshot)
    try:
        assert [r[0] for r in conn1.execute("SELECT name FROM nodes;").fetchall()] == ["node-0"]
    finally:
        conn1.close()

    # 2. Second restore attempt is refused because safety_snapshot exists
    with pytest.raises(PreRestoreSnapshotExistsError):
        perform_restore(backup_file_2, target_db)

    # 3. Operator archives the previous safety snapshot
    archive_dir = tmp_path / "snapshot_archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_path = archive_dir / "target_db.pre_restore.bak.archived"
    safety_snapshot.rename(archived_path)
    assert not safety_snapshot.exists()
    assert archived_path.exists()

    # 4. Now the subsequent restore succeeds
    perform_restore(backup_file_2, target_db)

    # Target now has node-v2 from backup_2
    conn2 = sqlite3.connect(target_db)
    try:
        assert [r[0] for r in conn2.execute("SELECT name FROM nodes;").fetchall()] == ["node-v2"]
    finally:
        conn2.close()

    # A new safety snapshot was created, capturing the state from before 2nd restore
    assert safety_snapshot.exists()
    conn3 = sqlite3.connect(safety_snapshot)
    try:
        names = [r[0] for r in conn3.execute("SELECT name FROM nodes;").fetchall()]
        assert "web-01" in names
    finally:
        conn3.close()

    # The archived snapshot remains pristine with node-0
    conn4 = sqlite3.connect(archived_path)
    try:
        assert [r[0] for r in conn4.execute("SELECT name FROM nodes;").fetchall()] == ["node-0"]
    finally:
        conn4.close()
