# Document 09: Background Health Probing & The Real-Time Dashboard

> **Curriculum Navigation:**
> * **Phase 1: Foundation & Architecture:** [Document 01](../foundation/01-vision-and-first-principles.md) · [Document 02](../foundation/02-engineering-pillars-and-portfolio.md)
> * **Phase 2: Feature 1 — Node Inventory:** [Documents 03–07](../node-inventory/03-registration-flow.md)
> * **Phase 3: Feature 2 — Node Availability & Probing:**
>   * [Document 08: Linux Connectivity Probing & The SSH Handshake](08-linux-probing-and-handshakes.md)
>   * **Document 09 (This Document): Background Health Probing & The Real-Time Dashboard**

---

## 1. The Problem: The Manual Button Trap

In Document 08 and Practice 05, we built the SSH banner prober and exposed it via `POST /api/nodes/{id}/probe`.

However, in an enterprise fleet of 50 to 500 Linux nodes:
* An operator cannot sit at a screen clicking a "Probe" button on each machine every 10 seconds.
* Systems fail unexpectedly at 3:00 AM when no operator is looking.

A production Fleet Manager must have a **continuous, autonomous availability detection engine** running in the background.

---

## 2. The Architecture: Offloading Blocking Network I/O in Async Python

FastAPI is built on top of **`asyncio`**, which uses a single-threaded cooperative event loop.

### The Pitfall
Our socket probe (`s.connect((address, port))` and `s.recv()`) performs **synchronous, blocking network I/O**.
If you run `probe_node(id)` directly inside an async function on the main event loop:
* When a node's connection times out (taking 2.5 seconds), the **entire FastAPI server freezes for 2.5 seconds**!
* No other HTTP requests can be handled while the prober waits for a packet.

### The First-Principles Solution: `asyncio.to_thread`
In Python 3.9+, standard library `asyncio` provides `asyncio.to_thread()`:
```python
# Offload synchronous socket probe to Python's background thread pool executor
await asyncio.to_thread(probe_node, node["id"])
```
This runs the blocking socket connection on a separate worker thread from Python's thread pool, allowing the main `asyncio` event loop to continue serving incoming web requests with **zero latency or freezing**!

---

## 3. The FastAPI Lifespan Pattern

Modern FastAPI uses the `@asynccontextmanager` lifespan pattern to safely manage background daemons:

```python
from contextlib import asynccontextmanager
import asyncio

async def background_probe_worker():
    while True:
        try:
            nodes = list_nodes()
            for node in nodes:
                await asyncio.to_thread(probe_node, node["id"])
        except Exception:
            pass
        await asyncio.sleep(15)  # Autonomous 15-second polling cycle

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start background probe worker
    worker_task = asyncio.create_task(background_probe_worker())
    yield
    # Shutdown: Cancel task cleanly when server stops
    worker_task.cancel()

app = FastAPI(title="Distributed Linux Fleet Manager", lifespan=lifespan)
```

---

## 4. The Operator Dashboard (`static/index.html`)

To satisfy the official requirement for a **"web-based system"**, we built a clean, zero-dependency, dark-themed Single Page Application:
1. **Onboarding Form:** Direct HTTP POST `/api/nodes` with real-time error alerts for invalid IPs and duplicates.
2. **Live Fleet Table:** Displays Node Name, Endpoint, Status Badge (`reachable` with latency / `unreachable` with error / `not_checked`), and OpenSSH Banner.
3. **Autonomous Polling:** The browser polls `/api/nodes` every 4 seconds, so when the background worker updates the database, the UI updates live without manual page reloads!

---

## 🛠️ Verification Command

Run the application locally:
```powershell
cd fleet-manager/docs/learn/node-inventory/practice
python -m uvicorn app:app --reload --port 8000
```
Open in your browser:
👉 **`http://127.0.0.1:8000/`** for the Live Dashboard!\
👉 **`http://127.0.0.1:8000/docs`** for the Interactive OpenAPI/Swagger UI!
