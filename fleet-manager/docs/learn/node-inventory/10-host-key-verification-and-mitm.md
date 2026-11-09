# Deep Dive: SSH Host Identity, Man-In-The-Middle (MITM) Defense, and Node Onboarding

*Author: Antigravity Agent & Student Pair-Programming*  
*Date: 9 November 2026*  
*Context: SWFW-12 Semester 5 - Distributed Linux Fleet Management*

---

## 1. The Core Threat: What is a Man-In-The-Middle (MITM) Attack?

In a distributed fleet management system, the controller (Fleet Manager at `10.160.0.2`) connects over the network to remote Linux nodes (e.g., Node A at `10.160.0.5`) on TCP port 22.

The physical and logical network between the controller and the managed nodes (local switches, Wi-Fi, cloud VPC routers, DNS servers) is **untrusted by default**.

### How a Network Attacker Intercepts Connections
If an attacker (Mallory) is present on the network path (using ARP cache poisoning, DNS spoofing, rogue DHCP, or IP address takeover):

```text
[ Controller ]                           [ Attacker: Mallory ]                        [ Real Node A ]
 10.160.0.2                                   (In Path)                                 10.160.0.5
      |                                           |                                          |
      |--- 1. TCP SYN to 10.160.0.5:22 ---------->| (Intercepted!)                           |
      |                                           |--- 2. TCP SYN to Real Node A ----------->|
      |<-- 3. Mallory sends Fake Host Key --------|                                          |
      |                                           |<-- 4. Node A sends Real Host Key --------|
      |                                           |                                          |
      |=== 5. Session encrypted with Fake Key ===>|                                          |
      |    (Mallory DECRYPTS commands/secrets)    |=== 6. Session encrypted with Real Key ==>|
      |                                           |    (Mallory re-encrypts and forwards)    |
```

### The Impact of a MITM Breach
Without strict identity verification:
1. **Eavesdropping:** The attacker decrypts all SSH traffic in transit, stealing tokens, private data, and application outputs.
2. **Payload Injection:** The attacker can alter commands on the fly (e.g., modifying `systemctl status` into `rm -rf /`).
3. **Credential Theft:** The controller's authentication credentials or public-key signatures can be captured or abused.

---

## 2. How SSH Prevents MITM: Asymmetric Host Keys

Every Linux machine running OpenSSH automatically generates a set of asymmetric host key pairs during installation (stored in `/etc/ssh/`):
* **Private Host Key** (`/etc/ssh/ssh_host_ed25519_key`): Strictly kept secret on Node A (permissions `0600`, owned by `root`).
* **Public Host Key** (`/etc/ssh/ssh_host_ed25519_key.pub`): The cryptographic identity of the machine.

### The SSH Handshake (RFC 4253)
When Fleet Manager initiates a connection to Node A on TCP port 22:
1. **Key Exchange (KEX - e.g., Diffie-Hellman / Curve25519):** Both sides compute a shared ephemeral session encryption key without transmitting it over the wire.
2. **Server Authentication:** Node A sends its **public host key** and signs the key exchange hash using its **private host key**.
3. **Client Verification:** Fleet Manager verifies the signature using the received public host key.

> [!IMPORTANT]
> **The Critical Catch (The Identity Dilemma):**  
> Verifying the cryptographic signature only proves that whoever is on the other end of the wire possesses *that* private key.  
> It does **NOT** prove that the key actually belongs to **Node A**!  
> If an attacker (Mallory) is intercepting the connection, Mallory simply presents Mallory's own public key and signs with Mallory's own private key. The cryptographic math checks out 100%!  
> **Therefore, the client must verify: "Does this public key genuinely belong to Node A?"**

---

## 3. Why Compare the *Fingerprint* (and Why That Only)?

### What is a Public Key vs. a Fingerprint?
* **Raw Public Key:** A base64-encoded binary string containing the key algorithm and public parameters:
  ```text
  ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOmX3e9h5W2+8bTz7qK3xL4V1r9Y8p0V7m... (100+ chars)
  ```
  *(An RSA-4096 public key is over 500 characters long).*
* **Fingerprint:** The cryptographic hash (specifically SHA-256) of that raw public key binary blob:
  ```text
  SHA256:4K+Zq9eP6w5yR3uE9vGkL4Z2+x1p9Y8q0V7mXYZ1234 (43 characters)
  ```

### Why Do We Compare Fingerprints?
1. **Cryptographic Collision Resistance (Pre-Image Resistance):**  
   SHA-256 is mathematically designed so that finding any other key that produces the exact same hash requires on average $2^{128}$ operations (billions of years of compute). If the SHA-256 fingerprint matches, the underlying key is guaranteed to be identical.
2. **Human Cognitive Feasibility:**  
   A human administrator cannot reliably inspect 200–500 random characters without making errors. Comparing a 43-character hash string takes 10 seconds and prevents human fatigue errors.
3. **Native Linux Standard:**  
   The standard OpenSSH utility (`ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub`) computes and outputs the SHA-256 fingerprint by default.

---

## 4. Alternative Approaches: Why Not Use Something Else?

| Alternative | How It Works | Why Not Chosen for Fleet Manager? |
| :--- | :--- | :--- |
| **Trust On First Use (TOFU)**<br>`StrictHostKeyChecking=accept-new` | Client blindly accepts whatever key is presented on the very first connection. | **Dangerous:** If an attacker is already on the wire during first boot, you permanently trust the attacker. Strictly forbidden in secure fleet management. |
| **SSH Certificate Authority (SSH CA)** | A central CA signs each host key. Controller only trusts the CA public key once. | **Operational Complexity:** Requires deploying, securing, and maintaining a separate PKI CA (e.g. HashiCorp Vault, Smallstep). Too heavy for small fleets/homelabs. |
| **X.509 TLS Certificates**<br>(Web PKI / HTTPS) | Using commercial or internal SSL certificates for SSH. | OpenSSH intentionally avoids X.509 PKI due to ASN.1 parsing attack surfaces and commercial CA dependencies. |
| **DNSSEC + SSHFP** | Host fingerprints published as signed DNS records. | Requires strict DNSSEC infrastructure on all domains, which is rarely supported in private VPC subnets. |
| **Out-of-Band Fingerprint Comparison**<br>*(Fleet Manager's Choice)* | Controller scans key; operator checks console out-of-band and clicks Trust. | **The Gold Standard:** Zero external dependencies, 100% cryptographic certainty, works across bare-metal, WSL, and cloud VMs. |

---

## 5. Microscopic Step-by-Step Walkthrough of Fleet Manager Onboarding

Fleet Manager implements a 4-step onboarding workflow that guarantees secure enrollment:

```text
+-----------------------------------------------------------------------------------+
| STEP 1: Registration                                                              |
| Operator enters: Name ("node-1"), IP ("10.160.0.5"), Port (22)                    |
| -> Fleet Manager validates syntax, inserts into SQLite inventory                 |
| -> Initial state: NOT_CHECKED / PENDING_SETUP                                     |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| STEP 2: Host Identity Verification & Pinned Trust                                 |
| 1. UI triggers: POST /api/nodes/{id}/scan-host-key                                |
| 2. Controller connects to TCP port 22, reads server public key, hashes SHA-256    |
| 3. UI displays: "SHA256:4K+Zq9eP6w5yR3uE9vGkL4Z2+x1p9Y8q0V7m..."                |
| 4. Operator opens Node Console via trusted channel (GCP Console, WSL terminal):  |
|    $ sudo ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub                      |
| 5. Operator compares character-by-character.                                      |
| 6. Operator ticks "I independently compared..." and clicks "Trust Key".           |
| 7. UI triggers: POST /api/nodes/{id}/trust-host-key                               |
| 8. Controller writes entry into: /var/lib/fleet-manager/known_hosts               |
|    Host identity is now CRYPTOGRAPHICALLY PINNED!                                 |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| STEP 3: Controller User Key Authorization                                         |
| Controller has its own keypair (/var/lib/fleet-manager/id_ed25519[.pub])         |
| UI displays public key and copyable bootstrap command:                            |
| $ mkdir -p ~/.ssh && chmod 700 ~/.ssh && \                                        |
|   echo "<CONTROLLER_PUBLIC_KEY>" >> ~/.ssh/authorized_keys && \                   |
|   chmod 600 ~/.ssh/authorized_keys                                                |
| Operator runs this on the node console.                                           |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| STEP 4: Connectivity & Readiness Check                                            |
| 1. Operator clicks "Validate SSH Connectivity"                                    |
| 2. UI triggers: POST /api/nodes/{id}/connectivity-check                           |
| 3. Controller opens SSH session using Paramiko with RejectPolicy (known_hosts)    |
| 4. Controller authenticates using id_ed25519 private key                          |
| 5. Probes remote shell response.                                                  |
| 6. SUCCESS -> Node transitions to: READY and REACHABLE!                           |
+-----------------------------------------------------------------------------------+
```

---

## 6. Hands-On Practice: Onboarding Your Local WSL Instance

To onboard a local WSL instance or GCP VM into Fleet Manager:

### Step 1: Ensure SSH is Running in WSL
In your WSL distribution:
```bash
# Check if sshd is running
sudo service ssh status

# If not running, start it:
sudo service ssh start

# Note your WSL IP address:
ip addr show eth0 | grep inet
```

### Step 2: Get Your WSL Node's Host Key Fingerprint
In your WSL distribution:
```bash
sudo ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub
```
Keep this terminal open to compare the hash!

### Step 3: Register in Fleet Manager Dashboard
1. Open the Fleet Manager dashboard in your browser (`http://127.0.0.1:8000/dashboard`).
2. Click **Register Node**.
3. Name: `wsl-node-1`
4. Address: Your WSL IP address (e.g., `172.x.x.x`)
5. Port: `22`
6. Click **Add Node**.

### Step 4: Scan and Trust
1. Click **Onboard** / **Setup** on the new row.
2. In Step 2 (Identity), click **Scan Host Key**.
3. Verify that the displayed fingerprint matches the output from Step 2 above!
4. Tick the checkbox and click **Trust Host Key**.

### Step 5: Authorize Controller Key
1. Copy the bootstrap command shown in Step 3.
2. Paste it into your WSL terminal to authorize the controller key in `~/.ssh/authorized_keys`.

### Step 6: Validate Connectivity
1. Click **Validate SSH Connectivity** in Step 4.
2. Watch the status transition to **`READY`** and **`REACHABLE`**!
