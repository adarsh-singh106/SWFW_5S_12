
import sqlite3


def init_db(db_path="inventory.db"):
    """Create the database and nodes table if they don't exist."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                ssh_port INTEGER NOT NULL DEFAULT 22,
                status TEXT NOT NULL DEFAULT 'not_checked',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(address, ssh_port)
            )
        """)


def add_node(name, address, port=22, db_path="inventory.db"):
    """Insert a node and return its ID after commit; map integrity errors to ValueError."""
    try:
        with sqlite3.connect(db_path) as conn:
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



def list_nodes(db_path="inventory.db"):
    """Return all nodes as a list of tuples."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("""
            SELECT id, name, address, ssh_port, status
            FROM nodes
        """)
        return cursor.fetchall()
