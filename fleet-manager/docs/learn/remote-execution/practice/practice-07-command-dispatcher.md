# Practice 07: The Secure Command Dispatcher & Audit Engine

**Series:** Fleet Manager Hands-on Practice\
**Topic:** Feature 4 — Controlled Remote Command Execution\
**Parent Lesson:** [⬅️ Document 12: Controlled Remote Command Execution & Enterprise Audit Pipeline](../12-controlled-remote-command-execution.md)\
**Associated Code:** [`command_dispatcher.py`](command_dispatcher.py), [`test_command_dispatcher.py`](test_command_dispatcher.py)

---

## 1. Objective

Is practice exercise mein hum Fleet Manager ka enterprise-grade **Controlled Remote Command Dispatcher** build karenge:

1. **Guarded Action Catalog (Allowlist):**
   * Free-form text box ko completely block karenge.
   * Sirf predefined actions allow karenge: `system.uptime`, `system.disk_free`, `system.memory`, `service.status`, `service.restart`.
   * Parametric actions (e.g. `service.status`) ke liye regex validation (`^[a-zA-Z0-9_\-]+$`) aur allowed service names list enforce karenge.
2. **Bounded Execution Timer:**
   * Python ke `subprocess.run` par strict timeout (default: 5.0s) lagayenge.
   * Agar koi command hang ho jaye (`cat` without args ya interactive prompts), toh timeout `SIGKILL` bhej kar process terminate karega aur exit code `124` record karega.
3. **POSIX Stream Isolation:**
   * `stdout`, `stderr`, aur `exit_code` ko alag-alag capture karenge without stream pollution.
4. **Immutable SQLite Audit Trail:**
   * Table `command_audit_log` create karenge aur har execution ka full telemetry record karenge (`node_id`, `action_name`, `status`, `exit_code`, `duration_ms`, `stdout`, `stderr`, `executed_at`).
5. **Deterministic Automated Verification:**
   * `test_command_dispatcher.py` me 5 comprehensive test cases likhenge jo allowlist rejection, timeout termination, stream separation, aur DB persistence verify karenge.

---

## 2. Architecture & Data Flow

```
                      INCOMING EXECUTION REQUEST
                      {node_id: 1, action: "service.status", params: {service: "nginx"}}
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │  1. ACTION CATALOG VALIDATION │
                   │     Is action in ALLOWLIST?   │
                   └───────────────┬───────────────┘
                        YES        │        NO
                         ┌─────────┴────────┐
                         ▼                  ▼
             ┌───────────────────────┐  Raise ValueError:
             │ 2. PARAMETER VALIDATION│  "Unauthorized Action"
             │    Regex & Service    │
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │ 3. BOUNDED SUBPROCESS │
             │    Timer: 5.0s Max    │
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │ 4. STREAM EXTRACTION  │
             │   exit_code, out, err │
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │ 5. SQLITE AUDIT INSERT│
             │   command_audit_log   │
             └───────────────────────┘
```

---

## 3. The Action Catalog Specification

```python
COMMAND_CATALOG = {
    "system.uptime": {
        "description": "Check system uptime and load average",
        "template": "uptime",
        "needs_params": False,
    },
    "system.disk_free": {
        "description": "Check disk space usage on root filesystem",
        "template": "df -h /",
        "needs_params": False,
    },
    "system.memory": {
        "description": "Check free and available memory",
        "template": "free -m",
        "needs_params": False,
    },
    "service.status": {
        "description": "Check status of an allowed systemd service",
        "template": "systemctl status {service}",
        "needs_params": True,
        "allowed_services": ["nginx", "node_exporter", "ssh", "docker", "cron"]
    },
    "service.restart": {
        "description": "Restart an allowed systemd service",
        "template": "systemctl restart {service}",
        "needs_params": True,
        "allowed_services": ["nginx", "node_exporter", "ssh", "docker"]
    }
}
```

---

## 4. Verification

Code ko run aur test karne ke liye:
```bash
python test_command_dispatcher.py
```
Expected: All 5 security and execution tests pass cleanly with exit code 0!
