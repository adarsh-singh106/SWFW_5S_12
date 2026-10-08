# Lab 10: Two Nodes — Cross-Machine SSH & Remote Execution

[All labs](../README.md) | [Previous: SSH and keys](09-ssh-and-keys.md)

**Budget:** 15 minutes.  
**Architecture:** 
- **Node 1 (Fleet Controller):** `Debian` (`DeathNode`), user `ash`, SSH on Port **`22`**.
- **Node 2 (Managed Node):** `Ubuntu` (`DeathNode`), user `kurai`, SSH on Port **`2222`**.

```text
┌────────────────────────────────────────┐         ┌────────────────────────────────────────┐
│        NODE 1: Debian (Controller)     │         │            NODE 2: Ubuntu              │
│        User: ash | OS: Debian 12       │         │        User: kurai | OS: Ubuntu 26.04  │
│                                        │         │                                        │
│  - Holds private key:                  │         │  - sshd listening on Port 2222         │
│    ~/.ssh/id_ed25519                   │ ──────> │  - Holds Node 1's public key in:       │
│  - Executes:                           │ (Port)  │    ~/.ssh/authorized_keys              │
│    ssh -p 2222 kurai@127.0.0.1 ...     │ (2222)  │  - Runs command on Ubuntu filesystem   │
└────────────────────────────────────────┘         └────────────────────────────────────────┘
```

---

## 1. First Principles: The WSL 2 Architecture Discovery

Look at your output from Ubuntu:
```text
kurai@DeathNode:~$ ip -br addr
eth0  UP  172.20.135.178/20 ...
```
And compare it to Debian:
```text
ash@DeathNode:~$ ip -br addr
eth0  UP  172.20.135.178/20 ...
```

### Why do both distros have the same IP and Hostname?
In Windows WSL 2:
1. **Shared Network & Kernel:** Microsoft runs a single lightweight virtual machine with one kernel. All WSL distributions share the same virtual network adapter (`eth0`) and hostname by default.
2. **Isolated Filesystems & Operating Systems:** Each distro has its own **completely separate root filesystem (`/`)**, separate user accounts (`ash` on Debian vs `kurai` on Ubuntu), separate package managers, and separate services.

### The Port Conflict Problem (Connecting back to Lab 08):
In Lab 08, you learned: **Only one process can listen on a specific port at a time.**
- Debian's SSH server is already listening on **Port 22**.
- If Ubuntu also tries to listen on Port 22, it will fail with: `Address already in use`.

**The Solution:** We will configure Ubuntu's SSH server to listen on Port **`2222`**!

---

## 2. Step 1: Install & Configure SSH on Port 2222 in Ubuntu (Node 2)

Inside your **Ubuntu terminal (`kurai@DeathNode`)**, run:

```bash
sudo apt update && sudo apt install -y openssh-server
```

Now configure Ubuntu's SSH daemon to listen on port `2222`:

```bash
printf 'Port 2222\n' | sudo tee /etc/ssh/sshd_config.d/port.conf
```

Start the SSH service:

```bash
sudo systemctl start ssh
systemctl status ssh --no-pager
```

Now inspect your listeners using the command from Lab 08:

```bash
ss -tlpn
```

Look at the output:
- You will see Port **`22`** (Debian's SSH server).
- You will see Port **`2222`** (Ubuntu's SSH server)!

Both operating systems are now concurrently offering SSH access on distinct ports!

---

## 3. Step 2: Transfer Node 1's Public Key to Node 2

Switch to your **Debian terminal (`ash@DeathNode`)**.

We want user `ash` on Debian to log into user `kurai` on Ubuntu without a password.
Run `ssh-copy-id`, specifying port `2222`:

```bash
ssh-copy-id -p 2222 kurai@127.0.0.1
```

*(You can also use `172.20.135.178` instead of `127.0.0.1`)*.

What happens:
1. **Host Verification:** SSH asks to verify the host key for port 2222. Type **`yes`**.
2. **Password:** Enter your **Ubuntu password** for user `kurai` (one last time).
3. Result: `Number of key(s) added: 1`.

Debian's public key is now stored in Ubuntu's `/home/kurai/.ssh/authorized_keys`!

---

## 4. Step 3: Test Cross-Node Remote Execution!

Now test executing commands on Ubuntu directly from Debian!

In your **Debian terminal (`ash@DeathNode`)**, run:

```bash
ssh -p 2222 kurai@127.0.0.1 "whoami && cat /etc/os-release | grep PRETTY_NAME"
```

Look at the result:
```text
kurai
PRETTY_NAME="Ubuntu 26.04.1 LTS"
```

Now run the exact same command locally on Debian:

```bash
whoami && cat /etc/os-release | grep PRETTY_NAME
```

Look at the local result:
```text
ash
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
```

### What just happened?
From your Debian machine, without typing a password:
1. You authenticated across the network to Ubuntu using your ED25519 keypair.
2. The remote command executed in **Ubuntu's filesystem**, as user **`kurai`**.
3. It returned Ubuntu's OS details back to your Debian shell.

---

## 5. Step 4: Test Controlled Node Failure

Now let's see what happens to our Fleet Controller when a node goes down:

1. In your **Ubuntu terminal (`kurai@DeathNode`)**, stop the SSH service:
   ```bash
   sudo systemctl stop ssh
   ```

2. In your **Debian terminal (`ash@DeathNode`)**, try to query the node:
   ```bash
   ssh -p 2222 -o ConnectTimeout=3 kurai@127.0.0.1 "hostname"
   ```

Observe the failure: What does it report? (`Connection refused`).

3. In **Ubuntu**, restore the service:
   ```bash
   sudo systemctl start ssh
   ```

4. In **Debian**, rerun the query. It succeeds again!

---

## 6. Checkpoint & Recall

Answer these aloud:
1. Why did we need Ubuntu to listen on port `2222` instead of port `22` in this WSL environment?
2. When Debian runs `ssh -p 2222 kurai@127.0.0.1 "whoami"`, why does it print `kurai` and not `ash`?
3. Where is the **private key** stored, and where is the **public key** stored in this two-node setup?
