# Practice 03: Service Layer Integration (Connecting Validator + Storage)

**Series:** Fleet Manager Hands-on Practice\
**Topic:** Feature 1 — Node Inventory (Service Layer)\
**Parent Lesson:** [⬅️ Document 06: Service Layer Integration](../06-service-layer-integration.md)\
**Associated Code:** [`node_service.py`](node_service.py)\

AI-drafted in the previous session; reviewed by Codex on 2026-10-15. Original exercise proposal followed by a student practice implementation; not an approved application architecture.

**Current status:** `add_node()` now returns the inserted ID after commit. `node_service.py` implements `register_node(node: dict)` with required `name`, `address`, and `port` keys, unlike the original proposed signature below. It initializes the default database in the working directory. `get_fleet_inventory()` is not implemented. Storage cleanup/error classification and validator strict-policy gaps remain open.

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
# Storage now returns the inserted ID; this is still the original service-signature proposal.
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

File bana: [`node_service.py`](node_service.py) aur yeh do functions implement kar:

```python
def register_node(name: str, address: str, port: int | str = 22, db_path: str = "inventory.db") -> dict:
    """Sanitizes input, validates port, saves to DB, and returns structured node dict."""
    pass

def get_fleet_inventory(db_path: str = "inventory.db") -> list[dict]:
    """Retrieves all nodes and converts rows to a clean list of dictionaries."""
    pass
```

---

## 4. Verification & Review of `node_service.py`

Codex independently tested the current implementation on 2026-10-15 in a temporary working directory, without touching existing local databases:

- Registration returned a positive integer ID, trimmed name/address, integer port, and `not_checked` status.
- A duplicate and six invalid inputs raised `ValueError` without inserting additional rows: blank name, non-string name, non-string address, blank address, boolean port, and out-of-range port.
- A separate Python process retrieved the saved record.
- Omitting `port` raised `KeyError`; defensive `.get()` parsing is not implemented. The input container type is also not checked.

**Remaining contract work:** agree required/optional keys and defaults, the `port` input versus `ssh_port` output naming, and a testable database-path interface. `.get()` is one possible implementation after deciding those rules, not an automatically correct policy. Address syntax validation and service-level inventory retrieval remain unimplemented. Do not mark full Feature 1 verification complete.

---

## 5. Student Thought: IP Address vs Hostname (IPv4 / IPv6)

> Student Comment:\
> *"for port we have function and for IP address, i am not sure if its IPv4 or IPv6 though IPv4 is 32 bit digit . 1byte each no. (set of such 4)"*

### First Principles Answer:
1. **IPv4:** 4 numbers (0-255) separated by dots (32 bits), e.g., `192.168.1.10`.
2. **IPv6:** 8 groups of hexadecimal digits separated by colons (128 bits), e.g., `2001:0db8::1`.
3. **Hostnames / Domains:** Real Linux servers often use DNS names, e.g., `lab-pc1.local`, `worker-1.internal`, or `localhost`.
4. **Validation in Python:** Python has a built-in module `import ipaddress` (`ipaddress.ip_address(val)`). Par production fleet systems hostnames bhi accept karte hain, accepting hostnames requires an explicit policy too. Trimming alone does not validate an address or hostname, and no reachability check is performed.

---

## 6. Next Step

Explain the intended outcome when `port` is omitted, then agree the payload contract before changing the implementation. Document 07 is a proposed synthesis topic, not an existing lesson or evidence that browser/API onboarding is complete.
