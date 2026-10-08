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

## 2. The Core Concept: Keys, Roles, and What They Protect

To understand SSH security, look at it in two simple layers:
1. **The Math (Layer 1):** What are Private and Public keys?
2. **The Role (Layer 2):** Who owns them (**Server** vs. **User**)?

```text
               ┌────────────────────────────────────────────────────────┐
               │                      SSH CONNECTION                    │
               └────────────────────────────────────────────────────────┘
                       ▲                                        ▲
                       │                                        │
           1. Host Key verifies the SERVER          2. User Key verifies YOU
           "Is this the real server?"               "Are you allowed to log in as ash?"
```

---

### Layer 1: The Cryptographic Pair (Private Key vs. Public Key)

Whenever you generate an SSH key, you never get a single key. You always generate a **matched twin pair**:

| Key | What it is | Real-world Analogy | Where it lives | Can you share it? |
| :--- | :--- | :--- | :--- | :--- |
| **Private Key** | The secret mathematical half. | The **physical key** in your pocket. | Only on the machine that created it. | **NEVER share it.** Anyone who has it can impersonate you. |
| **Public Key** | The public mathematical half matching your private key. | The **padlock** built specifically for your physical key. | Safe to copy to any machine you want to access. | **Yes, safe to share.** Giving someone a padlock doesn't give them your key. |

*Mathematical Rule:* Anything locked or signed by one half can only be unlocked or verified by the matching other half.

---

### Layer 2: The Two Roles (Host Key vs. User Key Pair)

Notice: **Both the Host Key and the User Key are Private/Public key pairs!**  
The difference is **WHO owns them** and **WHAT question they answer**:

#### 1. Host Key (Proves the Server's Identity)
* **Who owns it?** The **Server machine** (generated automatically when `openssh-server` is installed).
* **Where it lives:** In `/etc/ssh/ssh_host_*` on the server.
* **Question it answers:** *"Am I really connecting to the genuine server, or is an attacker on the network spoofing the server?"*
* **How it works:**
  - The server holds its **Host Private Key** in `/etc/ssh/`.
  - When a client connects, the server presents its **Host Public Key** (the fingerprint you see when connecting: `ED25519 key fingerprint is SHA256:...`).
  - When you accept it, your client saves that fingerprint in `~/.ssh/known_hosts`.
  - Future connections verify that the server's fingerprint still matches `known_hosts`.
* **Real-world Analogy:** The **official badge and photo ID** worn by a hotel receptionist. It proves you are talking to the real hotel staff, not an imposter standing in the lobby.

#### 2. User Key Pair (Proves Your Identity)
* **Who owns it?** **You (the client/user)** (generated when you run `ssh-keygen`).
* **Where it lives:** In `~/.ssh/id_ed25519` on your local client machine.
* **Question it answers:** *"Does the person connecting have permission to log in as user `ash` without typing a password?"*
* **How it works:**
  - You keep the **User Private Key** (`id_ed25519`) secret in your own `~/.ssh/` folder.
  - You place your **User Public Key** (`id_ed25519.pub`) into the server's `~/.ssh/authorized_keys` file.
  - When you connect, the server challenges your client: *"Prove you possess the private key that unlocks this public padlock."* Your client signs the challenge using its private key, and the server lets you in.
* **Real-world Analogy:** Your **personal keycard** that opens the door to room `ash`.

---

### Quick Comparison Summary

| Term | Who owns it? | Stored file name | What question does it answer? |
| :--- | :--- | :--- | :--- |
| **Private Key** | The creator of the key pair | `~/.ssh/id_ed25519` (User) or `/etc/ssh/ssh_host_*_key` (Server) | *"The secret proof used to sign and unlock."* |
| **Public Key** | Given to anyone who needs to verify you | `~/.ssh/id_ed25519.pub` (User) or `/etc/ssh/ssh_host_*.pub` (Server) | *"The lock that only the matching private key can open."* |
| **Host Key** | The **Server machine** | Server: `/etc/ssh/`<br>Client: `~/.ssh/known_hosts` | *"Client asking: Is this server authentic and genuine?"* |
| **User Key Pair** | **You (the User / Client)** | Client: `~/.ssh/id_ed25519`<br>Server: `~/.ssh/authorized_keys` | *"Server asking: Does this user have permission to log in?"* |

> [!TIP]
> **Rule of thumb to remember:**
> - **Host Key:** Protects **you from connecting to a fake server**.
> - **User Key:** Protects **the server from unauthorized users logging in**.

```text
Local Machine (Client)                             Target Machine (Server)
┌───────────────────────┐                         ┌─────────────────────────────┐
│  ssh ash@127.0.0.1    │ ──(Encrypted Port 22)──>│  sshd (Listening on Port 22)│
│  Uses: User Priv Key  │                         │  Checks: authorized_keys    │
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

### Deep Dive: Why SSH Demands `chmod 600` (Connecting to Lab 03)

Linux is a **multi-user system**. On a real server, multiple users or services (`ash`, `bob`, `www-data`, etc.) can execute programs on the same machine.

Remember what a **Private Key** is: it is the master credential proving your identity. If someone gets your private key, they can log into all your servers as **you** without a password.

#### 1. What "Loose Permissions" mean (from Lab 03):
If your private key has default file permissions like `chmod 644` (`-rw-r--r--`):

```text
-rw-r--r--
 │   │  └─ Others have READ permission (r--)  <-- DANGER!
 │   └──── Group has READ permission (r--)
 └──────── Owner has read & write (rw-)
```

Any other user on that machine could run `cat /home/ash/.ssh/id_ed25519` and steal your secret key!

#### 2. What "Strict Permissions" look like (`chmod 600`):
When you run `chmod 600 ~/.ssh/id_ed25519`:

```text
-rw-------
 │   │  └─ Others have NO permission (---)    <-- SAFE!
 │   └──── Group has NO permission (---)      <-- SAFE!
 └──────── Owner alone can read & write (rw-)
```

Only **you** (`ash`) can read or write the file. All other users get `Permission denied`.

#### 3. What SSH checks before connecting:
Before SSH uses your private key, it checks the file's permission bits. If group or others have read permissions, SSH deliberately refuses to use it and crashes out:

```text
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@         WARNING: UNPROTECTED PRIVATE KEY FILE!          @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
Permissions 0644 for '/home/ash/.ssh/id_ed25519' are too open.
It is required that your private key files are NOT accessible by others.
This private key will be ignored.
```

SSH essentially says: *"You left your master house key on the front porch where anyone walking by can photocopy it. I refuse to use this key until you put it in a private safe."*

#### 4. The Golden Rule of SSH Permissions:

| Path | Required Permission | Command | What it means |
| :--- | :--- | :--- | :--- |
| **`~/.ssh/`** (Folder) | `700` (`drwx------`) | `chmod 700 ~/.ssh` | Only you can enter (`x`) and list (`r`) this directory. |
| **`~/.ssh/id_ed25519`** (Private Key) | `600` (`-rw-------`) | `chmod 600 ~/.ssh/id_ed25519` | Only you can read or write your secret key. |
| **`~/.ssh/authorized_keys`** (Public list) | `600` (`-rw-------`) | `chmod 600 ~/.ssh/authorized_keys` | Only you can modify who is allowed to log in. |
| **`~/.ssh/id_ed25519.pub`** (Public Key) | `644` (`-rw-r--r--`) | *(Default is fine)* | Safe for anyone to read because it's public. |


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
