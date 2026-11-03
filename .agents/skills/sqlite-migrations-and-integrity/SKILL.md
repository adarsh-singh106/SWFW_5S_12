---
name: sqlite-migrations-and-integrity
description: Manages SQLite schema evolution, transactional migrations using PRAGMA user_version, data integrity constraints, and immutable audit logs. Use when adding tables, columns, constraints, or migrating database schemas.
---

# SQLite Schema Evolution, Migrations, and Data Integrity

Standard engineering practices for relational data storage in SQLite, focusing on versioned transactional migrations, structural integrity constraints, concurrency safety, and audit logging.

## Core Principles

1. **Explicit Schema Versioning**: Never guess schema version from column existence or table probes. Always use `PRAGMA user_version` as the single authoritative source of truth.
2. **Atomic Migrations**: Every migration step must run inside an immediate transaction (`BEGIN IMMEDIATE`) so that partial failures do not corrupt database state.
3. **Defense-in-Depth Constraints**: Do not rely solely on application validation. Enforce database-level guardrails using `CHECK`, `UNIQUE`, `NOT NULL`, and `FOREIGN KEY` constraints.
4. **Append-Only Auditing**: Never overwrite historical event records (e.g. connectivity probes, command runs). Append new observation rows with timestamps and query the latest record.

---

## Migration Pattern (`PRAGMA user_version`)

### Version Progression Architecture

```text
Version 0: Empty Database
   │
   ├─► Transaction 1: Create nodes table, set user_version = 1
   │
Version 1: Core Inventory
   │
   ├─► Transaction 2: Create connectivity_observations table, set user_version = 2
   │
Version 2: Verified Observations
   │
   ├─► Transaction 3: Create command_audit_log table, set user_version = 3
   │
Version 3: Execution Audit Trail
```

### Reference Python Migration Implementation

```python
import sqlite3
from contextlib import closing
from pathlib import Path

CURRENT_SCHEMA_VERSION = 2

class StorageError(Exception):
    """Database schema or transaction error."""

def connect_db(db_path: Path, timeout: float = 5.0) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def migrate_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_db(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            
            if version == 0:
                # Initial Schema V1: Nodes Table
                conn.execute("""
                CREATE TABLE nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 100),
                    address TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(address)) > 0),
                    ssh_port INTEGER NOT NULL CHECK (typeof(ssh_port) = 'integer' AND ssh_port BETWEEN 1 AND 65535),
                    observation_state TEXT NOT NULL DEFAULT 'NOT_CHECKED',
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
                    UNIQUE (address, ssh_port)
                );
                """)
                conn.execute("PRAGMA user_version = 1")
                version = 1

            if version == 1:
                # Migration V1 -> V2: Add Append-Only Observations Table
                conn.execute("""
                CREATE TABLE connectivity_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    observed_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
                    outcome TEXT NOT NULL,
                    error_category TEXT,
                    latency_ms REAL
                );
                """)
                conn.execute("""
                CREATE INDEX idx_observations_node_latest 
                ON connectivity_observations(node_id, id DESC);
                """)
                conn.execute("PRAGMA user_version = 2")
                version = 2

            if version > CURRENT_SCHEMA_VERSION:
                raise StorageError(
                    f"Database schema version {version} is newer than supported version {CURRENT_SCHEMA_VERSION}"
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
```

---

## Schema Integrity Rules

1. **Address Normalization**:
   - Use `COLLATE NOCASE` on hostnames and addresses to prevent duplicate entries like `Server1` and `server1`.
   - Always strip whitespace before database insertion and check `length(trim(col)) > 0`.

2. **Port Constraints**:
   - Enforce both type and numerical range:
     `CHECK (typeof(ssh_port) = 'integer' AND ssh_port BETWEEN 1 AND 65535)`.

3. **Composite Uniqueness**:
   - Enforce uniqueness across IP/hostname AND port: `UNIQUE (address, ssh_port)`.

4. **Foreign Key Enforcement**:
   - SQLite does not enable foreign keys by default. Always execute `PRAGMA foreign_keys = ON` on **every** connection before issuing queries.

5. **Parameterized Queries (Zero SQL Injection)**:
   - Never use string interpolation (`f"..."`, `format()`, `%`).
   - Use positional `?` or named `:name` parameter markers:
     ```python
     conn.execute(
         "INSERT INTO nodes (name, address, ssh_port) VALUES (?, ?, ?)",
         (name, address, port)
     )
     ```

---

## Concurrency and Locking Strategy

SQLite supports multiple concurrent readers but only one writer at a time.

- **Use `BEGIN IMMEDIATE`**: Prevents `SQLITE_BUSY` deadlocks when multiple connections attempt to upgrade from read lock to write lock simultaneously.
- **Set a Busy Timeout**: Always supply `timeout=5.0` or call `PRAGMA busy_timeout = 5000` to prevent immediate failures under transient lock contention.
- **Keep Transactions Short**: Open the connection, execute queries within a fast transaction, and commit or close immediately. Never hold database transactions open across network calls (e.g. during SSH connections or HTTP requests).

---

## Verification Checklist

Before considering database work complete:

- [ ] New tables and columns are defined with explicit `NOT NULL`, `CHECK`, and default constraints.
- [ ] Migration is tested on an empty database (from version 0 to target).
- [ ] Migration is tested on an existing populated database (from version N-1 to target) without data loss.
- [ ] SQLite version PRAGMA is checked and incremented in the same transaction.
- [ ] Pytest fixtures run against isolated temporary database paths (`tmp_path`).
- [ ] Foreign key cascade behavior is verified.
- [ ] Concurrent read/write smoke tests confirm graceful handling under load.
