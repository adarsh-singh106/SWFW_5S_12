# Debian 12 & Ubuntu 26.04 Linux Deployment Runbook

This runbook defines the authoritative operational procedure to deploy, harden, monitor, back up, and restore the Distributed Linux Fleet Manager control plane reproducibly on clean Debian 12 (Bookworm) and Ubuntu 26.04 LTS systems, with proposed procedures for Google Cloud Platform (GCE) multi-node topology. Live acceptance evidence is pending; commands below are instructions, not an execution record.

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
- **Port Forwarding via IAP SSH (Recommended; Live Verification Pending)**:
  Because the existing GCP firewall allows IAP on SSH port 22, forward loopback ports directly through the authenticated IAP SSH channel without requiring any additional firewall rules:

```bash
# Launch encrypted port forwarding tunnel to controller (run from local workstation):
gcloud compute ssh fleet-controller \
  --project="project-3682976b-7d4a-465a-933" \
  --zone="asia-south1-a" \
  --tunnel-through-iap \
  -- -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8000:127.0.0.1:8000 -L 127.0.0.1:3000:127.0.0.1:3000 -L 127.0.0.1:9090:127.0.0.1:9090
```

Once the tunnel is active, access local forwarded endpoints in your browser:
- **Fleet Manager Dashboard**: `http://127.0.0.1:8000/dashboard`
- **Fleet Manager Metrics**: `http://127.0.0.1:8000/metrics`
- **Grafana Operational Dashboard**: `http://127.0.0.1:3000`
- **Prometheus Query UI**: `http://127.0.0.1:9090`

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

### 7.2 Failure testing boundary

Live fault scenarios 08-13 are **NOT IMPLEMENTED** by the acceptance runner. The flag
`--allow-fault-injection` does not execute them. Do not rotate production SSH host keys
for this check. Requirement 3's separately authorized disposable-node outage/recovery
procedure is in section 15. Additional credential, key-mismatch, timeout and controller
crash scenarios remain live gates; local unit tests do not close them.

---

## 7.3 Operational Commands

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
- Each run copies pages into a temporary file, verifies `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and a supported `user_version` (3, 4 or 5), and atomically replaces `inventory_latest.db`.
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
2. **Pre-flight & Post-flight Checks**: The backup file is verified for valid SQLite B-tree pages, foreign keys, and a supported schema user_version (currently 3, 4 or 5).
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
OPERATOR_TOKEN=$(sudo sed -n 's/^FLEET_MANAGER_API_TOKEN=//p' /etc/fleet-manager/fleet-manager.env)
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
| `06-start-tunnel.sh` | Starts secure IAP SSH port forwarding tunnel | Forwards 8000, 3000 & 9090 to local loopback; fails on bind conflicts |
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

Run from the checked-out `fleet-manager/` directory in **Cloud Shell or a workstation**
with Python 3.12 and `uv sync --locked` (the runner needs the dev dependencies httpx
and TestClient). Do not install these into the production service virtualenv.
The tunnel must run in the **same machine/network namespace** as the runner.
Cloud Shell's localhost is not the workstation's localhost. Use the controller shell
for private-IP diagnostics; the runner uses the controller API to execute SSH checks.

```bash
# Offline only: executes authentication and temporary SQLite backup/restore.
uv run --no-sync python scripts/gce_acceptance_test.py --mock
# Expected exit 2: 2 local passes, 12 skips; no GCE acceptance established.

# FUTURE authorized live session: terminal 1, same host as acceptance runner:
bash deploy/gce/06-start-tunnel.sh --execute
# Keep this terminal open; forwards 8000, 3000, 9090 to controller loopback.

# Terminal 2: enter the configured operator token and Grafana credentials privately.
read -rsp 'Fleet Manager token: ' FLEET_MANAGER_API_TOKEN; printf '\n'
export FLEET_MANAGER_API_TOKEN
read -rp 'Grafana user: ' GRAFANA_USER
read -rsp 'Grafana password: ' GRAFANA_PASSWORD; printf '\n'
export GRAFANA_USER GRAFANA_PASSWORD
uv run --no-sync python scripts/gce_acceptance_test.py --host 127.0.0.1 --port 8000 --grafana-port 3000 --prometheus-port 9090
unset FLEET_MANAGER_API_TOKEN GRAFANA_USER GRAFANA_PASSWORD
```

Retrieve the token privately through the authorized controller console from
`/etc/fleet-manager/fleet-manager.env`; do not paste it into logs or command arguments.
The actual config key is `FLEET_MANAGER_API_TOKEN`; the runner uses `--host` and `--port`.
`--token` remains a compatibility option but puts a secret in the process arguments.
Do not use Python `-O`/`PYTHONOPTIMIZE`: the runner requires assertions and rejects it.

Manually onboard all three expected endpoints before running the baseline. Registration
and trust are never automatic. Baseline checks add connectivity observations and nine
read-only command audit records (three actions on each node). Admission errors 409/429,
FAILURE, UNCERTAIN, bad output and absent audit evidence fail; commands are not retried.
The HTTP timeout is 75 seconds, above the application's allowed 60-second operation budget.

Exit **1** means a failed check, **2** means incomplete/manual gates, **0** means all
checks executed and passed. The current suite always has manual/unimplemented gates,
so even a healthy live baseline returns 2. Never relabel 2 as full acceptance success.
Tests 08-13 remain SKIPPED with NOT IMPLEMENTED details even if the compatibility fault
flag is supplied. Test 14 uses a temporary empty local database, not the deployed DB.

## 15. Exact Manual Acceptance Procedures for the Four Official Requirements

**Not executed during this correction.** These procedures require a future authorized
live session. Record UTC time, revision, endpoint/VM identity, expected and observed
results, command exit status and restoration status. Redact secrets and scan confirmation
tokens. A missing step is PENDING/SKIPPED, never PASS. All Bash commands below use the
same Cloud Shell/workstation terminal with the active three-port tunnel, unless marked
controller or node. `jq`, curl and gcloud are prerequisites on that operator host.

### Shared setup and independent identity verification

```bash
set -o pipefail                    # preserve failures in curl/jq pipelines
cd ~/fleet-manager                 # extracted/checked-out project on operator host
export GCP_PROJECT=project-3682976b-7d4a-465a-933
export GCP_ZONE=asia-south1-a
API=http://127.0.0.1:8000
read -rsp 'Fleet Manager token: ' FLEET_MANAGER_API_TOKEN; printf '\n'
export FLEET_MANAGER_API_TOKEN
fm() { curl --fail-with-body --silent --show-error --max-time 75 -H "Authorization: Bearer ${FLEET_MANAGER_API_TOKEN}" "$@"; }
curl -s -o /dev/null -w '%{http_code}\n' "$API/api/nodes"  # expect 401
fm "$API/api/nodes" | jq .                               # expect 200 and nodes array
```

### Requirement 1: Node onboarding and management

For each `(name, address)` pair: `fleet-node-a 10.160.0.5`, `fleet-node-b 10.160.0.3`,
`fleet-node-c 10.160.0.4`, run the following, setting NAME and ADDRESS to that pair.
Reuse matching existing records; never assume IDs 1, 2, 3 and do not create duplicates.

```bash
NAME=fleet-node-a; ADDRESS=10.160.0.5
fm "$API/api/nodes" | jq --arg address "$ADDRESS" '.nodes[] | select(.address == $address)'
# Only if absent:
fm -X POST -H 'Content-Type: application/json' "$API/api/nodes"   -d "$(jq -nc --arg name "$NAME" --arg address "$ADDRESS" '{name:$name,address:$address,ssh_port:22}')"
NID=$(fm "$API/api/nodes" | jq -er --arg address "$ADDRESS" '.nodes[] | select(.address == $address and .ssh_port == 22) | .id')
fm "$API/api/nodes/$NID/onboarding" | jq .
```

New inventory should be NOT_CHECKED/PENDING_SETUP before a successful probe. The
onboarding API exposes the operator **public** key and bootstrap instruction. If login
is not configured, use an independently authenticated node console to install that
public key for `fleetbootstrap`; retain the private key only on the controller.

Before scanning/enrolling, independently identify the VM/project through authenticated
GCE console or an existing independently trusted IAP SSH session. Do not accept a new
SSH prompt merely to obtain a fingerprint from the same unverified endpoint.

```bash
# Operator terminal -> independently authenticated node (repeat for A/B/C):
gcloud compute ssh "$NAME" --project="$GCP_PROJECT" --zone="$GCP_ZONE" --tunnel-through-iap   --command='sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256'
# If scan returns another key_type, inspect that corresponding public host key instead.
SCAN=$(fm -X POST "$API/api/nodes/$NID/scan-host-key")
printf '%s' "$SCAN" | jq '{node_id,address,ssh_port,key_type,fingerprint,trust_state}'
```

**STOP AND COMPARE** the SHA256 fingerprint, key type, VM identity, IP and port against
the independently obtained value. Record who verified, when and via which trusted
channel. On mismatch, do not enroll or proceed. Only after an exact match:

```bash
fm -X POST -H 'Content-Type: application/json' "$API/api/nodes/$NID/trust-host-key"   -d "$(printf '%s' "$SCAN" | jq '{fingerprint,confirmation}')"
unset SCAN
fm -X POST "$API/api/nodes/$NID/connectivity-check" | jq .   # outcome CONNECTED
fm "$API/api/nodes/$NID/onboarding" | jq .                  # TRUSTED, READY, is_ready true
fm "$API/api/nodes/status" | jq .                          # corresponding node REACHABLE
```

Repeat for all three nodes. Open `/dashboard`, authenticate, reload, and verify all
three names/addresses/ports and current states persist. Requirement 1 needs this manual
record; automated test 03 deliberately stays a manual gate even after enrollment.

### Requirement 2: Collect, store and visualize metrics

```bash
curl -fsSG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=up' | jq .
curl -fsS http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[] | {labels,health,lastError,lastScrape}'
# Collect a stored time window after at least 2 minutes of successful scraping:
END=$(date +%s); START=$((END-120))
curl -fsSG http://127.0.0.1:9090/api/v1/query_range   --data-urlencode 'query=node_memory_MemTotal_bytes{job="node_exporter"}'   --data-urlencode "start=$START" --data-urlencode "end=$END" --data-urlencode 'step=5' | jq .
read -rp 'Grafana user: ' GRAFANA_USER
read -rsp 'Grafana password: ' GRAFANA_PASSWORD; printf '\n'
export GRAFANA_USER GRAFANA_PASSWORD
uv run --no-sync python scripts/gce_acceptance_test.py --host 127.0.0.1 --port 8000 --grafana-port 3000 --prometheus-port 9090
```

Require `up=1` for `fleet-manager/127.0.0.1:8000` and all three node_exporter instances
`10.160.0.5:9100`, `10.160.0.3:9100`, `10.160.0.4:9100`; targets must be healthy with
no lastError and recent lastScrape. The range query must show multiple timestamped,
positive memory samples for each node. A single HTTP 200 or empty result fails.
The runner verifies datasource UID `prometheus`, type, proxy access, server URL
`http://127.0.0.1:9090`, real `up` queries through Grafana, and provisioned dashboard
UID `fleet-manager-overview` with expected panel queries.

Open `http://127.0.0.1:3000/d/fleet-manager-overview`, choose Last 5 minutes and refresh.
Require real CPU/memory/disk/network data for A/B/C and control-plane panels without
query errors. Save timestamped screenshots only during the authorized evidence session.
API provisioning success alone does not prove rendered panels or historical storage.

### Requirement 3: Availability, failure handling and recovery (separate live gate)

Baseline: execute CONNECTED probes for all three nodes, then inspect `/api/nodes/status`
and ensure observations are recent within `observation_ttl_seconds`. A failed SSH login
is CHECK_ERROR, not evidence that the host itself is down.

The following **future maintenance-window procedure is disruptive and needs separate
explicit authorization**. Run only on disposable node C, with confirmed IAP console
access, no unrelated workloads, and a second operator able to restore it. Record its
original RUNNING state first. It is not part of this correction's executed scope.

```bash
# Operator host, with shared setup/token still loaded:
gcloud compute instances describe fleet-node-c --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='value(status)'
# Must be RUNNING before continuing. Resolve exact inventory ID, never assume 3:
CID=$(fm "$API/api/nodes" | jq -er '.nodes[] | select(.address == "10.160.0.4" and .ssh_port == 22) | .id')
# Install restoration trap BEFORE the authorized stop; keep an independent recovery session open.
restore_c() { gcloud compute instances start fleet-node-c --project="$GCP_PROJECT" --zone="$GCP_ZONE"; }
trap restore_c EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
gcloud compute instances stop fleet-node-c --project="$GCP_PROJECT" --zone="$GCP_ZONE"
time fm -X POST "$API/api/nodes/$CID/connectivity-check" | jq .
fm "$API/api/nodes/status" | jq .
# Re-run CONNECTED probes for A and B using their resolved IDs as in requirement 1.
# Inspect API/dashboard responsiveness and fresh peer observations during C's outage.
restore_c
# Leave the EXIT trap installed until restoration and recovery are verified.
gcloud compute instances describe fleet-node-c --project="$GCP_PROJECT" --zone="$GCP_ZONE" --format='value(status)'
# Poll status every 5s for at most 180s, WITHOUT manual probe, to observe scheduler recovery:
for i in $(seq 1 36); do
  STATUS=$(fm "$API/api/nodes/status") || break
  printf '%s' "$STATUS" | jq --argjson id "$CID" '.nodes[] | select(.node.id == $id)'
  printf '%s' "$STATUS" | jq -e --argjson id "$CID" '.nodes[] | select(.node.id == $id) | .display_status == "REACHABLE" and .observation.outcome == "CONNECTED"' >/dev/null && break
  sleep 5
done
# Remove trap ONLY after VM is RUNNING, SSH independently works, and fresh CONNECTED is observed:
# trap - EXIT INT TERM
```

Expected: the controller remains responsive; C's probe completes within configured
`FLEET_MANAGER_SSH_TOTAL_TIMEOUT_SECONDS` plus transport overhead, A/B remain fresh and
REACHABLE, and C recovers automatically after restoration. `CONNECTION_TIMEOUT` or
`CONNECTION_REFUSED` maps to UNREACHABLE; generic `TIMEOUT` maps to CHECK_ERROR under
the current contract. `EXECUTION_TIMEOUT` also maps to CHECK_ERROR because the parent
deadline does not identify the remote phase. Record the actual category; do not assume
any SSH timeout proves complete host or application failure. The phase-aware transport
makes future TCP establishment timeouts explicit; an older generic `TIMEOUT` observation
cannot be reclassified retrospectively.
Scheduler polling must produce a **new** observation timestamp after restoration.
A trap is best effort, not protection against operator-host loss; the independent
recovery operator must start C if the shell is lost. If any restoration check fails,
retain the gate as FAILED and restore C through the independent console.

08/09/10/13 (invalid credential, host-key mismatch, bounded specific timeout, controller
crash reconciliation) have no validated live automation/restoration procedure here.
Keep them NOT IMPLEMENTED until a separately reviewed isolated scenario exists.
This outage procedure can supply manual 11/12 evidence, but does not validate all failure categories.

### Requirement 4: Controlled remote execution and audit

For **each node**, resolve NID as in requirement 1 and execute:

```bash
for PAYLOAD in '{"action":"system.uptime","arguments":{}}'                '{"action":"system.memory","arguments":{}}'                '{"action":"system.disk","arguments":{"path":"/"}}'; do
  RESULT=$(fm -X POST -H 'Content-Type: application/json' "$API/api/nodes/$NID/operations" -d "$PAYLOAD") || break
  printf '%s' "$RESULT" | jq .
  OID=$(printf '%s' "$RESULT" | jq -er '.id') || break
  fm "$API/api/nodes/$NID/operations/$OID" | jq .
  fm "$API/api/nodes/$NID/operations?include_output=true" | jq --arg id "$OID" '.operations[] | select(.id == $id)'
done
# Catalog rejection, no remote command should execute (expect HTTP 422):
fm -X POST -H 'Content-Type: application/json' "$API/api/nodes/$NID/operations"   -d '{"action":"shell.exec","arguments":{"command":"id"}}'
```

Require SUCCESS, exit_code 0, no failure_category or truncation, populated timestamps,
correct node/action/arguments and audit operator metadata. Inspect actual stdout:
`uptime` includes uptime and load averages; `system.memory` is **free -m** with numeric
Mem/Swap rows; disk is **df -h -P -- /** with root mount and percentage usage. Compare
against those same read-only commands run via independently authenticated node access;
dynamic uptime/memory counters may change between observations. Audit GET and history
must contain the exact operation ID and persisted output/outcome. FAILURE, UNCERTAIN,
409, 429, empty/wrong output or missing history is not a pass. Do not retry uncertain jobs.

At session end unset credentials, close the tunnel and record remaining gates:

```bash
unset FLEET_MANAGER_API_TOKEN GRAFANA_USER GRAFANA_PASSWORD RESULT STATUS
```

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
