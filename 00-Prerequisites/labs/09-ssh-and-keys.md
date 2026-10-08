# Lab 09: SSH — Client, Server, and Key Authentication

[All labs](../README.md) | [Previous: network endpoints](08-network-endpoints.md)

**Budget:** 15 minutes.  
**Setup:** Your Debian Linux terminal on `DeathNode`. This lab uses `sudo` once to install and start the SSH server.

---

## 1. Why Fleet Manager needs SSH

In Lab 08, you saw how a client (`curl`) connects to an open port (`8080`) on an IP address.

Our Fleet Manager will need to run commands on multiple Linux nodes to collect metrics and check system health. We cannot use plain HTTP or unencrypted connections for this because:
1. Anyone on the network could read or tamper with the data.
2. We need a secure way to execute shell commands remotely.
3. We cannot manually type a password every 10 seconds. We need automated, secure **public key authentication**.

**SSH (Secure Shell)** solves all three problems.

---

## 2. Keep these ideas separate

| Component | What it does | Real-world analogy |
| :--- | :--- | :--- |
| **SSH Client (`ssh`)** | The command-line program on your local machine that requests a connection | The visitor making the call |
| **SSH Server Daemon (`sshd`)** | The background service on the destination machine listening on **Port 22** | The security guard at door 22 |
| **Host Key (Server's identity)** | A cryptographic key pair belonging to the server itself | The security guard's official government ID badge |
| **User Key Pair (Client's identity)** | A private key + public key used to log you in without a password | A physical lock & key |
| **Private Key (`id_ed25519`)** | Stays secret on your client machine. **Never shared with anyone.** | The physical metal key in your pocket |
| **Public Key (`id_ed25519.pub`)** | Safe to share. Placed in `~/.ssh/authorized_keys` on the target machine. | The padlock mounted on the door |

```text
Local Machine (Client)                             Target Machine (Server)
┌───────────────────────┐                         ┌─────────────────────────────┐
│  ssh ash@127.0.0.1    │ ──(Encrypted Port 22)──>│  sshd (Listening on Port 22)│
│  Uses: Private Key    │                         │  Checks: authorized_keys    │
│  (~/.ssh/id_ed25519)  │                         │  (~/.ssh/authorized_keys)   │
└───────────────────────┘                         └─────────────────────────────┘
```

---

## 3. Step 1: Install and start the SSH service

Debian WSL often comes with the SSH client and server packages uninstalled.

In your Debian terminal, run:

```bash
sudo apt update
sudo apt install -y openssh-server openssh-client
```

Once installed, start the SSH service using `systemctl` (which you mastered in Lab 07!):

```bash
sudo systemctl start ssh
systemctl status ssh --no-pager
```

Check the status output:
- `Active:` should say `active (running)`.
- Note the `Main PID` of `sshd`.

Now check your listeners using the tool from Lab 08:

```bash
ss -tlpn
```

Look for the row with port **`22`**. You will see `sshd` in `LISTEN` state!

---

## 4. Step 2: The first connection & host verification

Let's test an SSH connection to our own machine over the loopback interface (`127.0.0.1`):

```bash
ssh ash@127.0.0.1
```

Because your SSH client has **never talked to this SSH server before**, it will display a warning:

```text
The authenticity of host '127.0.0.1 (127.0.0.1)' can't be established.
ED25519 key fingerprint is SHA256:...
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

### Why does this happen?
This is **Host Verification**. Your SSH client wants to make sure nobody is spoofing or intercepting the connection. 
- Type **`yes`** and press **Enter**.
- The client saves this fingerprint in `~/.ssh/known_hosts`. Future connections to `127.0.0.1` will be trusted automatically.
- Next, SSH asks for your password. Enter your Linux password.
- You are now logged in via SSH! Type `exit` to close the SSH session and return to your main shell.

---

## 5. Step 3: Generate an SSH Key Pair (No more passwords!)

For automated systems like Fleet Manager, entering passwords interactively is impossible. We use **SSH Keys**.

Run:

```bash
ssh-keygen -t ed25519 -C "ash-fleet-key"
```

1. **"Enter file in which to save the key":** Press **Enter** to accept the default (`/home/ash/.ssh/id_ed25519`).
2. **"Enter passphrase":** Press **Enter** twice for an empty passphrase (standard for automated service keys in this practice environment).

Now inspect what was created in your `~/.ssh` directory:

```bash
ls -l ~/.ssh
```

You will see:
- `id_ed25519`: **Your Private Key.** Notice the permissions (`-rw-------` or 600). Only you can read it!
- `id_ed25519.pub`: **Your Public Key.** This is what we give to servers.
- `known_hosts`: The fingerprint of the server you accepted in Step 2.

> [!CAUTION]
> **Lab 03 Connection:** SSH has strict security rules. If your private key (`id_ed25519`) has loose permissions (like `chmod 644` or `chmod 777` where others could read it), SSH will **refuse to use the key** and error out with `UNPROTECTED PRIVATE KEY FILE!`.

---

## 6. Step 4: Authorize your public key

To allow this key to log in without a password, we append the **public key** into the server's `~/.ssh/authorized_keys` file:

```bash
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
chmod 700 ~/.ssh
```

*(Notice how we used `>>` from Lab 02 to append, and `chmod` from Lab 03 to secure the permissions!)*

---

## 7. Step 5: Test passwordless login

Now run:

```bash
ssh ash@127.0.0.1
```

Notice what happened: **No password prompt!** The SSH client and server performed a cryptographic handshake using your key pair and logged you straight in.

Type `exit` to return to your local shell.

---

## 8. Step 6: Non-interactive remote command execution

A Fleet Manager does not open an interactive shell to type commands by hand. It sends a command, captures the output, and exits immediately.

Run:

```bash
ssh ash@127.0.0.1 "hostname && uptime"
```

Look at the result:
- The command `hostname && uptime` ran on the destination server.
- The output was streamed back across the encrypted SSH connection to your terminal.
- The SSH session exited immediately back to your local prompt.

---

## 9. Checkpoint & Next Step: Preparing Node 2

Answer these aloud:

1. What is the difference between `id_ed25519` and `id_ed25519.pub`? Which one should never leave your client machine?
2. Why does SSH fail with an error if your private key file has permissions `-rw-rw-rw-`?
3. When you run `ssh user@host "command"`, does the SSH session stay open waiting for you to type, or does it return immediately after running the command?

### Looking ahead to Node 2:
Right now, you tested SSH over loopback (`127.0.0.1`). In the next step, we will connect from this machine to a **second Linux node**!
We have a few simple options for our second node on your Windows machine:
1. **A second WSL distro** (e.g. install Ubuntu alongside Debian with `wsl --install -d Ubuntu`).
2. **A lightweight Docker container** running Debian/Ubuntu with SSH.

Let me know your answers and which option for the second node you prefer!
