# Lab 08: Which machine and port am I talking to?

[All labs](../README.md) | [Previous: services and logs](07-services-and-logs.md)

**Budget:** 10–15 minutes.  
**Setup:** Two Linux terminal tabs (**Terminal A** and **Terminal B**) on your Debian WSL machine. No `sudo` needed.

---

## 1. The problem: reaching a program across a network

In Labs 01–07, everything happened on one local shell. You started processes, paused them with signals, and inspected system services.

Our Fleet Manager project eventually needs to **collect observations from other Linux machines**. 
A command on your laptop cannot just read `/proc/meminfo` or a log file on another machine using a local path like `cat /proc/meminfo`. It must talk across a **network**.

To talk across a network, your program needs to answer three questions:
1. **Which machine?** -> Identified by an **IP address**.
2. **Which door on that machine?** -> Identified by a **Port number**.
3. **Is any process waiting at that door?** -> Known as a **Listener** (or listening socket).

---

## 2. Keep these ideas separate

| Concept | What it is | Real-world analogy |
| :--- | :--- | :--- |
| **IP Address** | Numerical label for a network interface on a machine (e.g. `127.0.0.1` or `172.28.16.5`) | The street address of an apartment building |
| **Port** | A numbered communication channel (from `0` to `65535`) on that IP address | An apartment room number in that building |
| **Listener** | A running process that has opened a port and is waiting for incoming connections | A person sitting inside room 8080 waiting for someone to knock |
| **Loopback (`127.0.0.1` / `localhost`)** | A special internal network address that loops back to the *same* machine only | A memo slipped under your own door; cannot be reached from outside |

> [!IMPORTANT]
> **A port does not exist by magic.** A port only responds if an active **process** (with a PID!) has opened a socket and called "listen" on it. If no process is listening on that port, connection attempts are immediately rejected.

---

## 3. Step 1: Discover your network identities

In **Terminal A**, run:

```bash
ip -br addr
```

*(If `ip -br addr` gives an error or isn't formatted cleanly, run `ip addr`)*.

Look at the output columns:
- **`lo` (Loopback interface):** You will see `127.0.0.1/8`. This address means **"this machine right here"**.
- **`eth0` (or similar network interface):** You will see an IP address like `172.x.x.x` or `192.168.x.x`. This is the address other devices or the host use to talk to this Linux environment.

**Before continuing:** Write down your `lo` IP (`127.0.0.1`) and your primary interface IP.

---

## 4. Step 2: See who is currently listening

Linux provides the `ss` (Socket Statistics) tool to inspect network sockets.

In **Terminal A**, run:

```bash
ss -tlpn
```

Every flag explained:
- `ss`: Socket Statistics.
- `-t`: Show **TCP** sockets (the connection protocol used by HTTP, SSH, etc.).
- `-l`: Show only **listening** sockets (waiting for connections), not established active connections.
- `-p`: Show the **process** (name and PID) using the socket.
- `-n`: Show numerical port numbers instead of resolving service names (e.g. show `22` instead of `ssh`).

Look at the **Local Address:Port** column:
- If you see `127.0.0.1:25`, it means a process is listening only on loopback port 25.
- If you see `0.0.0.0:22` or `*:22`, it means a process is listening on **all** network interfaces on port 22.

---

## 5. Step 3: Start a practice listener in Terminal A

We will start a harmless practice server using Python's built-in HTTP module on port `8080`.

In **Terminal A**, run:

```bash
python3 -m http.server 8080
```

Expected output:
```text
Serving HTTP on 0.0.0.0 port 8080 (http://0.0.0.0:8080/) ...
```

Leave Terminal A open! Like `sleep 600` in Lab 05, this command stays in the foreground while it is running.

---

## 6. Step 4: Inspect the new listener in Terminal B

Open **Terminal B** (into the same Debian environment).

Run:

```bash
ss -tlpn
```

Look closely at the output:
1. Do you see a row with port `8080`?
2. Look at the `users:(...)` column for that row. What is the process name and **PID**?
3. Connect this to Lab 05: Which program on disk is running this process? (Answer: Python).

---

## 7. Step 5: Cause one harmless connection failure

Now we will test what happens when a client tries to connect to a port where **nobody is listening**.

In **Terminal B**, run:

```bash
curl -I http://127.0.0.1:8081
```

*(Notice we asked for port `8081`, but our server is on `8080`)*.

Expected result:
```text
curl: (7) Failed to connect to 127.0.0.1 port 8081: Connection refused
```

Now try the correct port:

```bash
curl -I http://127.0.0.1:8080
```

Expected result:
```text
HTTP/1.0 200 OK
...
```

Look at **Terminal A**: You should see a log line printed by the Python server showing the request received from `127.0.0.1`!

---

## 8. Step 6: Stop the listener and observe the change

1. Switch back to **Terminal A**.
2. Press **Ctrl+C** (which sends `SIGINT`, as you learned in Lab 06!) to stop Python.
3. Switch back to **Terminal B** and rerun:

```bash
curl -I http://127.0.0.1:8080
```

Predict before running: What will happen now that Python has stopped?

Run it. It reports **Connection refused**! The machine is still running, the IP `127.0.0.1` still exists, but the **listener process at port 8080 is gone**.

---

## 9. Checkpoint & Recall

Close your notes and answer these three questions aloud:

1. What is the difference between an **IP address** and a **port**?
2. If `curl` reports `Connection refused`, does that mean the entire computer is turned off? What does it actually prove?
3. When you run `ss -tlpn`, what does a line showing `0.0.0.0:8080` tell you about who is listening?

Record 30–60 seconds or reply with your answers to verify your mental model before we prepare for remote SSH access in Lab 09!
