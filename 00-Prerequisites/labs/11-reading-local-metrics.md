# Lab 11: Where Do Metrics Come From? (The `/proc` Filesystem & Python Parsing)

[All labs](../README.md) | [Previous: two nodes and cross-machine SSH](10-remote-node-and-cross-machine-ssh.md)

**Budget:** 15 minutes.  
**Setup:** Your Debian terminal (`ash@DeathNode`). No `sudo` needed.

---

## 1. The Question: Where do tools get their numbers?

When you run commands like `uptime`, `free -m`, or when monitoring systems like Prometheus and Node Exporter show charts of CPU and Memory:
*Where do those numbers actually come from?*

They do not come from a magic database, and they are not invented by the command-line tools. They are provided directly by the **Linux Kernel** through a special virtual filesystem called **`/proc`**.

In this lab, you will:
1. Peek behind the curtain to see the raw numbers the kernel outputs.
2. Understand what the raw numbers mean and what units they use.
3. Write a small Python script to parse raw kernel metrics into structured data.

---

## 2. The Mental Model: The `/proc` Pseudo-Filesystem

`/proc` looks like a normal directory with files and subfolders, but:
- **It does not live on your disk or SSD.**
- It is a **pseudo-filesystem** (virtual filesystem) generated on-the-fly by the Linux Kernel in RAM.
- When you run `cat /proc/uptime`, the kernel intercepts your read request, inspects its internal clock timer, formats the numbers into text, and returns them to your process.

```text
  Your Command (cat / Python)
             │
             ▼  reads "/proc/uptime"
┌──────────────────────────────────────────────┐
│             LINUX KERNEL                     │
│  - Reads internal hardware timer             │
│  - Generates text: "7532.14 28410.89"        │
└──────────────────────────────────────────────┘
```

---

## 3. Step 1: Inspect Raw System Uptime

In your **Debian terminal (`ash@DeathNode`)**, run:

```bash
cat /proc/uptime
```

You will see two numbers separated by a space, for example:
```text
7842.51 31024.12
```

### What do these two numbers mean?
1. **First number (`7842.51`):** **Total system uptime** in seconds. The machine has been running for 7,842.51 seconds since boot.
2. **Second number (`31024.12`):** **Total idle time** accumulated across all CPU cores in seconds. (On a multi-core machine, this can be larger than the uptime because 4 cores idle for 10 seconds accumulate 40 idle seconds!).

Now compare this raw output with the formatted `uptime` tool:

```bash
uptime -p
```

The `uptime` tool simply read `/proc/uptime` and converted the raw seconds into human-readable words like `up 2 hours, 10 minutes`!

---

## 4. Step 2: Inspect Raw Memory Metrics

Now run:

```bash
head -n 5 /proc/meminfo
```

Look at the output:
```text
MemTotal:        8042124 kB
MemFree:         4821040 kB
MemAvailable:    6104920 kB
Buffers:           45120 kB
Cached:          1310480 kB
```

Notice two critical details:
- **Unit:** Everything is reported in **`kB`** (kilobytes, 1024 bytes).
- **Difference between `MemFree` and `MemAvailable`:**
  - `MemFree`: Memory with literally nothing in it.
  - `MemAvailable`: Memory that is actually available for new applications to start without swapping (includes reclaimable cache). This is the number production monitoring systems watch!

---

## 5. Step 3: Write a Python Metric Parser

Now let's write our first piece of **Fleet Manager logic**: a Python script that reads `/proc/uptime`, parses the raw float values, and formats them into clean JSON.

In **Debian (`ash@DeathNode`)**, create a file named `parse_uptime.py`:

```bash
cat << 'EOF' > parse_uptime.py
import json
import time

def get_uptime_metric():
    try:
        with open("/proc/uptime", "r") as f:
            content = f.read().strip()
            
        uptime_str, idle_str = content.split()
        uptime_seconds = float(uptime_str)
        idle_seconds = float(idle_str)
        
        return {
            "metric": "system_uptime",
            "unit": "seconds",
            "uptime_seconds": round(uptime_seconds, 2),
            "uptime_hours": round(uptime_seconds / 3600, 2),
            "collected_at": int(time.time()),
            "status": "healthy"
        }
    except Exception as e:
        return {
            "metric": "system_uptime",
            "status": "error",
            "error_detail": str(e)
        }

if __name__ == "__main__":
    result = get_uptime_metric()
    print(json.dumps(result, indent=2))
EOF
```

Run your Python script:

```bash
python3 parse_uptime.py
```

Expected output:
```json
{
  "metric": "system_uptime",
  "unit": "seconds",
  "uptime_seconds": 7915.22,
  "uptime_hours": 2.2,
  "collected_at": 1728448800,
  "status": "healthy"
}
```

---

## 6. The Golden Rule of Observability: Missing ≠ Zero

Notice how our Python function has a `try...except` block:

> [!CAUTION]
> **A failed metric must NEVER silently become zero.**
> In monitoring systems, if a server crashes, disconnects, or a file read fails, setting `uptime_seconds = 0` would mean: *"The server just rebooted 0 seconds ago."* That is a false diagnosis.
> An honest collector reports: `"status": "error"` or `"status": "unreachable"`. Missing data is completely different from the value zero!

---

## 7. Checkpoint & Recall

Close your notes and answer:

1. Does the file `/proc/uptime` occupy space on your hard drive? Where does its data come from?
2. What are the units of the numbers in `/proc/uptime` and `/proc/meminfo`?
3. Why should a monitoring agent report `status: "failed"` instead of returning `0` when a metric cannot be read?

Once you've run the script, share your output and your answers! In Lab 12, we will run this logic remotely to collect metrics from Node 2!

---

## 8. Lab 11 Review & Conceptual Answers

*(Appended after lab completion & recall review)*

### Part A: Checkpoint Recall Answers & Evaluation

1. **Does `/proc/uptime` occupy space on secondary storage (hard drive)? Where does its data come from?**
   - **Your Answer:** The uptime file is in RAM (not on secondary storage), and its data is calculated at runtime by the Linux kernel reading its hardware timer when the request comes in.
   - **Evaluation: 10/10.** Perfect explanation. It is a kernel pseudo-filesystem generated on-the-fly in memory.

2. **What are the units of the numbers in `/proc/uptime` and `/proc/meminfo`?**
   - **Your Answer:** Uptime is in seconds (system duration since boot), and meminfo is in kilobytes (`kB`), reporting RAM (primary memory) allocation.
   - **Evaluation: 10/10.** Spot-on.

3. **Why should a monitoring agent report `status: "failed"` instead of returning `0` when a metric cannot be read?**
   - **Your Answer:** Because returning 0 would falsely communicate that the system rebooted 0 seconds ago. If there is a connection issue, it should honestly state that the server is unreachable or failed, rather than fabricating a zero value.
   - **Evaluation: 10/10.** Flawless understanding of the fundamental observability rule: **Missing ≠ Zero**.

---

### Part B: Terminal Output Analysis

Your parsed JSON output:
```json
{
  "metric": "system_uptime",
  "unit": "seconds",
  "uptime_seconds": 469.28,
  "uptime_hours": 0.13,
  "collected_at": 1791522327,
  "status": "healthy"
}
```

- **Accuracy:** The raw seconds (`469.28`) correctly correspond to `~0.13` hours (~7.8 minutes).
- **Structure:** Clean key-value pairs formatted with measurement name, explicit unit, timestamp, and health status. This is the exact data contract a Prometheus exporter or custom collector uses.

