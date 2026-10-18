# Document 10: Linux System Metrics Architecture & Node Exporter

> **Curriculum Navigation:**
> * **Phase 1: Foundation & Architecture:** [Documents 01–02](../foundation/01-vision-and-first-principles.md)
> * **Phase 2: Milestone 1 — Node Inventory & Onboarding:** [Documents 03–07](../node-inventory/03-registration-flow.md)
> * **Phase 3: Milestone 2 — Availability Detection & Probing:** [Documents 08–09](../connectivity-probing/08-linux-probing-and-handshakes.md)
> * **Phase 4: Milestone 3 — Metrics & Observability (This Phase):**
>   * **Document 10 (This Document): Linux System Metrics Architecture & Node Exporter**
>   * [Document 11: Prometheus Scrape Pipeline & Grafana Dashboards](11-prometheus-and-grafana-pipeline.md)

---

## 1. The Core Problem: Where Do Numbers Come From in Linux?

In Milestones 1 and 2, we answered:
1. *Which machines belong to our fleet?* (Node Inventory in SQLite)
2. *Is the SSH daemon listening and responsive?* (SSH Banner Probe Engine)

Now we enter **Official Requirement 2**:
> *"Collection, storage, and visualization of system metrics using **Prometheus and Grafana**."*

When an engineer opens a dashboard and sees:
```text
Node-01 CPU Usage: 78.4% | Memory Used: 3.2 GB / 8.0 GB | Disk Read: 14 MB/s
```

Where did the number `78.4%` physically come from?

Does Linux have a file on disk called `cpu_percentage.txt` where the kernel writes `78.4`?\
**No!**

To build an enterprise observability system, we must understand the foundational source of truth: **The Linux Kernel and the `/proc` Virtual Filesystem.**

---

## 2. Linux Kernel Internals: The `/proc` Virtual Filesystem

In Linux, there is a special directory called `/proc`.

If you inspect `/proc` with `ls -l /proc`, you will see hundreds of files:
* `/proc/stat`
* `/proc/meminfo`
* `/proc/diskstats`
* `/proc/net/dev`

### 💡 The Big First Principle: `/proc` Does NOT Exist on Your Hard Drive!
Files in `/proc` consume **0 bytes of disk space**.\
When your program opens `/proc/stat` and reads it, **the Linux Kernel dynamically generates those text bytes on-the-fly directly out of kernel memory!**

It is a window directly into the live brain of the operating system.

---

### A. How CPU Usage Works: `/proc/stat` & Jiffies

If you run `cat /proc/stat` on any Linux machine, the very first line looks like this:

```text
cpu  2255 34 2290 22625563 6290 127 456 0 0 0
```

Notice: There is **NO percentage**! There is no `78.4%`!

What are these numbers?\
They are raw **CPU Ticks (Jiffies)** since the machine was booted. A "tick" is a slice of time (typically $1/100^{\text{th}}$ or $1/1000^{\text{th}}$ of a second) measured by the CPU hardware timer.

The columns represent:
1. `user`: Ticks spent running normal user applications (Python, Chrome, Node.js).
2. `nice`: Ticks spent running low-priority background processes.
3. `system`: Ticks spent executing Linux kernel syscalls (I/O, memory allocation).
4. `idle`: Ticks the CPU spent doing absolutely nothing (waiting for work).
5. `iowait`: Ticks spent waiting for disk or network I/O to complete.
6. `irq` & `softirq`: Ticks handling hardware and software interrupts.

#### How Do You Calculate Percentage? (The Delta Principle)
Because these numbers only increase, a single reading tells you nothing about current CPU load.\
To find CPU usage, an observability agent must take **two readings separated by a time delta ($\Delta t$):**

$$\text{Total Ticks} = \text{user} + \text{system} + \text{idle} + \text{iowait} + \dots$$

$$\Delta \text{Total} = \text{Total}_2 - \text{Total}_1$$
$$\Delta \text{Idle} = \text{Idle}_2 - \text{Idle}_1$$

$$\text{CPU Usage \%} = \left( 1 - \frac{\Delta \text{Idle}}{\Delta \text{Total}} \right) \times 100$$

---

### B. How Memory Usage Works: `/proc/meminfo`

If you run `cat /proc/meminfo`, Linux gives you exact memory allocation counters:

```text
MemTotal:       16280456 kB
MemFree:         4892100 kB
MemAvailable:   11245080 kB
Buffers:          345120 kB
Cached:          6412900 kB
```

> [!IMPORTANT]
> **The Classic Linux Memory Trap: `MemFree` vs `MemAvailable`**
> In Linux: *"Unused RAM is wasted RAM."*
> If you have 16 GB of RAM, Linux uses all spare memory as disk cache (`Cached`) to make file reading instant.
> * `MemFree` is literally empty, untouched RAM. It is often very small (e.g. 500 MB).
> * `MemAvailable` is the true metric! It represents how much RAM can be immediately reclaimed for applications without freezing the system (Free + Reclaimable Caches).
>
> If an operator sees `MemFree = 500 MB` on an 8 GB server, they might panic. But a real systems engineer checks `MemAvailable`!

---

## 3. Why Can't We Just Store Metrics in SQLite? (Relational vs. Time-Series)

Students often ask:
> *"Bhai, hamare paas already `inventory.db` (SQLite) hai na! Hum har 5 second mein CPU and RAM table mein INSERT kyun nahi kar dete?"*

Let's do the math on a production fleet:
* Fleet size: **50 Linux nodes**.
* Metrics collected: **100 metrics per node** (CPU cores, RAM buffers, disk I/O, network packets).
* Scrape frequency: **Every 5 seconds**.

$$\frac{50 \text{ nodes} \times 100 \text{ metrics}}{5 \text{ seconds}} = 1,000 \text{ writes per second!}$$
$$1,000 \text{ writes/sec} \times 86,400 \text{ seconds/day} = \mathbf{86.4 \text{ Million rows per day!}}$$

### Why Relational Databases (SQLite / MySQL) Explode:
1. **Locking & Contention:** SQLite uses file-level locking. 1,000 writes/second will cause immediate `database is locked` deadlocks.
2. **B-Tree Index Overhead:** In relational databases, every new row updates multiple B-Tree indexes on disk. Disk I/O skyrockets, choking your server.
3. **Storage Bloat:** 86 million uncompressed SQL rows will consume gigabytes of disk in a few days.

### The Solution: Time-Series Databases (TSDB — Prometheus)
Observability requires a **Time-Series Database (TSDB)**:
* **Append-Only:** Historical data is never updated (`UPDATE` does not exist in TSDB).
* **Double-Delta Compression (Gorilla Algorithm):** Prometheus compresses timestamps and floating-point values down to **1.37 bytes per sample** (over 90% disk space reduction!).
* **In-Memory Chunking:** Keeps the most recent 2 hours of data in RAM for instant queries.

---

## 4. What is Prometheus Node Exporter?

We cannot have our central Fleet Manager SSH into 50 machines every 5 seconds to run `cat /proc/stat` (the SSH crypto overhead would melt the CPU).

Instead, the industry standard is **Prometheus Node Exporter**:
* It is a single, lightweight binary written in Go.
* It runs as a **Daemon** on the target Linux node.
* It listens on TCP port **`9100`**.
* Whenever an HTTP `GET /metrics` request arrives, Node Exporter reads `/proc` in microseconds and outputs plain-text, standardized metrics:

```text
# HELP node_cpu_seconds_total Seconds the CPUs spent in each mode.
# TYPE node_cpu_seconds_total counter
node_cpu_seconds_total{cpu="0",mode="idle"} 2.2625563e+07
node_cpu_seconds_total{cpu="0",mode="system"} 2290.45
node_cpu_seconds_total{cpu="0",mode="user"} 2255.12

# HELP node_memory_MemAvailable_bytes Memory information field MemAvailable_bytes.
# TYPE node_memory_MemAvailable_bytes gauge
node_memory_MemAvailable_bytes 1.151496192e+10
```

Notice the structure:
$$\text{metric\_name}\{\text{label1}=\text{"value"}, \text{label2}=\text{"value"}\} \quad \text{numeric\_value}$$

---

## 5. Pull vs. Push Model: Why Does Prometheus Scrape?

There are two architectural ways to collect telemetry:

```
[ PUSH MODEL: Node -> Central Server ]
Node sends HTTP POST every 5s.
Risk: If 1,000 nodes reboot at once, they storm the central server (DDoS).

[ PULL MODEL: Central Server -> Node (Prometheus) ]
Prometheus controls the schedule and sends HTTP GET /metrics.
Benefit: Central server controls its own load (Backpressure protection).
```

### Why Pull Wins in Fleet Management:
1. **Built-in Health Detection:** If Prometheus scrapes Node 2 on port 9100 and gets a timeout, Prometheus immediately knows the node is down! In a push model, if a node goes silent, you have to wait and guess whether it's dead or just slow.
2. **No Central Server Overload:** The central monitoring server controls its own pacing.

---

## 6. The Golden Rule of Observability: Missing Metrics $\neq$ 0

> [!CAUTION]
> **The Most Dangerous Trap in Monitoring:**
> If a Linux machine powers off or its network cable is unplugged, its CPU usage is **NOT 0%**.
>
> If you record `CPU = 0%`, your dashboard will show: *"Great news! The server is cool, completely idle, and happy!"*
> In reality, the server is dead or unreachable.
>
> **In Prometheus and Grafana:**
> A failed scrape results in **`NaN` (Not a Number) or Missing Data (Gap in the graph)**.
> Prometheus records a special synthetic metric:
> * `up{job="node"} == 1` $\to$ Scrape succeeded.
> * `up{job="node"} == 0` $\to$ Scrape failed (Host unreachable / down).
>
> Never convert missing telemetry into zero!

---

## 7. Check Understanding

Before we set up Node Exporter and Prometheus scraping in Document 11, test your systems understanding on this real-world scenario:

### The Scenario
You look at a Linux machine's memory report:
* Total RAM: `8192 MB` (8 GB)
* `MemFree`: `300 MB`
* `Buffers + Cached`: `6200 MB`
* `MemAvailable`: `6500 MB`

An intern runs into your office in a panic and says:\
*"Bhai! Server is at 96% RAM usage! We only have 300 MB left! We must restart the machine or buy more RAM immediately!"*

### Questions:
1. Is the intern correct? Is the server running out of RAM?
2. What will the Linux kernel do if a new Python process suddenly starts and demands 4 GB of RAM?
3. Which metric should your Grafana alert be configured on: `MemFree` or `MemAvailable`?

<details>
<summary><b>Click to check the worked answer</b></summary>

**Answer:**
1. **No, the intern is completely wrong!** The server has over **6.5 GB (80%) of usable memory available**.
2. **The Linux kernel will instantly evict the disk caches (`Cached`).** Disk caches are clean copies of files stored in RAM for fast reading. If an application needs memory, the kernel drops the cache in sub-milliseconds and hands that physical RAM to the Python process without crashing.
3. **Always configure alerts on `MemAvailable` (or `node_memory_MemAvailable_bytes`).** An alert on `MemFree` would trigger false alarms 24/7 because a healthy Linux kernel deliberately keeps `MemFree` close to zero by caching active disk data.

</details>

---

## 🛠️ What Comes Next?

Now that we understand the Linux `/proc` architecture and Node Exporter's role:
👉 **[Document 11: The Prometheus Scrape Pipeline & Grafana Dashboards](11-prometheus-and-grafana-pipeline.md)**\
*(We will configure `prometheus.yml` to automatically scrape registered nodes, query metrics using PromQL, and visualize them on live Grafana dashboards!)*
