# Practice 03: Service Layer Integration (Connecting Validator + Storage)

**Series:** Fleet Manager Hands-on Practice\
**Topic:** Feature 1 — Node Inventory (Service Layer)\
**Parent Lesson:** [⬅️ Document 06: Service Layer Integration](../06-service-layer-integration.md)\
**Associated Code:** `node_service.py` (not created yet)\

AI-drafted in the previous session; reviewed by Codex on 2026-10-15. Proposed student exercise, not an implemented service or approved application architecture.

**Before implementation:** current `add_node()` returns `None`. Agree a storage contract that returns the inserted ID after successful commit before using the ID example below. Resolve duplicate-error classification and deterministic connection closing. Validator strict-policy gaps remain documented in Practice 01.

---

## 1. Objective

Is practice exercise mein hum ek unified Service Layer function banayenge: **`register_node()`**.\
Yeh function hamare dono previous modules ko jodega:
1. [`validate_port.py`](validate_port.py) se **`validate_ssh_port`**
2. [`db_storage.py`](db_storage.py) se **`add_node`** aur **`init_db`**

---

## 2. The Lego Blocks / Syntax Cheatsheet

Tujhe zero se syntax sochna nahi padega. Yeh rahe tere building blocks:

### Tool 1: Module Imports (Pichle functions ko lana)
```python
from validate_port import validate_ssh_port
from db_storage import init_db, add_node, list_nodes
```

### Tool 2: String Sanitization (Whitespace hatao aur empty check karo)
```python
if not isinstance(name, str) or not isinstance(address, str):
    raise ValueError("Name and address must be strings")
clean_name = name.strip()
if not clean_name:
    raise ValueError("Node name cannot be empty")

clean_address = address.strip()
if not clean_address:
    raise ValueError("Node address cannot be empty")
```

Trimming is normalization, not IP/hostname validation or proof of reachability. The string-only policy above is proposed; agree the contract before implementing.

### Tool 3: Port Validation (Pichla validator call karo)
```python
valid_port = validate_ssh_port(port)
```

### Tool 4: Storage Call & Structured Dictionary Return
```python
# Database mein save karo (Duplicate aane par add_node khud ValueError raise karega)
# Proposed future return contract; current add_node returns None.
node_id = add_node(clean_name, clean_address, valid_port, db_path)

# Clean, structured dictionary return karo (Web API aur Frontend ke liye ready!)
return {
    "id": node_id,
    "name": clean_name,
    "address": clean_address,
    "ssh_port": valid_port,
    "status": "not_checked"
}
```

---

## 3. Function Contract for `node_service.py`

File bana: `node_service.py` (not created yet) aur yeh do functions implement kar:

```python
def register_node(name: str, address: str, port: int | str = 22, db_path: str = "inventory.db") -> dict:
    """Sanitizes input, validates port, saves to DB, and returns structured node dict."""
    pass

def get_fleet_inventory(db_path: str = "inventory.db") -> list[dict]:
    """Retrieves all nodes and converts rows to a clean list of dictionaries."""
    pass
```

---

## 4. Next Step

First explain why the current storage function cannot supply an ID. Agree the small storage-contract changes and exercise scope before implementing. Initialize the database explicitly in exercise setup; test successful registration, invalid input without insertion, duplicates, and retrieval using a temporary database.

Student `node_service.py` (not created yet) likhega aur edge cases test karega.\
Jab yeh chal jaye, tab hum is feature ko synthesize karke verify karenge!
