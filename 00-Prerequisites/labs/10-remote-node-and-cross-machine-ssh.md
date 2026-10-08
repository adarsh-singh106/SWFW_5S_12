# Lab 10: Two Nodes — Cross-Machine SSH & Remote Execution

[All labs](../README.md) | [Previous: SSH and keys](09-ssh-and-keys.md)

**Budget:** 15 minutes.  
**Architecture:** 
- **Node 1 (Fleet Controller):** Your primary `Debian` machine (`DeathNode`).
- **Node 2 (Managed Node):** Your new `Ubuntu` machine.

```text
┌────────────────────────────────────────┐         ┌────────────────────────────────────────┐
│        NODE 1: Debian (DeathNode)      │         │            NODE 2: Ubuntu              │
│        Role: Fleet Controller          │         │            Role: Managed Node          │
│                                        │         │                                        │
│  - Holds private key:                  │         │  - sshd listening on port 22           │
│    ~/.ssh/id_ed25519                   │ ──────> │  - Holds Node 1's public key in:       │
│  - Executes:                           │  (SSH)  │    ~/.ssh/authorized_keys              │
│    ssh ash@<Ubuntu-IP> "hostname"      │         │  - Executes command and returns output │
└────────────────────────────────────────┘         └────────────────────────────────────────┘
```

---

## 1. Step 1: Install Ubuntu as Node 2

In **Windows PowerShell**, run:

```powershell
wsl --install -d Ubuntu
```

Windows will download and launch Ubuntu. When the new terminal window appears:
1. **Enter new UNIX username:** Type `ash` (keeping the same username as Debian makes things simple).
2. **New password:** Enter a password you remember.
3. **Retype password:** Confirm the password.

Once setup finishes, you will see the green prompt:
```text
ash@...:~$
```

---

## 2. Step 2: Identify each node's network address

Now you have two separate Linux nodes running concurrently! Let's check their identities.

### On Node 2 (Ubuntu terminal):
Run:
```bash
hostname
ip -br addr
```
*(If `ip -br addr` is not formatted cleanly, run `ip addr`)*.

Look at the `eth0` row. Write down:
- **Node 2 Hostname:** (e.g. `DeathNode` or `Ubuntu-PC`)
- **Node 2 IP Address:** (e.g. `172.x.x.x`)

### On Node 1 (Debian terminal):
Run:
```bash
hostname
```
Confirm it shows `DeathNode`.

---

## 3. Step 3: Ensure SSH Server is Running on Node 2

In your **Ubuntu terminal (Node 2)**:

```bash
sudo apt update && sudo apt install -y openssh-server
sudo systemctl start ssh
ss -tlpn
```

Check that port **`22`** is in the `LISTEN` state!

---

## 4. Step 4: Transfer Node 1's Public Key to Node 2

Now switch to your **Debian terminal (Node 1)**.

We want Node 1 to be able to run commands on Node 2 without typing passwords.
Linux provides a built-in helper command called `ssh-copy-id` that securely appends your public key to the remote server's `authorized_keys`.

In **Debian (Node 1)**, run:

```bash
ssh-copy-id ash@<Node-2-IP>
```
*(Replace `<Node-2-IP>` with the exact IP of your Ubuntu node you wrote down in Step 2)*.

What to expect:
1. **Host Verification prompt:** It asks to trust Node 2's host key fingerprint. Type **`yes`**.
2. **Password prompt:** Enter your Node 2 (`Ubuntu`) password one last time.
3. Message: `Number of key(s) added: 1`.

---

## 5. Step 5: Test Cross-Node Remote Execution!

Now for the magic of distributed systems!

Stay in your **Debian terminal (Node 1)**. Run:

```bash
ssh ash@<Node-2-IP> "hostname && uptime"
```

Look at the output:
- Did you need to enter a password? (No!)
- What hostname was printed? (Node 2's hostname!)
- Run `hostname` locally on Debian to compare.

You just executed a command on a completely separate operating system node and retrieved the observation back across the virtual network!

---

## 6. Step 6: Test Controlled Failure (Offline Detection)

In Fleet Management, knowing when a node is **down** is just as important as knowing when it is healthy.

1. In **Node 2 (Ubuntu)**, stop the SSH service:
   ```bash
   sudo systemctl stop ssh
   ```

2. In **Node 1 (Debian)**, attempt to run the command again:
   ```bash
   ssh -o ConnectTimeout=3 ash@<Node-2-IP> "hostname"
   ```

What observation did Node 1 return?
Is this a "Connection refused" or a timeout? Connect this back to Lab 08!

3. In **Node 2 (Ubuntu)**, restart the SSH service to restore health:
   ```bash
   sudo systemctl start ssh
   ```

---

## 7. Checkpoint & Recall

1. Why did we copy the **public key** (`id_ed25519.pub`) to Node 2 rather than the **private key** (`id_ed25519`)?
2. When Node 1 runs `ssh ash@<Node-2-IP> "uptime"`, on which CPU and kernel did the uptime command actually execute?
3. When you stopped SSH on Node 2 in Step 6, how did Node 1 report the failure?
