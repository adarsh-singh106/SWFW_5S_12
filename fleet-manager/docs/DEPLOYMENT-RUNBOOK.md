# Debian 12 Linux Deployment Runbook

This runbook defines the authoritative operational procedure to deploy, harden, monitor, back up, and restore the Distributed Linux Fleet Manager control plane reproducibly on clean Debian 12 (Bookworm) systems.

---

## 1. System Requirements & Prerequisites

- **Operating System**: Debian 12 (Bookworm) x86_64 / aarch64.
- **Python**: CPython 3.12 managed via `uv` (isolated, reproducible toolchain).
- **Required System Packages**:
  ```bash
  sudo apt-get update && sudo apt-get install -y \
    curl \
    git \
    sqlite3 \
    openssh-client \
    prometheus \
    prometheus-node-exporter \
    grafana-server
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
sudo mkdir -p /var/lib/fleet-manager      # SQLite database & WAL/SHM state (0700, fleet-manager)
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
```

### 4.2 Safe SSH Host-Key Enrollment & Key Generation
Generate the operator Ed25519 private key and initialize trusted `known_hosts`:

```bash
# Generate dedicated operator SSH key pair without passphrase
sudo -u fleet-manager ssh-keygen -t ed25519 -N "" -f /etc/fleet-manager/id_ed25519
sudo chmod 600 /etc/fleet-manager/id_ed25519
sudo chmod 644 /etc/fleet-manager/id_ed25519.pub

# Initialize known_hosts file
sudo -u fleet-manager touch /etc/fleet-manager/known_hosts
sudo chmod 644 /etc/fleet-manager/known_hosts

# STRICT SECURITY REQUIREMENT: Host Key Verification
# Never disable host-key checking (StrictHostKeyChecking=no is strictly forbidden).
# When enrolling a new managed node, independently verify the key fingerprint out-of-band:
# Example:
#   ssh-keyscan -t ed25519 -p 22 192.168.1.50 | sudo tee -a /etc/fleet-manager/known_hosts
#   ssh-keygen -lf /etc/fleet-manager/known_hosts
# Compare fingerprint against the remote node's local `/etc/ssh/ssh_host_ed25519_key.pub`.
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

## 6. Prometheus & Grafana Provisioning

Configure Prometheus to scrape the `/metrics` endpoint and Grafana for dashboard visualization:

```bash
# 1. Deploy Prometheus scrape configuration
sudo cp /opt/fleet-manager/monitoring/prometheus/prometheus.yml /etc/prometheus/prometheus.yml
sudo cp /opt/fleet-manager/monitoring/prometheus/targets.json /etc/prometheus/targets.json
sudo chown -R prometheus:prometheus /etc/prometheus
sudo systemctl restart prometheus prometheus-node-exporter

# 2. Deploy Grafana datasource and dashboard provisioning
sudo mkdir -p /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards /etc/grafana/dashboards
sudo cp /opt/fleet-manager/monitoring/grafana/provisioning/datasources/prometheus.yaml /etc/grafana/provisioning/datasources/
sudo cp /opt/fleet-manager/monitoring/grafana/provisioning/dashboards/dashboards.yaml /etc/grafana/provisioning/dashboards/
sudo cp /opt/fleet-manager/monitoring/grafana/dashboards/fleet-monitoring.json /etc/grafana/dashboards/
sudo chown -R grafana:grafana /etc/grafana/provisioning /etc/grafana/dashboards
sudo systemctl restart grafana-server
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

### Step 1: Stop the Fleet Manager Service
```bash
sudo systemctl stop fleet-manager
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

### Step 5: Start the Fleet Manager Service
```bash
sudo systemctl start fleet-manager
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
curl -fsS -H "Authorization: Bearer ${OPERATOR_TOKEN}" http://127.0.0.1:8000/api/operations
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
   # Manually archive the existing snapshot away from the operational database directory
   sudo -u fleet-manager mv /var/lib/fleet-manager/inventory.db.pre_restore.bak \
     /var/backups/fleet-manager/archived_snapshots/resolved_collision.bak
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
| **SSH Check `AUTH_FAILED`** | Private key `/etc/fleet-manager/id_ed25519` not accepted by target node. | Verify remote node's `~/.ssh/authorized_keys` contains the exact public key from `/etc/fleet-manager/id_ed25519.pub`. |
| **SSH Check `UNKNOWN_HOST` / `KEY_CHANGED`** | Remote host key is not present in `/etc/fleet-manager/known_hosts`, or host key has changed. | Verify remote host key fingerprint independently out-of-band and enroll into `/etc/fleet-manager/known_hosts`. |
| **Backup timer inactive** | `fleet-manager-backup.timer` not enabled in systemd. | Run `sudo systemctl enable --now fleet-manager-backup.timer` and verify via `systemctl list-timers`. |

---

## 12. Security & Portability Boundaries

1. **Loopback Boundary**: The control plane binds strictly to `127.0.0.1:8000`. Exposing the API to external networks requires an external reverse proxy (e.g. Nginx, Caddy, or Envoy) terminating TLS with client certificates or mutual authentication.
2. **Single Operator Scope**: Authentication uses a high-entropy operator bearer token, not multi-tenant RBAC.
3. **Evidence Limits**:
   - The systemd unit sandboxing definitions and file permissions in this runbook are designed for Debian 12 (systemd v252+).
   - In cross-platform development environments (Windows/macOS), static linting and Python unit test matrices are fully verified, but live kernel namespace isolation (`ProtectSystem`, `PrivateTmp`, `CapabilityBoundingSet`) requires validation on a running Linux host.
