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

---

## 4. Practice Implementation (`probe_engine.py`)

> Commit review (2026-10-16, Codex on Windows): the three supplied tests passed locally, using two simulated services and one network-dependent timeout. This is not full RFC 4253 validation or host authentication: a single `recv` may return a partial banner, and an `SSH-` prefix can be forged. Socket timeouts apply per operation rather than establishing a total probe deadline. Refusal and timeout do not prove host state or a specific failure cause. The explanations below remain draft material pending technical review.

```python
import socket
import time

def probe_ssh_endpoint(address: str, port: int, timeout: float = 2.5) -> dict:
    """
    Probes an SSH endpoint by completing a TCP handshake and verifying
    the RFC 4253 SSH identification banner without authenticating.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Bounded execution: Never leave timeout as None to avoid indefinite hangs
    s.settimeout(timeout)

    try:
        start_time = time.perf_counter()
        s.connect((address, port))
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # OpenSSH servers send their identification banner immediately upon TCP connect
        raw_bytes = s.recv(256)
        banner = raw_bytes.decode("utf-8", errors="replace").strip()

        if not banner.startswith("SSH-"):
            raise ValueError(f"Port is open, but service is not SSH (received: {banner[:30]!r})")

        return {
            "reachable": True,
            "banner": banner,
            "latency_ms": latency_ms,
            "error": None
        }

    except ValueError as e:
        return {
            "reachable": False,
            "banner": None,
            "latency_ms": None,
            "error": str(e)
        }
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
    finally:
        s.close()
```

---

## 5. Line-by-Line Post-Mortem (Under the Hood Mechanics)

### 1. Setup & Bounded Sockets
* **`import socket`:** OS ke C-level Berkeley Sockets API ko call karta hai.
* **`socket.AF_INET`:** IPv4 address family select karta hai.
* **`socket.SOCK_STREAM`:** TCP stream (reliable, connection-oriented) select karta hai.
* **`s.settimeout(timeout)` ⚠️:** Python ka default timeout `None` hota hai (infinite blocking). Agar remote machine switch off hai, toh OS ka kernel 2–3 minute tak packet retransmit karta rahega. Bounded timeout backend ko freeze hone se bachata hai.

### 2. TCP 3-Way Handshake & Latency
* **`s.connect((address, port))`:** Wire par `SYN -> SYN-ACK -> ACK` sequence complete karta hai.
* **`time.perf_counter()`:** Network round-trip time (RTT) measure karta hai milliseconds mein.

### 3. RFC 4253 Banner & Imposter Protection
* **`s.recv(256)`:** Humne server ko koi data nahi bheja. OpenSSH server connection bante hi turant apna banner bhejta hai: `SSH-2.0-OpenSSH_9.0...`.
* **`banner.startswith("SSH-")`:** Agar port 22 par kisi ne HTTP server ya honey-pot chala rakha ho, toh `HTTP/1.1 200 OK` milega. Yeh check imposter services ko turant pakad leta hai.

### 4. Exception Shield (Network Truth Mapping)
* **`ConnectionRefusedError`:** Remote kernel ne explicit **`TCP RST`** packet bheja. Proof: Machine ON hai, par SSH daemon band hai.
* **`TimeoutError`:** Zero packets wapas aaye. Proof: Firewall packet drop kar raha hai (`-j DROP`), cable cut hai, ya host off hai.
* **`finally: s.close()`:** Resource leak prevention. Agar socket close nahi karoge toh Linux bolega: `OSError: Too many open files`.

---

## 6. Previously Recorded Automated Test Output ([`test_probe.py`](test_probe.py))

```text
=================================================================
RUNNING PRACTICE 05: PROBE ENGINE VERIFICATION
=================================================================

[TEST 1] Testing Valid OpenSSH Server (Mock on port 2224)...
  -> Result: {'reachable': True, 'banner': 'SSH-2.0-OpenSSH_9.0p1 Ubuntu-1ubuntu1', 'latency_ms': 0.37, 'error': None}
  -> [PASS] Valid SSH Banner correctly detected with latency!

[TEST 2] Testing Non-SSH Service (Mock HTTP Server on port 2225)...
  -> Result: {'reachable': False, 'banner': None, 'latency_ms': None, 'error': "Port is open, but service is not SSH (received: 'HTTP/1.1 200 OK\\r\\nServer: Apach')"}
  -> [PASS] Non-SSH service gracefully caught without crashing!

[TEST 3] Testing Packet Drop / Timeout (RFC 5737 192.0.2.1)...
  -> Result: {'reachable': False, 'banner': None, 'latency_ms': None, 'error': 'Connection timed out (Host powered off, network partitioned, or firewall dropped packets)'}
  -> [PASS] Bounded timeout expired cleanly without hanging!

=================================================================
ALL 3 PROBE TESTS PASSED SUCCESSFULLY! (EXIT CODE 0)
=================================================================
```
