# Practice 05: The SSH Banner Probe Engine

> Draft review pending: refusal/timeout interpretation, banner framing, overall timeout bounds, blocking versus non-blocking terminology, and deterministic test scenarios need review before implementation. `probe_engine.py` is a planned exercise file and does not yet exist.

**Series:** Fleet Manager Hands-on Practice\
**Topic:** Feature 2 — Node Availability & Probing\
**Parent Lesson:** [⬅️ Document 08: Linux Connectivity Probing & The SSH Handshake](../08-linux-probing-and-handshakes.md)\
**Associated Code:** [`probe_engine.py`](probe_engine.py)

---

## 1. Objective

Is practice exercise mein hum ek dedicated network probe function banayenge: **`probe_ssh_endpoint(address, port, timeout=2.5)`** using Python's standard library **`socket`**.\
Yeh function remote machine ko test karega **bina authentication run kiye**:

1. TCP 3-way handshake initiate karega (with a strict 2.5-second timeout).
2. Remote server se RFC 4253 SSH identification banner read karega (e.g. `SSH-2.0-OpenSSH...`).
3. Network failures ko accurately classify karega:
   * **`ConnectionRefusedError`:** Host zinda hai par port 22 pe service band hai.
   * **`TimeoutError`:** Packets drop ho rahe hain (firewall ya host powered off).
   * **`InvalidBannerError`:** Port open hai par SSH nahi chal raha (koi aur service hai).
4. Ek structured observation dictionary return karega:
   ```python
   {
       "reachable": True,
       "banner": "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.6",
       "latency_ms": 14.2,
       "error": None
   }
   ```

---

## 2. The Lego Blocks / Syntax Cheatsheet

Network programming ke building blocks pure Python standard library mein hain. Koi third-party library nahi chahiye!

### Tool 1: Creating a TCP Socket with Bounded Timeout
```python
import socket
import time

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# Never leave timeout as None! Bounded execution is non-negotiable.
s.settimeout(timeout)
```

### Tool 2: Measuring Round-Trip Handshake Latency
```python
start_time = time.perf_counter()
s.connect((address, port))
latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
```

### Tool 3: Reading the RFC 4253 SSH Banner
```python
# OpenSSH servers send their banner immediately upon TCP connection
raw_bytes = s.recv(256)
banner = raw_bytes.decode("utf-8", errors="replace").strip()

if not banner.startswith("SSH-"):
    raise ValueError(f"Port is open, but service is not SSH (received: {banner[:30]!r})")
```

### Tool 4: Safe Socket Cleanup (Always close resources!)
```python
finally:
    s.close()
```

### Tool 5: Distinguishing Linux Network Errors
```python
except ConnectionRefusedError:
    return {
        "reachable": False,
        "banner": None,
        "latency_ms": None,
        "error": "Connection refused (Host is alive, but SSH service is not running on this port)"
    }
except (socket.timeout, TimeoutError):
    return {
        "reachable": False,
        "banner": None,
        "latency_ms": None,
        "error": "Connection timed out (Host powered off, network partitioned, or firewall dropped packets)"
    }
except OSError as e:
    return {
        "reachable": False,
        "banner": None,
        "latency_ms": None,
        "error": f"OS network error: {e}"
    }
```

---

## 3. Test Scenarios We Will Run

Jab hum `probe_engine.py` likhenge, hum use 3 alag-alag real-world cases par test karenge:
1. **Local / Lab Machine (SSH Running):** `localhost:22` ya live IP -> Must return `reachable: True` with OpenSSH banner.
2. **Refused Port:** `localhost:9999` (jahan koi service nahi chal rahi) -> Must catch `ConnectionRefusedError` in < 2ms!
3. **Black Hole IP (Timeout):** `192.0.2.1` (RFC 5737 TEST-NET address jo kabhi answer nahi karega) -> Must hit strict 2.5s timeout cleanly without hanging the process!
