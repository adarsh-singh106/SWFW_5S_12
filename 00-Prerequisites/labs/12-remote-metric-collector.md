# Lab 12: The Remote Collector (SSH + Python + Honest Failure)

[All labs](../README.md) | [Previous: local metrics](11-reading-local-metrics.md)

**Budget:** 15 minutes.  
**Architecture:** 
- **Controller (Debian):** Runs Python collector script.
- **Managed Node (Ubuntu):** Provides raw `/proc/uptime` over SSH (port 2222).

```text
┌──────────────────────────────────────────────┐
│        NODE 1: Debian (Controller)           │
│  Runs: python3 remote_collector.py           │
│                                              │
│  1. Issues: ssh -p 2222 kurai@127.0.0.1      │
│             "cat /proc/uptime"               │
│  2. Captures remote stdout                   │
│  3. Parses float values                      │
│  4. Handles failure cleanly if unreachable   │
└──────────────────────────────────────────────┘
                       │
                       │ (Encrypted SSH / Port 2222)
                       ▼
┌──────────────────────────────────────────────┐
│          NODE 2: Ubuntu (Target Node)        │
│  sshd streams: /proc/uptime                  │
└──────────────────────────────────────────────┘
```

---

## 1. The Milestone: Our First Real Fleet Collector

In Lab 10, you used the command-line to run commands on Ubuntu from Debian.  
In Lab 11, you parsed local `/proc/uptime` metrics into JSON using Python.

Now, we bring them together: **A Python script on Debian that remotely observes Ubuntu and handles network/node failure honestly.**

This completes the prerequisite finish line defined in our learning plan:
> *"Your own small collector retrieves and explains one observation from another Linux node and reports collection failure honestly."*

---

## 2. Step 1: Write `remote_collector.py` on Debian

In your **Debian terminal (`ash@DeathNode`)**, create `remote_collector.py`:

```bash
cat << 'EOF' > remote_collector.py
import subprocess
import json
import time

def collect_remote_uptime(node_id, host, port, user):
    collected_at = int(time.time())
    
    # We call ssh non-interactively with a strict timeout
    ssh_cmd = [
        "ssh",
        "-p", str(port),
        "-o", "BatchMode=yes",          # Never prompt for interactive password
        "-o", "ConnectTimeout=3",       # Give up after 3 seconds if node is down
        f"{user}@{host}",
        "cat /proc/uptime"
    ]
    
    try:
        proc = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Check if SSH itself failed (e.g. exit status non-zero)
        if proc.returncode != 0:
            return {
                "node_id": node_id,
                "status": "unreachable",
                "error": proc.stderr.strip() or "SSH connection failed",
                "collected_at": collected_at
            }
            
        # Parse the remote kernel stdout
        raw_output = proc.stdout.strip()
        uptime_str, idle_str = raw_output.split()
        uptime_seconds = float(uptime_str)
        idle_seconds = float(idle_str)
        
        return {
            "node_id": node_id,
            "target_host": host,
            "port": port,
            "metric": "system_uptime",
            "unit": "seconds",
            "uptime_seconds": round(uptime_seconds, 2),
            "uptime_hours": round(uptime_seconds / 3600, 2),
            "status": "healthy",
            "collected_at": collected_at
        }
        
    except subprocess.TimeoutExpired:
        return {
            "node_id": node_id,
            "status": "timeout",
            "error": "Node did not respond within 5 seconds",
            "collected_at": collected_at
        }
    except Exception as e:
        return {
            "node_id": node_id,
            "status": "error",
            "error_detail": str(e),
            "collected_at": collected_at
        }

if __name__ == "__main__":
    # Query our managed Ubuntu node
    result = collect_remote_uptime(
        node_id="ubuntu-node-02",
        host="127.0.0.1",
        port=2222,
        user="kurai"
    )
    print(json.dumps(result, indent=2))
EOF
```

---

## 3. Step 2: Run the Remote Collector (Happy Path)

Make sure your Ubuntu terminal has `ssh.socket` running.  
In your **Debian terminal**, run:

```bash
python3 remote_collector.py
```

Expected output:
```json
{
  "node_id": "ubuntu-node-02",
  "target_host": "127.0.0.1",
  "port": 2222,
  "metric": "system_uptime",
  "unit": "seconds",
  "uptime_seconds": ...,
  "uptime_hours": ...,
  "status": "healthy",
  "collected_at": ...
}
```

Notice what just happened:
1. Python invoked `ssh` under the hood as a child process.
2. It authenticated with your `id_ed25519` key into Ubuntu (`kurai`).
3. It read Ubuntu's `/proc/uptime`.
4. It parsed the remote string and outputted structured JSON!

---

## 4. Step 3: Test Controlled Failure (The Observability Test)

Now let's simulate an offline node:

1. In your **Ubuntu terminal (`kurai@DeathNode`)**, stop the SSH server:
   ```bash
   sudo systemctl stop ssh.socket ssh.service
   ```

2. In your **Debian terminal (`ash@DeathNode`)**, run the collector again:
   ```bash
   python3 remote_collector.py
   ```

Look at the output:
```json
{
  "node_id": "ubuntu-node-02",
  "status": "unreachable",
  "error": "ssh: connect to host 127.0.0.1 port 2222: Connection refused",
  "collected_at": ...
}
```

### Key Observation:
- Did Python crash with an uncaught traceback? **No.**
- Did Python report `uptime_seconds: 0`? **No.**
- It reported **honest degradation**: `"status": "unreachable"`.

---

## 5. Step 4: Restore Health & Verify Recovery

1. In your **Ubuntu terminal**, bring the service back up:
   ```bash
   sudo systemctl start ssh.socket
   ```

2. In **Debian**, run the collector again:
   ```bash
   python3 remote_collector.py
   ```

It immediately recovers and returns `"status": "healthy"`!

---

## 6. Checkpoint & Recall

Answer these aloud:
1. Why is setting a `ConnectTimeout` in automated SSH calls critical when collecting metrics from multiple nodes in a fleet?
2. When the node went down, why was returning `status: "unreachable"` better than letting the script crash or returning `0`?
3. How does this collector satisfy Requirement 1 and Requirement 3 of our Fleet Manager project?
