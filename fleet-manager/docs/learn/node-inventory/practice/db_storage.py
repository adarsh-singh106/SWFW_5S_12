import sqlite3


def init_db(db_path="inventory.db"):
    """Create the database and nodes table if they don't exist, and ensure all columns exist."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    address TEXT NOT NULL,
                    ssh_port INTEGER NOT NULL DEFAULT 22,
                    status TEXT NOT NULL DEFAULT 'not_checked',
                    banner TEXT,
                    latency_ms REAL,
                    last_error TEXT,
                    last_seen TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(address, ssh_port)
                )
            """)
            # Schema migration check: Ensure newly added columns exist in older database files
            existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()]
            migrations = [
                ("banner", "TEXT"),
                ("latency_ms", "REAL"),
                ("last_error", "TEXT"),
                ("last_seen", "TIMESTAMP")
            ]
            for col_name, col_type in migrations:
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE nodes ADD COLUMN {col_name} {col_type}")
    finally:
        conn.close()


def add_node(name, address, port=22, db_path="inventory.db"):
    """Insert a node and return its ID after commit; map integrity errors to ValueError."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO nodes (name, address, ssh_port)
                VALUES (?, ?, ?)
                """,
                (name, address, port)
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            "Node with this address and port already exists"
        ) from exc
    finally:
        conn.close()


def get_node_by_id(node_id: int, db_path="inventory.db") -> dict | None:
    """Fetch a single node by its primary key ID."""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id, name, address, ssh_port, status, banner, latency_ms, last_error, last_seen, created_at
            FROM nodes
            WHERE id = ?
            """,
            (node_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_node_probe_result(node_id: int, status: str, banner: str = None,
                             latency_ms: float = None, last_error: str = None,
                             db_path="inventory.db") -> dict | None:
    """Update probe results, latency, and timestamp for a node."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE nodes
                SET status = ?, banner = ?, latency_ms = ?, last_error = ?, last_seen = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, banner, latency_ms, last_error, node_id)
            )
    finally:
        conn.close()
    return get_node_by_id(node_id, db_path=db_path)


def list_nodes(db_path="inventory.db") -> list[dict]:
    """Return all nodes as a list of dictionaries."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT id, name, address, ssh_port, status, banner, latency_ms, last_error, last_seen, created_at
            FROM nodes
            ORDER BY id ASC
        """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
