# Practice 02: Hands-on SQLite Storage & Create/Read Operations

**Series:** Fleet Manager Hands-on Practice\
**Topic:** Feature 1 — Node Inventory (Persistence)\
**Parent Lesson:** [⬅️ Document 05: Database Persistence & Storage Engine](../05-database-persistence.md)\
**Associated Code:** [`db_storage.py`](db_storage.py)\

AI-drafted in the previous session; reviewed by Codex on 2026-10-15. Practice implementation only; application readiness and student mastery are not established.

---

## 1. Objective

Is practice exercise mein hum Python ke built-in `sqlite3` module se ek real SQLite database file banayenge (`inventory.db`) jo:
1. `nodes` table create karega (schema with `UNIQUE` constraint).
2. Naye nodes ko safely insert karega (parameterized queries ke sath).
3. Duplicates ko gracefully catch karega (bina crash hue).
4. Saved nodes ko retrieve karke print karega.

---

## 2. The Python `sqlite3` Toolkit (Syntax Cheatsheet / Lego Blocks)

These are separate syntax fragments, not a runnable script. Connections require explicit closing; `with conn` manages transactions only.

```python
import sqlite3

# Tool 1: Transaction context manager (commit/rollback; does NOT close the connection)
with sqlite3.connect("inventory.db") as conn:
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE ...")

# Tool 2: Parameterized INSERT (Prevent SQL injection)
sql = "INSERT INTO nodes (name, address, ssh_port) VALUES (?, ?, ?)"
cursor.execute(sql, (name, address, port))  # Values tuple mein jaati hain!

# Tool 3: Catching Duplicate Error (IntegrityError)
try:
    cursor.execute(sql, (name, address, port))
except sqlite3.IntegrityError:
    raise ValueError(f"Node at {address}:{port} already exists!")

# Tool 4: Reading / Fetching rows
cursor.execute("SELECT id, name, address, ssh_port, status FROM nodes")
rows = cursor.fetchall()  # Returns list of tuples: [(1, 'Server A', '192.168.1.1', 22, 'not_checked'), ...]
```

---

## 3. The Function Contracts to Implement in `db_storage.py`

### Function 1: `init_db(db_path="inventory.db")`
* `nodes` table banaye if not exists:
  ```sql
  CREATE TABLE IF NOT EXISTS nodes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      address TEXT NOT NULL,
      ssh_port INTEGER NOT NULL DEFAULT 22,
      status TEXT NOT NULL DEFAULT 'not_checked',
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(address, ssh_port)
  );
  ```

### Function 2: `add_node(name, address, port=22, db_path="inventory.db")`
* Parameterized query use kare:
  `INSERT INTO nodes (name, address, ssh_port) VALUES (?, ?, ?)`
* Agar same address aur port dobara insert ho, toh `sqlite3.IntegrityError` catch kare aur clean `ValueError("Node with this address and port already exists")` raise kare.
* `conn.commit()` kare.

### Function 3: `list_nodes(db_path="inventory.db")`
* `SELECT id, name, address, ssh_port, status FROM nodes` run kare.
* Saari rows ko return kare (jaise `cursor.fetchall()`).

---

---

## 4. Verification & Test Results

The inherited notes reported verification on 2026-10-14 (original output unavailable). Codex independently checked the existing code on 2026-10-15 using a temporary database and separate Python processes:
* `init_db()` successfully created table schema on disk.
* `add_node()` inserted node with parameterized query.
* Duplicate insertion was cleanly caught via `sqlite3.IntegrityError` and raised `ValueError`.
* `list_nodes()` retrieved explicit columns.

---

## 5. Review: practice implementation with known gaps

Core create/read behavior passed: repeated initialization, parameterized insertion of a quoted name, duplicate rejection without an extra row, and retrieval after the writer process exited. Initial status was `not_checked`. The existing local `inventory.db` was not used or changed.

Remaining issues to address in a student follow-up:

- `with sqlite3.connect(...) as conn` commits/rolls back transactions but does not close the connection. Explicit deterministic cleanup is still needed.
- Every `IntegrityError` is reported as a duplicate. A `None` name reproduced a NOT NULL failure incorrectly labeled "already exists".
- Follow-up verified by Codex on 2026-10-15: `add_node()` now returns the inserted `lastrowid` after successful transaction exit. The return-ID gap is resolved; the cleanup and error-classification gaps remain.
- Name/address normalization and port constraints remain incomplete; this layer does not itself validate those values.
- No concurrency, lock contention, power-loss, or full recovery testing was performed. WAL and row factories are optional design choices, not a production-readiness checklist.

Parameter binding keeps values separate from SQL syntax in these statements. Explicit SELECT columns stabilize the returned shape; `SELECT *` is not inherently a security vulnerability.

Source: [Python sqlite3 reference](https://docs.python.org/3/library/sqlite3.html), especially the connection context manager and parameter binding sections (inspected 2026-10-15).

---

## 6. Detailed Line-by-Line Code Breakdown (The 5 Gears)

Code ko deeply samajhne ke liye yeh 5 concepts jaan-na zaroori hai:

### Gear 1: transaction scope and connection lifetime

`with conn` commits an open transaction on success or rolls it back on failure. It does not close the connection. The current practice code relies on later cleanup; a follow-up should explicitly close each connection even when an exception occurs.

### Gear 2: `conn.execute(...)` Direct Shortcut
* `cursor = conn.cursor()` likhne ke bajay direct `conn.execute()` likha. Python internally khud cursor bana kar query run karta hai, code 2 lines clean ho jata hai.

### Gear 3: `VALUES (?, ?, ?)` (Parameterized Query - The Tala)
* `?` placeholders hain. Python values ko alag se safe tuple `(name, address, port)` mein pass karta hai.
* Bound values are treated as data in these statements; this does not establish security for the entire application.

### Gear 4: `try...except sqlite3.IntegrityError as exc: raise ValueError(...) from exc`
* **Translation:** Jab DB level par `UNIQUE(address, ssh_port)` constraint break hota hai, SQLite technical `sqlite3.IntegrityError` fekta hai. Humne use catch karke clean user-facing `ValueError("Node with this address and port already exists")` banaya.
* **`from exc`:** Python ka exception chaining feature jo original database error ko logs mein chhipata nahi hai, debugging asaan rehti hai.

### Gear 5: `list_nodes()` aur `cursor.fetchall()`
* Explicitly columns select karta hai (`SELECT id, name, address, ssh_port, status`).
* `cursor.fetchall()` saare matching rows ko Python tuples ki list `[(1, 'Lab PC 1', '192.168.1.10', 22, 'not_checked')]` ke roop mein return karta hai.

---

## 7. Next Step
Core behavior has been checked, but independent student understanding and the review gaps remain open. Next proposed topic:\
👉 **[Document 06: Service Layer Integration — Combining Validator + Storage](../06-service-layer-integration.md)**
