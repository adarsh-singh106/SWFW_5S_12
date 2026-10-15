# Document 05: Database Persistence & The Storage Engine

**Series:** Fleet Manager Learning Series\
**Topic:** Feature 1 — Node Inventory (Persistence)\
**Parent Lesson:** [⬅️ Document 04: Input Validation Contract](04-input-validation-contract.md)\
**Status:** In Progress / Learning\

AI-drafted in the previous session (original author/date unverified); reviewed by Codex on 2026-10-13. SQLite and the schema below are proposals, not approved application decisions. Examples are illustrative; no persistence implementation or runtime result is claimed. See [primary references](references.md).

---

## 1. What Problem Are We Solving from First Principles?

Maan le tune Fleet Manager backend start kiya. User ne 10 Linux servers form bhar kar add kar diye.\
Ab maan le:
* Server machine ka light chali gayi ya restart ho gaya.
* Ya tune backend ka naya version deploy karne ke liye process ko restart kiya (`Ctrl + C`).

Agar tune data Python ki memory (RAM) mein rakha tha—jaise `nodes = []`—toh restart hote hi **saara data gaayab!** User ko 10 servers dobara manually enter karne padenge.

> **First Principle Definition:**\
> **Persistence** ka matlab hai: Data ko aisi jagah store karna (Disk/Storage) jo program band hone, crash hone, ya machine restart hone ke baad bhi **survive kare**.

---

## 2. Why SQLite? (Technology Justification & Trade-offs)

SQLite is a candidate for this small inventory because it runs inside the application process and does not require a separate database server. Python provides the `sqlite3` standard-library interface when available in its build.

PostgreSQL/MySQL run as separate services and provide different concurrency and operational capabilities. Their resource use depends on configuration and workload; they are not only for thousands of users.

SQLite permits one writer at a time per database, including when connections share a process. Multiple clients can take turns, but write contention needs handling. Journal/WAL companion files may exist. Backups, permissions, migrations, and recovery still require care: embedded does not mean zero maintenance. Suitability remains a proposal to verify against our workload.

---

## 3. Schema Design: The `nodes` Table Contract

A schema describes columns and constraints. This is an initial sketch to discuss, not a finalized integrity contract:

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

### 🔍 Field-by-Field Breakdown:
1. **`id` (Primary Key):** Har node ka unique roll number.
2. **`name`:** Insaan ko pehchanne ke liye label (e.g. `"Lab PC 1"`).
3. **`address`:** IP ya hostname (e.g. `"192.168.1.10"`).
4. **`ssh_port`:** Validated port number (1 to 65535, default 22).
5. **`status`:** By default **`not_checked`**! (Kyunki save hone ka matlab connected hona nahi hai).
6. **`UNIQUE(address, ssh_port)`:** **Sabse critical constraint!** Agar koi galti se same IP aur same Port dobara add karne ki koshish kare, toh database turant rok dega (Duplicate prevention).

**Limits of this sketch:** `NOT NULL` does not reject empty names; the port column does not enforce the range or strict integer storage. Application validation and appropriate database checks still need design. Address normalization is unresolved: exact address/port uniqueness is not physical-machine identity. `AUTOINCREMENT` is unnecessary unless preventing reuse of deleted IDs is a requirement; `INTEGER PRIMARY KEY` already generates IDs. Status here is only an initial label, not a complete observation model.

---

## 4. Transactions, Commit & Rollback (ACID in Action)

A transaction groups changes into a unit that commits together or rolls back. Python's transaction configuration determines when one opens; choose that explicitly in the later exercise.

Illustrative fragment, assuming an open transaction and valid values:

```python
cursor.execute("INSERT INTO nodes (name, address, ssh_port) VALUES (?, ?, ?)",
               (name, address, port))
connection.commit()
```

Uncommitted changes are not necessarily only in RAM: journal/WAL/database pages may already be on disk. Recovery uses the journaling protocol to restore a consistent committed state. An application may also explicitly roll back a transaction.

Report success only after commit succeeds. Power-loss durability depends on journal/synchronization settings, filesystem behavior, and hardware; commit is not a universal guarantee against every storage failure. A process-restart experiment proves only the behavior tested. Atomicity also does not make a repeated request idempotent.

---

## 5. Security Gate: SQL Injection se Bachav

Kabhi bhi SQL query ko string formatting se mat banana:

❌ **DANGEROUS (SQL Injection Trap):**
```python
# HACKER input: "hacked'); DROP TABLE nodes; --"
query = f"INSERT INTO nodes (name) VALUES ('{user_input}')"
```
String interpolation lets input alter SQL syntax. This stacked `DROP TABLE` example is not a demonstrated exploit: Python sqlite3 `execute()` accepts one statement, and this sample also omits required columns. Neither limitation makes interpolating values safe.

✅ **PRODUCTION PATTERN (Parameterized Queries):**
```python
query = "INSERT INTO nodes (name, address, ssh_port) VALUES (?, ?, ?)"
cursor.execute(query, (name, address, port))
```
Yahan `?` placeholders hain. SQLite library user input ko strictly **data** maanti hai, **executable code nahi**.

---

## 📝 Document 05 Revision Notes

> 1. **Persistence:** Surviving process restarts by storing records on disk.
> 2. **SQLite Choice:** Embedded candidate; workload and operational requirements still need verification.
> 3. **Unique Constraint:** `UNIQUE(address, ssh_port)` duplicates ko database level par rokh deta hai.
> 4. **Commit:** Commit finalizes a transaction; durability depends on configuration and storage assumptions.
> 5. **Security:** Hamesha parameterized queries (`?`) use karo, kabhi f-strings se SQL mat banao.

---

## 🛠️ Hands-on Practice & Exercise

👉 **[Go to Practice 02: Hands-on SQLite Storage & Create/Read Operations](practice/practice-02-sqlite-storage.md)**\
*(Write `db_storage.py` to create the table, insert nodes, prevent duplicates, and query rows)*
