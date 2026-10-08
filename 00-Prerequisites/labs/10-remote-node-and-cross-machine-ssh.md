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

## 1. Architecture: Why Two Distros in WSL 2?

When you checked `ip -br addr` on both Debian and Ubuntu, you noticed:
```text
kurai@DeathNode:~$ ip -br addr
eth0  UP  172.20.135.178/20 ...

ash@DeathNode:~$ ip -br addr
eth0  UP  172.20.135.178/20 ...
```

### Why do both distros have the same IP and Hostname?
In Windows WSL 2:
1. **Shared Network & Kernel:** Microsoft runs a single lightweight virtual machine under the hood. All WSL distributions share the same virtual network adapter (`eth0`), kernel, and default machine hostname.
2. **Isolated Operating Systems & Filesystems:** Each distro has its own **completely independent root filesystem (`/`)**, separate user accounts (`ash` on Debian vs `kurai` on Ubuntu), separate package managers (`apt`), and separate system services.

### The Port Conflict Problem (Connecting back to Lab 08):
In Lab 08, you learned: **Only one process can listen on a specific port at a time.**
- Debian's SSH server is already listening on **Port 22**.
- If Ubuntu also tries to listen on Port 22, it will fail with: `Address already in use`.

**The Solution:** We configure Ubuntu's SSH server to listen on Port **`2222`**!

---

## 2. Step 1: Install & Set Up Ubuntu (Node 2)

If Ubuntu is not already installed, run this in **Windows PowerShell**:

```powershell
wsl --install -d Ubuntu
```

When Ubuntu launches for the first time:
1. Set UNIX username: `kurai`
2. Set and confirm your password.

---

## 3. Step 2: Configure Ubuntu's SSH Socket to Port 2222

In your **Ubuntu terminal (`kurai@DeathNode`)**, install the SSH server:

```bash
sudo apt update && sudo apt install -y openssh-server
```

In modern Ubuntu, SSH uses **systemd socket activation** (`ssh.socket`). To move Ubuntu's SSH socket to port `2222` (freeing port `22` for Debian), create a systemd socket override:

```bash
sudo mkdir -p /etc/systemd/system/ssh.socket.d
printf '[Socket]\nListenStream=\nListenStream=0.0.0.0:2222\nListenStream=[::]:2222\n' | sudo tee /etc/systemd/system/ssh.socket.d/listen.conf
sudo systemctl daemon-reload
sudo systemctl restart ssh.socket
```

Verify that Ubuntu is listening on port `2222`:

```bash
systemctl status ssh.socket --no-pager
```

Now return to your **Debian terminal (`ash@DeathNode`)** and restart Debian's SSH server so it reclaims port `22`:

```bash
sudo systemctl restart ssh
```

Check the listening sockets in either terminal with `ss -tlpn`:

```bash
ss -tlpn
```

You will see:
- Port **`22`** in `LISTEN` state (Debian).
- Port **`2222`** in `LISTEN` state (Ubuntu).

---

## 4. Step 3: Transfer Node 1's Public Key to Node 2

Switch to your **Debian terminal (`ash@DeathNode`)**.

We want user `ash` on Debian to log into user `kurai` on Ubuntu without a password.
Run `ssh-copy-id`, specifying port `2222`:

```bash
ssh-copy-id -p 2222 kurai@127.0.0.1
```

*(You can also use your internal IP `172.20.135.178` instead of `127.0.0.1`)*.

### What happens during this command:
1. **Host Verification:** SSH asks to verify the host key for port 2222. Type **`yes`**.
2. **Password:** Enter your **Ubuntu password** for user `kurai` (one last time).
3. **Success:** `Number of key(s) added: 1`.

Debian's public key is now appended to Ubuntu's `/home/kurai/.ssh/authorized_keys`!

---

## 5. Step 4: Test Cross-Node Remote Execution!

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

Now run the exact same command locally on Debian to contrast:

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

## 6. Step 5: Test Controlled Node Failure & Recovery

In Fleet Management, knowing when a node is **down** is just as important as knowing when it is healthy.

1. In your **Ubuntu terminal (`kurai@DeathNode`)**, stop the SSH socket and service:
   ```bash
   sudo systemctl stop ssh.socket ssh.service
   ```

2. In your **Debian terminal (`ash@DeathNode`)**, try to query the node:
   ```bash
   ssh -p 2222 -o ConnectTimeout=3 kurai@127.0.0.1 "hostname"
   ```

Observe the failure: What does it report? (`Connection refused`).

3. In **Ubuntu**, restore the service:
   ```bash
   sudo systemctl start ssh.socket
   ```

4. In **Debian**, rerun the query:
   ```bash
   ssh -p 2222 kurai@127.0.0.1 "hostname"
   ```
   It succeeds again!

---

## 7. Checkpoint & Recall

Answer these aloud:
1. Why did we need Ubuntu to listen on port `2222` instead of port `22` in this WSL environment?
2. When Debian runs `ssh -p 2222 kurai@127.0.0.1 "whoami"`, why does it print `kurai` and not `ash`?
3. Where is the **private key** stored, and where is the **public key** stored in this two-node setup?
