# Debian 12 & Ubuntu 26.04 Linux Deployment Runbook

This runbook defines the authoritative operational procedure to deploy, harden, monitor, back up, and restore the Distributed Linux Fleet Manager control plane reproducibly on clean Debian 12 (Bookworm) and Ubuntu 26.04 LTS systems, with verified procedures for Google Cloud Platform (GCE) multi-node topology.

---

## 1. System Requirements & Prerequisites

- **Operating System**: Debian 12 (Bookworm) or Ubuntu 26.04 LTS (x86_64 / aarch64).
- **Python**: CPython 3.12 managed via `uv` (isolated, reproducible toolchain).
- **Required System Packages**:
  ```bash
  sudo apt-get update && sudo apt-get install -y \
    apt-transport-https \
    software-properties-common \
    wget \
    gpg \
    curl \
    git \
    sqlite3 \
    openssh-client \
    prometheus \
    prometheus-node-exporter
  ```
- **Official Grafana Repository Installation**:
  ```bash
  # 1. Import official Grafana GPG signing key
  sudo mkdir -p /etc/apt/keyrings
  curl -fsSL https://apt.grafana.com/gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/grafana.gpg

  # 2. Add stable Grafana repository source
  echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list

  # 3. Update package index and install Grafana
  sudo apt-get update && sudo apt-get install -y grafana
  ```
- **Install `uv`** (standalone package runner):
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  sudo install -m 755 "$HOME/.local/bin/uv" /usr/local/bin/uv
  ```

---

## 2. Dedicated Service User & Directory Layout

To enforce least privilege, the control plane runs under a dedicated, unprivileged system user without an interactive login shell:

```bash
# 1. Create system user and primary group with a non-interactive shell
sudo useradd -r -s /usr/sbin/nologin -d /var/lib/fleet-manager -m fleet-manager

# 2. Create directory layout
sudo mkdir -p /opt/fleet-manager          # Application code & locked virtual environment (owned by root)
sudo mkdir -p /etc/fleet-manager          # Configuration & cryptographic keys (0700, fleet-manager)
sudo mkdir -p /var/lib/fleet-manager      # SQLite database, WAL/SHM state, and dynamic known_hosts (0700, fleet-manager)
sudo mkdir -p /var/backups/fleet-manager  # Database backups & manifests (0700, fleet-manager)

# 3. Apply ownership and restrictive permissions
# Note: Service logs stream directly to the systemd journal; no /var/log directory is required.
sudo chown -R fleet-manager:fleet-manager /var/lib/fleet-manager /var/backups/fleet-manager /etc/fleet-manager
sudo chmod 700 /var/lib/fleet-manager /var/backups/fleet-manager /etc/fleet-manager
```

---

## 3. Code Deployment & Locked Dependency Installation

Deploy application release artifacts to `/opt/fleet-manager` and install dependencies strictly from `uv.lock` without development packages:

```bash
# From the project repository, copy release files to /opt/fleet-manager
sudo cp -r src deploy scripts monitoring README.md pyproject.toml uv.lock /opt/fleet-manager/
sudo chown -R root:root /opt/fleet-manager
sudo chmod -R go-w /opt/fleet-manager
cd /opt/fleet-manager

# Install isolated CPython 3.12 and locked production dependencies
sudo env UV_PYTHON_INSTALL_DIR=/opt/fleet-manager/python /usr/local/bin/uv python install 3.12
PYTHON_BIN="$(sudo env UV_PYTHON_INSTALL_DIR=/opt/fleet-manager/python /usr/local/bin/uv python find 3.12)"
sudo env UV_LINK_MODE=copy /usr/local/bin/uv sync --locked --no-dev --python "$PYTHON_BIN"

# Ensure virtual environment and Python binaries are world-readable and executable
sudo chmod -R a+rX /opt/fleet-manager/python /opt/fleet-manager/.venv
```

---

## 4. Configuration & Cryptographic Secrets

### 4.1 Generate Environment Configuration
Copy the configuration template and generate a 32-character URL-safe operator bearer token:

```bash
sudo cp /opt/fleet-manager/deploy/fleet-manager.env.example /etc/fleet-manager/fleet-manager.env
sudo chmod 600 /etc/fleet-manager/fleet-manager.env
sudo chown fleet-manager:fleet-manager /etc/fleet-manager/fleet-manager.env

# Generate high-entropy operator token
SECRET_TOKEN=$(/opt/fleet-manager/.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))")
sudo sed -i "s|REPLACE_WITH_GENERATED_32_TO_128_CHAR_SECRET_TOKEN|${SECRET_TOKEN}|g" /etc/fleet-manager/fleet-manager.env

# Confirm SSH username and known_hosts path:
# Reference GCE topology uses 'fleetbootstrap' service user on managed nodes
# and stores dynamic known_hosts in /var/lib/fleet-manager/
```

### 4.2 Safe SSH Host-Key & Credential Management

#### A. Target Node Credentials: GCE Cloud Shell Bootstrap Key Deployment
In the Google Cloud environment, managed nodes have their public key enrolled via GCE instance metadata for user `fleetbootstrap`. The matching private key resides in Cloud Shell at `~/.ssh/fleet-bootstrap`.

Transfer and install this key securely onto `fleet-controller`:

```bash
# 1. From Cloud Shell, copy the private key to the controller via IAP tunnel:
gcloud compute scp ~/.ssh/fleet-bootstrap fleet-controller:/tmp/fleet-bootstrap \
  --zone=asia-south1-a --tunnel-through-iap

# 2. On fleet-controller, install the private key to /etc/fleet-manager/id_ed25519:
sudo install -m 600 -o fleet-manager -g fleet-manager /tmp/fleet-bootstrap /etc/fleet-manager/id_ed25519
rm -f /tmp/fleet-bootstrap

# 3. Ensure public key sidecar exists for operator verification:
ssh-keygen -y -f /tmp/fleet-bootstrap | sudo tee /etc/fleet-manager/id_ed25519.pub >/dev/null 2>&1 || true
sudo ssh-keygen -y -f /etc/fleet-manager/id_ed25519 | sudo tee /etc/fleet-manager/id_ed25519.pub
sudo chown fleet-manager:fleet-manager /etc/fleet-manager/id_ed25519.pub
sudo chmod 644 /etc/fleet-manager/id_ed25519.pub
```

#### B. Greenfield Key Generation (Alternative)
For environments where keys are generated directly on the controller:

```bash
sudo -u fleet-manager ssh-keygen -t ed25519 -N "" -f /etc/fleet-manager/id_ed25519
sudo chmod 600 /etc/fleet-manager/id_ed25519
sudo chmod 644 /etc/fleet-manager/id_ed25519.pub
```

#### C. Runtime Host-Key Trust Store Initialization (`known_hosts`)
The application dynamically performs atomic writes and file locking during in-browser host-key trust enrollment (`POST /api/nodes/{id}/trust-host-key`). Because `/etc/fleet-manager` is mounted read-only by systemd (`ReadOnlyPaths=/etc/fleet-manager`), the `known_hosts` file is placed in the writable state directory `/var/lib/fleet-manager`:

```bash
# Initialize known_hosts in writable state directory
sudo -u fleet-manager touch /var/lib/fleet-manager/known_hosts
sudo chmod 600 /var/lib/fleet-manager/known_hosts

# STRICT SECURITY REQUIREMENT: Host Key Verification
# Never disable host-key checking (StrictHostKeyChecking=no is strictly forbidden).
# When onboarding a node, the operator can:
# 1. Use the Web Dashboard "Scan & Verify Host Key" button to view the presented SHA-256 fingerprint.
# 2. Verify that fingerprint matches the node's console:
#      ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub
# 3. Confirm trust in the UI to enroll the key into /var/lib/fleet-manager/known_hosts.
```
```

---

## 5. Systemd Units Installation & Startup

> [!IMPORTANT]
> **Single-Worker Process Architecture Requirement**:
> Fleet Manager MUST be deployed with exactly one Uvicorn worker process (`--workers 1` in `fleet-manager.service`).
> In-process admission locks, concurrent SSH worker limits, background scheduler singleton execution, and in-memory Prometheus metric registries rely on single-process semantics. Multi-worker uvicorn deployment (`--workers > 1`) will cause concurrent scheduler conflicts and split in-memory telemetry states. Scaling is handled via asynchronous coroutines and bounded subprocess worker executors within the single supervisor.

Install the main control plane service, daily backup service, and daily backup timer (requires `sudo`):

```bash
# Copy systemd unit definitions
sudo cp /opt/fleet-manager/deploy/fleet-manager.service /etc/systemd/system/
sudo cp /opt/fleet-manager/deploy/fleet-manager-backup.service /etc/systemd/system/
sudo cp /opt/fleet-manager/deploy/fleet-manager-backup.timer /etc/systemd/system/

# Reload systemd and enable services
sudo systemctl daemon-reload
sudo systemctl enable --now fleet-manager.service
sudo systemctl enable --now fleet-manager-backup.timer
```

---

## 6. Prometheus & Grafana Provisioning for Multi-Node Fleet

### 6.1 GCE VPC Firewall Verification for Node Exporter
The Prometheus server on `fleet-controller` (`10.160.0.2`) collects metrics from managed nodes over TCP port 9100.
In Google Cloud Platform, the standard VPC network includes the default firewall rule `default-allow-internal`:
- Source IP range: `10.128.0.0/9`
- Allowed protocols/ports: `tcp:0-65535`, `udp:0-65535`, `icmp`
- Ingress: Internal only

Because the controller (`10.160.0.2`) and all managed nodes (`10.160.0.3`, `10.160.0.4`, `10.160.0.5`) reside inside the `10.160.0.0/24` subnet, which is fully contained within `10.128.0.0/9`, **TCP port 9100 communication is already permitted internally**.
No additional firewall rule creation is required or recommended. Do NOT expose port 9100 to the public internet (`0.0.0.0/0`).

### 6.2 Managed Node Exporter Installation (Nodes A, B, and C)
On each managed node (`fleet-node-a`, `fleet-node-b`, `fleet-node-c`), install and start the official Prometheus Node Exporter:

```bash
# Connect to each node via Cloud Shell IAP tunnel:
gcloud compute ssh fleet-node-a --zone=asia-south1-a --tunnel-through-iap
# (Repeat for fleet-node-b and fleet-node-c)

# Install and enable Node Exporter service:
sudo apt-get update && sudo apt-get install -y prometheus-node-exporter
sudo systemctl enable --now prometheus-node-exporter

# Verify local listening state:
sudo ss -tlpn | grep 9100
```

### 6.3 Controller Prometheus Configuration & Dynamic Targets
On `fleet-controller`, configure Prometheus to scrape the local control plane `/metrics` endpoint and discover remote node exporters via dynamic file-based discovery (`targets.json`).

Deploy the scrape configuration and populate `/etc/prometheus/targets.json` with the GCE internal IPs:

```bash
# 1. Deploy base Prometheus scrape configuration
sudo cp /opt/fleet-manager/monitoring/prometheus/prometheus.yml /etc/prometheus/prometheus.yml

# 2. Configure dynamic targets for Google Cloud topology:
cat << 'EOF' | sudo tee /etc/prometheus/targets.json
[
  {
    "targets": ["10.160.0.5:9100"],
    "labels": {
      "node_name": "fleet-node-a",
      "job": "node_exporter",
      "fleet": "gcp-production"
    }
  },
  {
    "targets": ["10.160.0.3:9100"],
    "labels": {
      "node_name": "fleet-node-b",
      "job": "node_exporter",
      "fleet": "gcp-production"
    }
  },
  {
    "targets": ["10.160.0.4:9100"],
    "labels": {
      "node_name": "fleet-node-c",
      "job": "node_exporter",
      "fleet": "gcp-production"
    }
  }
]
EOF

sudo chown -R prometheus:prometheus /etc/prometheus
sudo systemctl restart prometheus prometheus-node-exporter
```

### 6.4 Grafana Provisioning
Deploy the automated datasources and operational dashboard:

```bash
sudo mkdir -p /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards /etc/grafana/dashboards
sudo cp /opt/fleet-manager/monitoring/grafana/provisioning/datasources/prometheus.yaml /etc/grafana/provisioning/datasources/
sudo cp /opt/fleet-manager/monitoring/grafana/provisioning/dashboards/dashboards.yaml /etc/grafana/provisioning/dashboards/
sudo cp /opt/fleet-manager/monitoring/grafana/dashboards/fleet-monitoring.json /etc/grafana/dashboards/
sudo chown -R grafana:grafana /etc/grafana/provisioning /etc/grafana/dashboards
sudo systemctl restart grafana-server
```

---

## 7. Google Cloud IAP Operational Workflow & Testing Access

All instances in the test environment are deployed without public IP addresses, with ingress strictly restricted to Identity-Aware Proxy (CIDR `35.235.240.0/20`).

### 7.1 Operator Remote Access & IAP Architecture

All VMs are deployed without public IP addresses, with ingress strictly gated through Google Cloud Identity-Aware Proxy (CIDR `35.235.240.0/20`).

#### Secure Loopback Invariant & Access Method
- **Loopback Enforcement**: Fleet Manager binds strictly to `127.0.0.1:8000` and Grafana binds to `127.0.0.1:3000`. Neither port is exposed to the VPC or the public internet.
- **Port Forwarding via IAP SSH (Recommended & Verified)**:
  Because the existing GCP firewall allows IAP on SSH port 22, forward loopback ports directly through the authenticated IAP SSH channel without requiring any additional firewall rules:

```bash
# Launch encrypted port forwarding tunnel to controller (run from local workstation):
gcloud compute ssh fleet-controller \
  --project="project-3682976b-7d4a-465a-933" \
  --zone="asia-south1-a" \
  --tunnel-through-iap \
  -- -N -L 8000:127.0.0.1:8000 -L 3000:127.0.0.1:3000
```

Once the tunnel is active, access local forwarded endpoints in your browser:
- **Fleet Manager Dashboard**: `http://127.0.0.1:8000/dashboard`
- **Fleet Manager Metrics**: `http://127.0.0.1:8000/metrics`
- **Grafana Operational Dashboard**: `http://127.0.0.1:3000`

*(Note: Standalone `gcloud compute start-iap-tunnel fleet-controller 8000` is intentionally avoided because packets from `35.235.240.0/20` hit `eth0` rather than `127.0.0.1`, which would require binding to `0.0.0.0` or adding VPC ingress firewall rules. SSH port forwarding keeps services strictly on loopback).*

#### Operator Remote Shell Commands
```bash
# 1. SSH to fleet-controller via IAP tunnel (OS Login):
gcloud compute ssh fleet-controller --zone=asia-south1-a --tunnel-through-iap

# 2. SSH to managed nodes via IAP tunnel:
gcloud compute ssh fleet-node-a --zone=asia-south1-a --tunnel-through-iap
gcloud compute ssh fleet-node-b --zone=asia-south1-a --tunnel-through-iap
gcloud compute ssh fleet-node-c --zone=asia-south1-a --tunnel-through-iap

# 3. Secure file copy (SCP) of bootstrap key through IAP:
gcloud compute scp ~/.ssh/fleet-bootstrap fleet-controller:/tmp/fleet-bootstrap \
  --zone=asia-south1-a --tunnel-through-iap
```

### 7.2 Safe Reversible Host-Key Mismatch Failure Injection
To safely verify detection of host-key tampering or changes (`HOST_KEY_MISMATCH` / `CHECK_ERROR`), **never use `ssh-keygen -A`** (which skips existing keys). Use this explicit, fully reversible test procedure on one managed node (e.g. `fleet-node-c`):

```bash
# Connect to fleet-node-c via IAP:
gcloud compute ssh fleet-node-c --zone=asia-south1-a --tunnel-through-iap

# Step 1: Back up the verified host public and private keys
sudo cp -p /etc/ssh/ssh_host_ed25519_key /etc/ssh/ssh_host_ed25519_key.bak
sudo cp -p /etc/ssh/ssh_host_ed25519_key.pub /etc/ssh/ssh_host_ed25519_key.pub.bak

# Step 2: Overwrite with a newly generated disposable host key
sudo ssh-keygen -t ed25519 -N "" -f /etc/ssh/ssh_host_ed25519_key <<< y
sudo systemctl restart ssh

# Step 3: Trigger check from Controller / Web UI
# Observed Outcome: Connectivity check fails with HOST_KEY_MISMATCH.
# The UI displays a warning that the server identity has changed and refuses auto-reconnection.

# Step 4: Restore the authentic host key and verify recovery
sudo mv /etc/ssh/ssh_host_ed25519_key.bak /etc/ssh/ssh_host_ed25519_key
sudo mv /etc/ssh/ssh_host_ed25519_key.pub.bak /etc/ssh/ssh_host_ed25519_key.pub
sudo systemctl restart ssh

# Step 5: Retest connectivity from Controller / Web UI -> Node returns to REACHABLE.
```

---

## 7. Operational Commands

| Action | Command |
|---|---|
| **Start Service** | `sudo systemctl start fleet-manager` |
| **Stop Service** | `sudo systemctl stop fleet-manager` |
| **Restart Service** | `sudo systemctl restart fleet-manager` |
| **Service Status** | `sudo systemctl status fleet-manager` |
| **Live Journal Logs** | `journalctl -u fleet-manager -f` |
| **Liveness Probe** | `curl -fsS http://127.0.0.1:8000/healthz` |
| **Readiness Probe** | `curl -fsS http://127.0.0.1:8000/readyz` |
| **Prometheus Metrics** | `curl -fsS http://127.0.0.1:8000/metrics` |
| **Web Dashboard** | Open browser to `http://127.0.0.1:8000/dashboard` |
| **Backup Timer Status** | `systemctl list-timers fleet-manager-backup.timer` |
| **Backup Journal Logs** | `journalctl -u fleet-manager-backup -n 50` |

---

## 8. Scheduled Backup Automation & Retention Semantics

### 8.1 Automated Daily Backup
The `fleet-manager-backup.timer` triggers daily at `02:00:00 UTC` (with a randomized delay of up to 15 minutes to prevent thundering herds). It runs `fleet-manager-backup.service`, which executes:
```bash
/opt/fleet-manager/.venv/bin/python /opt/fleet-manager/scripts/backup_restore.py backup \
  /var/lib/fleet-manager/inventory.db \
  /var/backups/fleet-manager/inventory_latest.db
```

### 8.2 Retention Semantics
- **Single Latest Snapshot**: The automated backup schedule retains **exactly one** validated point-in-time snapshot (`inventory_latest.db`) and its companion manifest (`inventory_latest.db.manifest.json`).
- Each run copies pages into a temporary file, verifies `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and `user_version = 3`, and atomically replaces `inventory_latest.db`.
- **Historical Multi-Generation Retention**: If multi-day or archival retention is required, operators must configure an external rotation tool (such as `logrotate`, `restic`, or an enterprise backup agent) targeting `/var/backups/fleet-manager/`. The systemd backup service intentionally maintains only the single verified latest baseline.

### 8.3 Manual On-Demand Online Backup
Operators can perform an on-demand online backup at any time without stopping the application:
```bash
sudo -u fleet-manager /opt/fleet-manager/.venv/bin/python /opt/fleet-manager/scripts/backup_restore.py backup \
  /var/lib/fleet-manager/inventory.db \
  /var/backups/fleet-manager/inventory_$(date +%Y%m%d_%H%M%S).db
```

---

## 9. Offline Maintenance & Restoration Protocol

> [!CAUTION]
> **Database Restoration is an Offline Maintenance Operation.**
> Never attempt database restoration while `fleet-manager.service` is running. Restoring while the control plane is live causes file-descriptor invalidation, torn WAL replays, and silent data corruption.

Follow this exact step-by-step procedure:

### Step 1: Quiesce All Database Users & Timers
Stop both the application control plane and the automated backup timer/service to ensure zero write contention:
```bash
sudo systemctl stop fleet-manager fleet-manager-backup.timer fleet-manager-backup.service
```

### Step 2: Confirm Service is Inactive and No Database Handles Exist
```bash
# Verify systemd service state is inactive
sudo systemctl is-active fleet-manager
# Expected output: inactive

# Ensure zero active processes hold file descriptors to the database or sidecars
sudo fuser /var/lib/fleet-manager/inventory.db /var/lib/fleet-manager/inventory.db-wal
# Expected output: empty (no PIDs returned)
```

### Step 3: Inspect Backup Manifest and Integrity
Inspect the backup archive and manifest to confirm the timestamp, record counts, and expected SHA-256 digest:
```bash
# View backup metadata
cat /var/backups/fleet-manager/inventory_latest.db.manifest.json

# Confirm backup checksum
sha256sum /var/backups/fleet-manager/inventory_latest.db
```
*(Note: When `restore` is invoked in Step 4, `backup_restore.py` automatically performs pre-flight B-tree integrity check, foreign-key check, and SHA-256 manifest verification before touching the target database).*

### Step 4: Execute Offline Restore with Safety Snapshot Enabled
Execute restore using the hardened backup utility:
```bash
sudo -u fleet-manager /opt/fleet-manager/.venv/bin/python /opt/fleet-manager/scripts/backup_restore.py restore \
  /var/backups/fleet-manager/inventory_latest.db \
  /var/lib/fleet-manager/inventory.db
```

#### What Happens Internally:
1. **Safety Snapshot**: If `/var/lib/fleet-manager/inventory.db` exists, it is automatically backed up to `/var/lib/fleet-manager/inventory.db.pre_restore.bak` before any file modifications take place.
2. **Pre-flight & Post-flight Checks**: The backup file is verified for valid SQLite B-tree pages, foreign keys, and schema user_version 3.
3. **Atomic Swap**: The restored database is written to a temporary staging file and atomically renamed to `inventory.db`.
4. **Stale Sidecar Cleanup**: Any leftover `/var/lib/fleet-manager/inventory.db-wal` or `/var/lib/fleet-manager/inventory.db-shm` sidecars are unlinked immediately after replacement to prevent replaying stale WAL log entries into the new database.
5. **Fail-Safe Rollback**: If replacement or verification fails, the target is automatically rolled back to the `.pre_restore.bak` snapshot.

### Step 5: Start the Fleet Manager Service & Timers
```bash
sudo systemctl start fleet-manager fleet-manager-backup.timer
```

### Step 6: Verify Post-Restore Health & Readiness
```bash
# 1. Process Liveness
curl -fsS http://127.0.0.1:8000/healthz

# 2. Dependency Readiness
curl -fsS http://127.0.0.1:8000/readyz

# 3. Authenticated Inventory & Operations Probe
OPERATOR_TOKEN=$(grep FLEET_MANAGER_API_TOKEN /etc/fleet-manager/fleet-manager.env | cut -d '=' -f2)
curl -fsS -H "Authorization: Bearer ${OPERATOR_TOKEN}" http://127.0.0.1:8000/api/nodes
# Note: Operations history is scoped per node:
curl -fsS -H "Authorization: Bearer ${OPERATOR_TOKEN}" http://127.0.0.1:8000/api/nodes/1/operations
```

### Step 7: Emergency Rollback (If Post-Restore Probes Fail)
If readiness probes fail or unexpected data loss is observed:
```bash
sudo systemctl stop fleet-manager
sudo -u fleet-manager cp /var/lib/fleet-manager/inventory.db.pre_restore.bak /var/lib/fleet-manager/inventory.db
# Remove sidecars that might belong to the failed restore attempt
sudo -u fleet-manager rm -f /var/lib/fleet-manager/inventory.db-wal /var/lib/fleet-manager/inventory.db-shm
sudo systemctl start fleet-manager
```

### Step 8: Pre-Restore Safety Snapshot Collision Resolution (.pre_restore.bak)

If a prior restore was interrupted or an existing safety snapshot is already present on disk, `backup_restore.py` strictly fails closed with `PreRestoreSnapshotExistsError` before touching the active database or issuing WAL checkpoints. To resolve this collision safely without risk of data loss:

1. **Restore Refusal**: The restore procedure intentionally refuses to proceed or overwrite an existing snapshot when `/var/lib/fleet-manager/inventory.db.pre_restore.bak` already exists.
2. **Stop and Inspect**: Do not immediately retry or force the restore command. Stop and inspect both the current active database (`/var/lib/fleet-manager/inventory.db`) and the pre-existing safety snapshot (`/var/lib/fleet-manager/inventory.db.pre_restore.bak`) to identify their origins and contents.
3. **Preserve Both Files**: Keep both database files intact throughout the investigation. Never configure automated scripts or procedures to silently delete `.pre_restore.bak`.
4. **Record SHA-256 Checksums**: Compute and document cryptographic SHA-256 checksums for both files to establish immutable provenance:
   ```bash
   sha256sum /var/lib/fleet-manager/inventory.db /var/lib/fleet-manager/inventory.db.pre_restore.bak
   ```
5. **Validate Database Integrity and Foreign Keys**: Run SQLite integrity and foreign-key checks on all candidate recovery copies to assess database page consistency and constraint validity:
   ```bash
   sqlite3 /var/lib/fleet-manager/inventory.db "PRAGMA integrity_check; PRAGMA foreign_key_check;"
   sqlite3 /var/lib/fleet-manager/inventory.db.pre_restore.bak "PRAGMA integrity_check; PRAGMA foreign_key_check;"
   ```
6. **Retain an Independent Copy Before Archiving**: Create an independent, timestamped archival copy in a designated backup directory before moving the safety snapshot out of the operational path:
   ```bash
   sudo -u fleet-manager mkdir -p /var/backups/fleet-manager/archived_snapshots
   # Retain independent copy
   sudo -u fleet-manager cp -p /var/lib/fleet-manager/inventory.db.pre_restore.bak \
     /var/backups/fleet-manager/archived_snapshots/inventory.db.pre_restore.$(date +%Y%m%d_%H%M%S).bak
   # Manually archive the existing snapshot away from the operational database directory with timestamp protection
   sudo -u fleet-manager mv -n /var/lib/fleet-manager/inventory.db.pre_restore.bak \
     /var/backups/fleet-manager/archived_snapshots/resolved_collision.$(date +%Y%m%d_%H%M%S).bak
   ```
7. **Retry Restore Only After Explicit Resolution**: Only re-attempt the offline restore operation (Step 4) after the operator has explicitly inspected, validated, and archived the colliding snapshot.

---

## 10. Post-Deployment Smoke Verification

Probe the installed service and telemetry pipelines without installing development packages:

```bash
# 1. Basic endpoints
curl -fsS http://127.0.0.1:8000/healthz >/dev/null
curl -fsS http://127.0.0.1:8000/readyz >/dev/null
curl -fsS http://127.0.0.1:8000/metrics >/dev/null
curl -fsS http://127.0.0.1:8000/dashboard >/dev/null

# 2. Prometheus targets and query verification
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22fleet-manager%22%7D'

# 3. Grafana health check
curl -fsS http://127.0.0.1:3000/api/health
```

---

## 11. Common Systemd & SQLite Failure Diagnostics

| Symptom / Error | Root Cause | Resolution |
|---|---|---|
| **Service exits with Code 1** (`RuntimeError: Configuration error`) | Missing or invalid `FLEET_MANAGER_API_TOKEN` or permission error on `/etc/fleet-manager/fleet-manager.env`. | Inspect `/etc/fleet-manager/fleet-manager.env`. Ensure token is 32-128 chars, ownership is `fleet-manager:fleet-manager`, permissions `0600`. |
| **systemd 203/EXEC Failure** | Python virtualenv binary not found or not executable. | Verify `/opt/fleet-manager/.venv/bin/uvicorn` exists and has execute permissions (`chmod a+rx`). |
| **systemd 226/NAMESPACE Failure** | File path listed in `ReadOnlyPaths` or `ReadWritePaths` does not exist on disk. | Verify `/etc/fleet-manager`, `/var/lib/fleet-manager`, and `/var/backups/fleet-manager` exist with correct directory ownership before starting service. |
| **SQLite `OperationalError: unable to open database file`** | Service account cannot create or lock database file in `/var/lib/fleet-manager`. | Ensure `/var/lib/fleet-manager` is owned by `fleet-manager:fleet-manager` with mode `0700`. |
| **SSH Check `AUTH_FAILED`** | Private key `/etc/fleet-manager/id_ed25519` not accepted by target node. | Verify remote node's `~/.ssh/authorized_keys` contains the public key matching `/etc/fleet-manager/id_ed25519` for user `fleetbootstrap`. |
| **SSH Check `UNKNOWN_HOST` / `KEY_CHANGED`** | Remote host key is not present in `/var/lib/fleet-manager/known_hosts`, or host key has changed. | Verify remote host key fingerprint independently out-of-band and enroll into `/var/lib/fleet-manager/known_hosts`. |
| **Backup timer inactive** | `fleet-manager-backup.timer` not enabled in systemd. | Run `sudo systemctl enable --now fleet-manager-backup.timer` and verify via `systemctl list-timers`. |

---

## 12. Security & Portability Boundaries

1. **Loopback Boundary**: The control plane binds strictly to `127.0.0.1:8000`. Exposing the API to external networks requires an external reverse proxy (e.g. Nginx, Caddy, or Envoy) terminating TLS with client certificates or mutual authentication.
2. **Single Operator Scope**: Authentication uses a high-entropy operator bearer token, not multi-tenant RBAC.
3. **Evidence Limits**:
   - The systemd unit sandboxing definitions and file permissions in this runbook are designed for Debian 12 (systemd v252+).
   - In cross-platform development environments (Windows/macOS), static linting and Python unit test matrices are fully verified, but live kernel namespace isolation (`ProtectSystem`, `PrivateTmp`, `CapabilityBoundingSet`) requires validation on a running Linux host.

---

## 13. GCE One-Shot Deployment Automation (`deploy/gce/`)

The repository includes a reproducible, modular deployment suite under `fleet-manager/deploy/gce/`.

### Directory Structure & Responsibilities

| File | Purpose | Safeguards |
|---|---|---|
| `00-config.env` | Central configuration and IP topology mappings | Contains no embedded credentials or secrets |
| `01-start-vms.sh` | Boots all 4 VMs and polls until RUNNING | Defaults to `--dry-run`; requires `--execute` |
| `02-setup-nodes.sh` | Installs `prometheus-node-exporter` on nodes A, B, C | Leverages existing `default-allow-internal` VPC rule |
| `03-setup-controller.sh` | Installs base packages, `uv`, Python 3.12, Prometheus, Grafana | Installs hermetic Python 3.12 in `/opt/fleet-manager/python` |
| `04-deploy-app.sh` | Deploys verified source bundle, syncs dependencies, enables systemd | Verifies SHA-256 before extraction; generates 32-byte crypto token |
| `05-transfer-keys.sh` | Transfers `~/.ssh/fleet-bootstrap` and inits `known_hosts` | Restricts key to 0600 `fleet-manager:fleet-manager` |
| `06-start-tunnel.sh` | Starts secure IAP SSH port forwarding tunnel | Forwards 8000 & 3000 to local workstation |
| `07-cleanup-vms.sh` | Stops all 4 VMs, confirms TERMINATED, reports disk costs | Preserves persistent disks and firewall rules intact |
| `deploy-all.sh` | Master orchestrator running steps 1 through 6 sequentially | Defaults to `--dry-run`; requires `--execute` and confirm |

### Standalone Source-Bundle Packaging & Integrity Workflow

In environments where GitHub remote access is not configured, or where the current working tree contains uncommitted modifications and untracked core files (such as `onboarding.py`, `trust.py`, `readiness.py`, `ui/static/`, `ui/templates/`), the deployment **must not depend on `git clone` or `git archive`**.

Use the verified standalone packaging utility to create a self-contained release archive from the active working tree:

```bash
# 1. Package verified source bundle from local working tree:
python scripts/package_source_bundle.py --output-dir dist/

# 2. Verify archive integrity and member listing locally:
python scripts/package_source_bundle.py --verify-only dist/fleet-manager-source-bundle.tar.gz
```

---

### Primary Deployment Workflow: Google Cloud Shell

> [!IMPORTANT]
> **Cloud Shell is the Primary & Authoritative Execution Environment.**
> The bootstrap private key (`~/.ssh/fleet-bootstrap`) exists exclusively in Google Cloud Shell. Therefore, Cloud Shell is the primary documented deployment environment. Local workstation deployment is optional and supported only when credentials are explicitly transferred.

#### Step 1: Transfer Bundle to Cloud Shell
From your local workstation terminal:
```bash
# Upload bundle and companion checksum to Cloud Shell home directory:
gcloud cloud-shell scp localhost:dist/fleet-manager-source-bundle.tar.gz cloudshell:~/fleet-manager-source-bundle.tar.gz
gcloud cloud-shell scp localhost:dist/fleet-manager-source-bundle.tar.gz.sha256 cloudshell:~/fleet-manager-source-bundle.tar.gz.sha256
```
*(Alternatively, in the Cloud Shell browser window, click **More (⋮) → Upload** and select `dist/fleet-manager-source-bundle.tar.gz` and `dist/fleet-manager-source-bundle.tar.gz.sha256`).*

#### Step 2: Verify Checksum in Cloud Shell BEFORE Extraction
In Google Cloud Shell:
```bash
# CRITICAL PRE-FLIGHT CHECK: Verify SHA-256 digest before untarring
cd ~ && sha256sum -c fleet-manager-source-bundle.tar.gz.sha256
# Expected output: fleet-manager-source-bundle.tar.gz: OK
```

#### Step 3: Extract and Run One-Shot Deployment in Cloud Shell
```bash
# Extract verified source bundle:
mkdir -p ~/fleet-manager && tar -xzf ~/fleet-manager-source-bundle.tar.gz -C ~/fleet-manager

# Navigate to project and run dry-run validation:
cd ~/fleet-manager
bash deploy/gce/deploy-all.sh --dry-run

# Execute live deployment against GCE:
bash deploy/gce/deploy-all.sh --execute --bundle ~/fleet-manager-source-bundle.tar.gz
```

---

### Optional Secondary Workflow: Direct Local Workstation Deployment
*(Use only if you have explicitly satisfied credential requirements by copying `fleet-bootstrap` from Cloud Shell to `~/.ssh/fleet-bootstrap` on your local workstation):*

```bash
cd fleet-manager
bash deploy/gce/deploy-all.sh --dry-run
bash deploy/gce/deploy-all.sh --execute
```

---

## 14. Automated Acceptance Testing (`scripts/gce_acceptance_test.py`)

A comprehensive verification suite covering 14 distinct system checks divided into non-destructive baseline and opt-in failure-injection tiers.

### Running Acceptance Tests

```bash
# 1. Offline Verification (Mocks cloud and SSH without network or running VMs):
python scripts/gce_acceptance_test.py --mock

# 2. Live Cloud Baseline Acceptance (Non-destructive, safe to run anytime):
OPERATOR_TOKEN=$(gcloud compute ssh fleet-controller --zone=asia-south1-a --tunnel-through-iap -- \
  "sudo grep FLEET_MANAGER_API_TOKEN /etc/fleet-manager/fleet-manager.env | cut -d '=' -f2")
python scripts/gce_acceptance_test.py --host 127.0.0.1 --port 8000 --token "${OPERATOR_TOKEN}"

# 3. Full Acceptance with Opt-In Fault-Injection (Includes failure recovery):
# NOTE: --allow-fault-injection is passed directly as a Python CLI argument (single line):
python scripts/gce_acceptance_test.py --host 127.0.0.1 --port 8000 --token "${OPERATOR_TOKEN}" --allow-fault-injection
```

---

## 15. Manual Acceptance Checklist

| # | Test Area | Command / Action | Expected Output | Reversible Restoration |
|---|---|---|---|---|
| **M1** | VM Status | `gcloud compute instances list --filter="name ~ fleet-"` | All 4 VMs report status `RUNNING` | `07-cleanup-vms.sh` halts VMs |
| **M2** | Node SSH Reachability | `nc -zv 10.160.0.5 22` (from controller) | `Connection to 10.160.0.5 22 port [tcp/ssh] succeeded!` | N/A (Read-only probe) |
| **M3** | API Security Barrier | `curl -i http://127.0.0.1:8000/api/nodes` | `HTTP/1.1 401 Unauthorized` | N/A (Read-only probe) |
| **M4** | Fresh Initial Inventory | `curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/nodes` | `HTTP/1.1 200 OK`, `{"nodes": []}` (empty initial state on clean deployment) | N/A (Read-only probe) |
| **M5** | Node Registration | Register `fleet-node-a` (`10.160.0.5`), `fleet-node-b` (`10.160.0.3`), `fleet-node-c` (`10.160.0.4`) via UI or `POST /api/nodes` | HTTP 201 Created; IDs 1, 2, 3 assigned with state `NOT_CHECKED` | Inventory records persisted |
| **M6** | Host-Key Scan & Fingerprint | Web UI -> Click "Scan & Verify Host Key" on Node A | Presented ED25519 SHA-256 fingerprint displayed with `UNTRUSTED` badge | Confirmation required to enroll |
| **M7** | Host-Key Trust Enrollment | Click "Trust & Enroll Key" in modal | Badge updates to `TRUSTED`; key pinned in `/var/lib/fleet-manager/known_hosts` | Atomic write to disk |
| **M8** | SSH Connectivity Check | `curl -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/nodes/1/connectivity-check` | Outcome `CONNECTED`, derived display status `REACHABLE` | N/A (Read-only probe) |
| **M9** | Controlled Remote Operation: Uptime | Web UI -> Select `system.uptime` -> Run | Exit code 0, standard Linux `uptime` output | N/A (Read-only command) |
| **M10** | Controlled Remote Operation: Memory | Web UI -> Select `system.memory` -> Run | Exit code 0, `/proc/meminfo` kernel memory counters | N/A (Read-only command) |
| **M11** | Controlled Remote Operation: Disk | Web UI -> Select `system.disk` (`path: /`) -> Run | Exit code 0, POSIX `df -h /` disk utilization | N/A (Read-only command) |
| **M12** | Prometheus Scrapes | `curl -s http://127.0.0.1:9090/api/v1/query?query=up` | `up{job="fleet-manager"} == 1` and `up{job="node_exporter"} == 1` for nodes | N/A (Read-only probe) |
| **M13** | Grafana Dashboard | Open `http://127.0.0.1:3000` -> Fleet Management Dashboard | 9 operational panels rendering live Prometheus time-series | N/A (Read-only display) |
| **M14** | Host-Key Mismatch Rejection | Temporarily rotate host key on Node C ([Runbook Sec 7.2](#72-safe-reversible-host-key-mismatch-failure-injection)) | Outcome `HOST_KEY_MISMATCH`, status `CHECK_ERROR` | Restore `.bak` key & restart ssh ([Runbook 7.2](#72-safe-reversible-host-key-mismatch-failure-injection)) |
| **M15** | Unreachable Node Timeout | Register non-routable address (`192.0.2.1`) & probe | Outcome `TIMEOUT`, status `UNREACHABLE` within 12s | Safe failure handling |
| **M16** | Disaster Recovery Backup | Run `backup_restore.py backup` | Creates verified `inventory_latest.db` and SHA-256 manifest | Online safe snapshot |
| **M17** | Disaster Recovery Restore | Run `backup_restore.py restore` | Atomically swaps DB, cleans WAL/SHM, preserves `.pre_restore.bak` | Rollback to `.pre_restore.bak` if needed |

---

## 16. Teardown, Cost Optimization & Resource Accounting

To prevent unnecessary GCP compute spend when the testing session concludes, run the verified teardown script:

```bash
# Dry-run inspection
bash deploy/gce/07-cleanup-vms.sh --dry-run

# Live VM shutdown
bash deploy/gce/07-cleanup-vms.sh --execute
```

### Resource Accounting & Invariants
1. **VM Compute (vCPU / RAM)**: Charges halt immediately upon `TERMINATED` status ($0.00/hour).
2. **Persistent Disks**: Boot and data disks are **preserved** and NOT deleted, guaranteeing state durability.
   - **Controller (`fleet-controller`)**: 20 GB balanced persistent disk (`pd-balanced`).
   - **Managed Node A (`fleet-node-a`)**: 10 GB standard persistent disk (`pd-standard`).
   - **Managed Node B (`fleet-node-b`)**: 10 GB standard persistent disk (`pd-standard`).
   - **Managed Node C (`fleet-node-c`)**: 10 GB standard persistent disk (`pd-standard`).
   - **Total Provisioned Capacity**: 20 GB `pd-balanced` + 30 GB `pd-standard` (50 GB total storage across 4 disks).
   - Storage charges continue to accrue per published regional Google Cloud rates for `asia-south1` (Mumbai) until persistent disks are deleted.
3. **Firewall Rules & IAM**: Preserved intact without recurring charges.
4. **Permanent Decommissioning** (Optional, only if terminating project completely):
   ```bash
   gcloud compute instances delete fleet-controller fleet-node-a fleet-node-b fleet-node-c \
     --project="project-3682976b-7d4a-465a-933" \
     --zone="asia-south1-a" \
     --delete-disks=all
   ```
