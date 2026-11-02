#!/usr/bin/env python3
"""SQLite Database Online Backup and Restore Utility for Linux Fleet Manager.

Provides:
  1. Transaction-safe online SQLite backup via sqlite3.Connection.backup()
     without database downtime, read lock starvation, or corruption.
  2. Integrity validation via PRAGMA integrity_check, PRAGMA foreign_key_check,
     and PRAGMA user_version.
  3. Metadata manifest generation (SHA-256 checksum, row counts, timestamp, size).
  4. Atomic restoration with pre-flight integrity, manifest verification, and safety snapshots.
  5. Built-in verification test mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any


def _set_private_permissions(path: Path) -> None:
    """Set 0600 permissions on POSIX systems; safe no-op on non-POSIX."""
    if os.name == "posix":
        try:
            path.chmod(0o600)
        except OSError:
            pass


def calculate_sha256(path: Path) -> str:
    """Calculate the SHA-256 digest of a file in 64 KiB chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _copy_database_pages(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    pages: int = 100,
    sleep: float = 0.01,
) -> None:
    """Copy pages safely between connections using SQLite online backup API."""
    source_conn.backup(target_conn, pages=pages, sleep=sleep)


def _atomic_replace(source: Path, target: Path) -> None:
    """Atomically replace target with source and apply private permissions."""
    source.replace(target)
    _set_private_permissions(target)


def check_integrity(db_path: Path) -> tuple[bool, str, int]:
    """Verify database integrity, foreign keys, and extract schema user_version."""
    if not db_path.exists() or not db_path.is_file() or db_path.stat().st_size == 0:
        return False, "Database file does not exist, is not a file, or is empty", 0

    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        row = cursor.fetchone()
        integrity_result = str(row[0]) if row else "unknown"

        cursor.execute("PRAGMA foreign_key_check;")
        fk_violations = cursor.fetchall()

        cursor.execute("PRAGMA user_version;")
        v_row = cursor.fetchone()
        version = int(v_row[0]) if v_row else 0
    except (sqlite3.Error, OSError) as exc:
        return False, f"Failed to inspect database: {exc}", 0
    finally:
        conn.close()

    if integrity_result != "ok":
        return False, f"Integrity check failed: {integrity_result}", version

    if fk_violations:
        return (
            False,
            f"Foreign key violations found: {len(fk_violations)} violation(s)",
            version,
        )

    return True, "ok", version


def get_table_counts(db_path: Path) -> dict[str, int]:
    """Count records in all user-defined database tables."""
    counts: dict[str, int] = {}
    if not db_path.exists() or not db_path.is_file() or db_path.stat().st_size == 0:
        return counts

    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        )
        tables = [r[0] for r in cursor.fetchall()]
        for table in sorted(tables):
            cursor.execute(f'SELECT COUNT(*) FROM "{table}";')  # noqa: S608
            counts[table] = int(cursor.fetchone()[0])
    except (sqlite3.Error, OSError):
        return {}
    finally:
        conn.close()
    return counts


def perform_backup(source_db: Path, backup_dest: Path) -> dict[str, Any]:
    """Perform a safe online backup from source_db to backup_dest."""
    if not source_db.exists() or not source_db.is_file():
        raise FileNotFoundError(f"Source database {source_db} does not exist or is not a file")

    if source_db.stat().st_size == 0:
        raise ValueError(f"Source database {source_db} is empty (0 bytes)")

    # Pre-flight check on source
    is_ok, check_msg, version = check_integrity(source_db)
    if not is_ok:
        raise RuntimeError(f"Source database failed integrity check: {check_msg}")

    backup_dest.parent.mkdir(parents=True, exist_ok=True)
    temp_backup = backup_dest.with_suffix(backup_dest.suffix + ".tmp")
    if temp_backup.exists():
        temp_backup.unlink(missing_ok=True)

    _set_private_permissions(temp_backup)

    print(f"[*] Starting online backup: {source_db} -> {backup_dest}")
    started = time.monotonic()

    # Use SQLite online backup API to copy pages safely
    src_conn = sqlite3.connect(f"file:{source_db.resolve()}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(temp_backup)
    try:
        _copy_database_pages(src_conn, dst_conn, pages=100, sleep=0.01)
    except Exception:
        dst_conn.close()
        src_conn.close()
        if temp_backup.exists():
            temp_backup.unlink(missing_ok=True)
        raise
    finally:
        dst_conn.close()
        src_conn.close()

    duration = time.monotonic() - started
    _set_private_permissions(temp_backup)

    # Verify backup integrity
    is_ok, check_msg, version = check_integrity(temp_backup)
    if not is_ok:
        temp_backup.unlink(missing_ok=True)
        raise RuntimeError(f"Backup failed integrity check: {check_msg}")

    checksum = calculate_sha256(temp_backup)
    counts = get_table_counts(temp_backup)

    manifest: dict[str, Any] = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_database": str(source_db.resolve()),
        "backup_database": str(backup_dest.resolve()),
        "backup_size_bytes": temp_backup.stat().st_size,
        "sha256": checksum,
        "schema_user_version": version,
        "table_counts": counts,
        "duration_seconds": round(duration, 3),
    }

    manifest_path = backup_dest.with_suffix(backup_dest.suffix + ".manifest.json")
    temp_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temp_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _set_private_permissions(temp_manifest)

    # Atomic publication of both backup and manifest with rollback guarantee
    prev_backup: Path | None = None
    prev_manifest: Path | None = None
    if backup_dest.exists():
        prev_backup = backup_dest.with_suffix(backup_dest.suffix + ".prev.tmp")
        backup_dest.replace(prev_backup)
    if manifest_path.exists():
        prev_manifest = manifest_path.with_suffix(manifest_path.suffix + ".prev.tmp")
        manifest_path.replace(prev_manifest)

    try:
        _atomic_replace(temp_backup, backup_dest)
        _atomic_replace(temp_manifest, manifest_path)
    except Exception:
        # Revert to previous backup and manifest if publication fails
        if prev_backup and prev_backup.exists():
            _atomic_replace(prev_backup, backup_dest)
        if prev_manifest and prev_manifest.exists():
            _atomic_replace(prev_manifest, manifest_path)
        if temp_backup.exists():
            temp_backup.unlink(missing_ok=True)
        if temp_manifest.exists():
            temp_manifest.unlink(missing_ok=True)
        raise
    finally:
        if prev_backup and prev_backup.exists():
            prev_backup.unlink(missing_ok=True)
        if prev_manifest and prev_manifest.exists():
            prev_manifest.unlink(missing_ok=True)

    print(f"[+] Backup completed successfully in {manifest['duration_seconds']}s")
    print(f"    - Schema version : {version}")
    print(f"    - Size           : {manifest['backup_size_bytes']} bytes")
    print(f"    - SHA-256        : {checksum[:16]}...")
    print(f"    - Table counts   : {counts}")
    print(f"    - Manifest saved : {manifest_path}")

    return manifest


def perform_restore(backup_file: Path, target_db: Path) -> dict[str, Any]:
    """Safely restore backup_file into target_db after pre-flight integrity check."""
    if not backup_file.exists() or not backup_file.is_file():
        raise FileNotFoundError(f"Backup file {backup_file} does not exist or is not a file")

    if backup_file.stat().st_size == 0:
        raise ValueError(f"Backup file {backup_file} is empty (0 bytes)")

    print(f"[*] Pre-flight integrity check on backup: {backup_file}")
    is_ok, check_msg, version = check_integrity(backup_file)
    if not is_ok:
        raise RuntimeError(f"Cannot restore corrupt backup: {check_msg}")

    # Check sidecar manifest if present
    manifest_path = backup_file.with_suffix(backup_file.suffix + ".manifest.json")
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_checksum = manifest_data.get("sha256")
            if expected_checksum:
                actual_checksum = calculate_sha256(backup_file)
                if actual_checksum != expected_checksum:
                    raise RuntimeError(
                        f"Backup checksum mismatch: manifest expected {expected_checksum}, "
                        f"computed {actual_checksum}"
                    )
            expected_size = manifest_data.get("backup_size_bytes")
            if expected_size is not None and backup_file.stat().st_size != expected_size:
                raise RuntimeError(
                    f"Backup size mismatch: manifest expected {expected_size}, "
                    f"actual {backup_file.stat().st_size}"
                )
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Corrupt manifest file {manifest_path}: {exc}") from exc

    target_db.parent.mkdir(parents=True, exist_ok=True)

    # If target exists, create a safety rollback snapshot
    safety_snapshot: Path | None = None
    target_wal = target_db.with_name(target_db.name + "-wal")
    target_shm = target_db.with_name(target_db.name + "-shm")

    if target_db.exists() and target_db.stat().st_size > 0:
        # Flush uncheckpointed WAL frames into target_db so safety snapshot has complete state
        try:
            ck_conn = sqlite3.connect(f"file:{target_db.resolve()}", uri=True)
            try:
                ck_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            finally:
                ck_conn.close()
        except sqlite3.Error:
            pass  # Safe no-op if DB was not in WAL mode

        safety_snapshot = target_db.with_suffix(target_db.suffix + ".pre_restore.bak")
        src_target = sqlite3.connect(f"file:{target_db.resolve()}?mode=ro", uri=True)
        dst_safety = sqlite3.connect(safety_snapshot)
        try:
            _copy_database_pages(src_target, dst_safety, pages=100, sleep=0.01)
        finally:
            dst_safety.close()
            src_target.close()
        _set_private_permissions(safety_snapshot)
        print(f"[+] Created pre-restore safety snapshot: {safety_snapshot}")

    temp_restore = target_db.with_suffix(target_db.suffix + ".restoring.tmp")
    if temp_restore.exists():
        temp_restore.unlink(missing_ok=True)

    try:
        # Use SQLite backup API to write into temp_restore
        src_bkp = sqlite3.connect(f"file:{backup_file.resolve()}?mode=ro", uri=True)
        dst_temp = sqlite3.connect(temp_restore)
        try:
            _copy_database_pages(src_bkp, dst_temp, pages=100, sleep=0.01)
        finally:
            dst_temp.close()
            src_bkp.close()

        _set_private_permissions(temp_restore)

        # Validate restored temporary file
        res_ok, res_msg, res_version = check_integrity(temp_restore)
        if not res_ok:
            temp_restore.unlink(missing_ok=True)
            raise RuntimeError(f"Restored file failed integrity check: {res_msg}")

        # Clean up obsolete sidecars prior to atomic replacement to eliminate the crash window
        # where old WAL frames could replay into the restored database
        if target_wal.exists():
            target_wal.unlink(missing_ok=True)
        if target_shm.exists():
            target_shm.unlink(missing_ok=True)

        # Atomically replace target database
        _atomic_replace(temp_restore, target_db)

    except Exception as exc:
        if temp_restore.exists():
            temp_restore.unlink(missing_ok=True)
        if safety_snapshot and safety_snapshot.exists():
            _atomic_replace(safety_snapshot, target_db)
            print(f"[!] Restored database rolled back to safety snapshot due to error: {exc}")
        raise

    counts = get_table_counts(target_db)
    print(f"[+] Database restored successfully to {target_db}")
    print(f"    - Schema version : {res_version}")
    print(f"    - Table counts   : {counts}")

    return {
        "restored_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_database": str(target_db.resolve()),
        "schema_user_version": res_version,
        "table_counts": counts,
    }


def self_verify(tmp_dir: Path) -> None:
    """Run an autonomous end-to-end backup and restore verification test."""
    print("=" * 70)
    print("Running Backup & Restore Verification Self-Test")
    print("=" * 70)

    work_dir = tmp_dir / "backup_test"
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    src_db = work_dir / "live_inventory.db"
    backup_file = work_dir / "backups" / "live_inventory_backup.db"
    restored_db = work_dir / "restored_inventory.db"

    # 1. Initialize schema v3 and seed dummy data matching Fleet Manager models
    conn = sqlite3.connect(src_db)
    try:
        conn.execute("PRAGMA user_version = 3;")
        conn.execute("""
            CREATE TABLE nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                address TEXT NOT NULL,
                ssh_port INTEGER NOT NULL,
                observation_state TEXT NOT NULL DEFAULT 'NOT_CHECKED'
            );
        """)
        conn.execute("""
            CREATE TABLE connectivity_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL REFERENCES nodes(id),
                observed_at TEXT NOT NULL,
                outcome TEXT NOT NULL,
                error_category TEXT
            );
        """)
        conn.execute("""
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
                audit_metadata TEXT NOT NULL
            );
        """)
        # Insert test records
        conn.execute(
            "INSERT INTO nodes (name, address, ssh_port, observation_state) "
            "VALUES ('node-1', '127.0.0.1', 2201, 'NOT_CHECKED');"
        )
        conn.execute(
            "INSERT INTO nodes (name, address, ssh_port, observation_state) "
            "VALUES ('node-2', '127.0.0.1', 2202, 'NOT_CHECKED');"
        )
        conn.execute(
            "INSERT INTO connectivity_observations (node_id, observed_at, outcome, error_category) "
            "VALUES (1, '2026-10-27T16:00:00Z', 'CONNECTED', NULL);"
        )
        conn.execute(
            "INSERT INTO operation_executions ("
            "  id, node_id, action, arguments, requested_at, outcome, exit_code, audit_metadata"
            ") VALUES ("
            "  'op-001', 1, 'system.uptime', '{}', '2026-10-27T16:01:00Z', 'SUCCESS', 0, '{}'"
            ");"
        )
        conn.commit()
    finally:
        conn.close()

    orig_counts = get_table_counts(src_db)
    print(f"[*] Original database initialized with: {orig_counts}")

    # 2. Perform online backup
    manifest = perform_backup(src_db, backup_file)
    assert manifest["schema_user_version"] == 3
    assert manifest["table_counts"] == orig_counts

    # 3. Restore into clean target path
    res_info = perform_restore(backup_file, restored_db)
    assert res_info["schema_user_version"] == 3
    assert res_info["table_counts"] == orig_counts

    # 4. Verify data fidelity
    conn = sqlite3.connect(restored_db)
    try:
        node_count = conn.execute("SELECT COUNT(*) FROM nodes;").fetchone()[0]
        obs_count = conn.execute("SELECT COUNT(*) FROM connectivity_observations;").fetchone()[0]
        op_count = conn.execute("SELECT COUNT(*) FROM operation_executions;").fetchone()[0]
        assert node_count == 2
        assert obs_count == 1
        assert op_count == 1
    finally:
        conn.close()

    shutil.rmtree(work_dir, ignore_errors=True)
    print("\n[PASS] Database online backup and restore self-verification succeeded!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fleet Manager SQLite Backup and Restore Utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Backup command
    b_parser = subparsers.add_parser("backup", help="Perform safe online SQLite backup")
    b_parser.add_argument("source", type=Path, help="Path to source SQLite database")
    b_parser.add_argument("destination", type=Path, help="Path to output backup file")

    # Restore command
    r_parser = subparsers.add_parser("restore", help="Restore SQLite database from backup")
    r_parser.add_argument("backup", type=Path, help="Path to backup file")
    r_parser.add_argument("target", type=Path, help="Path to target database destination")

    # Verify command
    v_parser = subparsers.add_parser("verify", help="Run end-to-end backup/restore self-test")
    v_parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=Path(tempfile.gettempdir()),
        help="Temporary directory for test files",
    )

    args = parser.parse_args()
    if args.command == "backup":
        perform_backup(args.source, args.destination)
    elif args.command == "restore":
        perform_restore(args.backup, args.target)
    elif args.command == "verify":
        self_verify(args.tmp_dir)
