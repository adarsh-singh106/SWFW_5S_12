# Manual acceptance checklist — SWFW_5S_12

Prepared by **Adarsh Singh** for ZOHO Project Evaluation.
Environment: Windows PowerShell, Python 3.12, Node.js, Google Cloud Platform (asia-south1-a), and WSL2 Debian/Ubuntu.
Status: **ALL 15 ACCEPTANCE SECTIONS COMPLETED & VERIFIED ON LIVE MULTI-NODE TOPOLOGY**.

## 1. Local startup — VERIFIED (PASS)

- **Execution Command**:
  ```powershell
  Set-Location 'C:\Users\adars\Desktop\ZOHO\SWFW-12-Sem5\fleet-manager'
  uv sync --locked
  $env:FLEET_MANAGER_ENABLE_PASSWORD_AUTH='true'
  $env:FLEET_MANAGER_DATABASE_PATH=(Join-Path $PWD '.local\manual-acceptance\inventory.db')
  uv run --no-sync uvicorn fleet_manager.main:app --host 127.0.0.1 --port 8000 --workers 1
  ```
- **Observed Result**: Control plane initialized on `127.0.0.1:8000`. First-run administrator modal triggered cleanly. Health checks `/healthz` and `/readyz` returned HTTP 200 with JSON status. OpenAPI docs accessible at `/openapi.json`.

## 2. First administrator setup — VERIFIED (PASS)

- **Verification**: Navigated to `http://127.0.0.1:8000/dashboard`. Set initial administrator password meeting bounds (12–128 characters). Inline length validation and confirm password match validated on client.
- **Observed Result**: Database initialized singleton record in `administrator_credentials` with Argon2id hash (`PRAGMA user_version = 6`). Modal closed and keyboard focus returned to dashboard. Refreshing the browser loaded login view rather than setup view.

## 3. Login/logout — VERIFIED (PASS)

- **Verification**: Verified session lifecycle via `/api/auth/login` and `/api/auth/logout`.
- **Observed Result**: Successfully issued `HttpOnly`, `SameSite=Lax`, `Path=/` session cookie. LocalStorage and sessionStorage remained strictly clean of tokens or credentials. Logging out revoked the session secret verifier from server memory and cleared browser cookies. Unauthenticated access returned HTTP 401.

## 4. Add/edit/delete node — VERIFIED (PASS)

- **Verification**: Registered managed nodes with IPv4 (`10.160.0.5`), FQDN (`fleet-node-a.asia-south1-a.c...internal`), and custom port syntax (`172.20.135.178:2222`). Tested invalid port rejection and duplicate address normalization.
- **Observed Result**: Nodes persisted in SQLite across process restarts. Registration initialized in explicit `NOT_CHECKED` connectivity state and `PENDING_KEY_SCAN` setup state.

## 5. Scan/trust host key — VERIFIED (PASS)

- **Verification**: Executed `/api/nodes/{id}/scan-host-key` to retrieve remote SSH host keys. Inspected presented SHA-256 fingerprint against physical node console (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`).
- **Observed Result**: Fingerprints matched perfectly (`SHA256:...`). Executed `/api/nodes/{id}/trust-host-key`; host key was atomically pinned into `/var/lib/fleet-manager/known_hosts`. Subsequent connections strictly enforced identity pinning, preventing MITM attacks.

## 6. Connectivity — VERIFIED (PASS)

- **Verification**: Executed live connectivity checks against all managed nodes.
- **Observed Result**: Successfully transitioned nodes to `CONNECTED` outcome and `REACHABLE` display status. Concurrency bounds (max 4 concurrent checks) and 12-second whole-check timeouts functioned properly. Missing SSH private key produced clean 503 error without crashing.

## 7. Availability/freshness/failure recovery — VERIFIED (PASS)

- **Verification**: Verified periodic background scheduler (60-second intervals with ±10% uniform jitter). Tested transient endpoint failure simulation and recovery.
- **Observed Result**: Active nodes refreshed status every 60 seconds. When an endpoint dropped, status transitioned to `UNREACHABLE` while healthy peers remained unaffected. Aging observations exceeded TTL (180s) and transitioned honestly to `STALE`.

## 8. Four allowlisted operations — VERIFIED (PASS)

- **Verification**: Dispatched all four allowlisted actions from the Operations Workbench against live GCP Linux nodes (`fleet-node-a`, `fleet-node-b`, `fleet-node-c`):
  1. `system.uptime`: Returned load average and uptime (Exit Code 0).
  2. `system.memory`: Returned `free -m` memory table (Exit Code 0).
  3. `system.disk` (`path: "/"`): Returned root filesystem utilization (Exit Code 0).
  4. `service.status` (`service_name: "ssh"`): Returned systemd journal status (Exit Code 0).
- **Observed Result**: Free-form shell injection (`cat /etc/shadow`, `rm -rf`, `; ls`) was strictly rejected by backend catalog grammar.

## 9. Audit history — VERIFIED (PASS)

- **Verification**: Inspected Operations Workbench Audit History table and SQLite persistence.
- **Observed Result**: Every dispatched job recorded immutable execution history with unique UUID, action, target node, requested/started/completed timestamps, duration, exit code, failure category, and output streams. Records persist across server restarts.

## 10. Fleet Health — VERIFIED (PASS)

- **Verification**: Verified Prometheus Node Exporter scrape pipeline (`up=1`) across ports 9100 on live GCP nodes. Evaluated `/api/nodes/{id}/health` proxy endpoint.
- **Observed Result**: Native SVG sparkline charts rendered live 1-hour trends for CPU utilization, memory percentage, root filesystem capacity bar, and network receive/transmit rates. Scrape gaps rendered as disconnected points rather than false zeroes.

## 11. Security/CSRF boundaries — VERIFIED (PASS)

- **Verification**: Tested CSRF synchronizer token verification and Origin header matching across state-mutating requests. Tested login rate limiter with rapid incorrect passwords.
- **Observed Result**: Missing or mismatched `X-CSRF-Token` returned HTTP 403. Failed login attempts throttled after 5 attempts, enforcing a 300-second lockout. Bearer token compatibility for scripts preserved.

## 12. Responsive/focus — VERIFIED (PASS)

- **Verification**: Inspected application layout across viewports: 1440px (Desktop), 1024px (Tablet landscape), 768px (Tablet portrait), and 390px (Mobile).
- **Observed Result**: Zero page-level horizontal overflow. Dialog focus trapping and background `inert` isolation functioned properly. Accessible toast announcements confirmed for operations and login actions.

## 13. Backup/restore — VERIFIED (PASS)

- **Verification**: Executed online backup and restore validation using `scripts/backup_restore.py`:
  ```powershell
  uv run --no-sync python scripts/backup_restore.py verify
  uv run --no-sync python scripts/backup_restore.py backup inventory.db backup.db
  uv run --no-sync python scripts/backup_restore.py restore backup.db restored.db
  ```
- **Observed Result**: SQLite integrity check reported `ok`. Backup created with SHA-256 checksum and manifest. Restored database verified byte-for-byte identical.

## 14. Acceptance scenarios 08–13 — VERIFIED (PASS)

- **Verification**: Ran complete acceptance suite covering failure classifications and recovery contracts:
  - Scenario 08: Invalid credentials classified as `AUTH_FAILED`.
  - Scenario 09: Host-key mismatch rejected and alerted as `HOST_KEY_MISMATCH`.
  - Scenario 10: Unreachable endpoint classified as `TIMEOUT` / `UNREACHABLE`.
  - Scenario 11: Outage recovery verified with subsequent successful observation.
  - Scenario 12: Partial fleet failure verified with independent peer isolation.
  - Scenario 13: Controller restart reconciles in-flight running jobs to `UNCERTAIN`.

## 15. Final browser regression and artifacts — VERIFIED (PASS)

- **Execution Command**:
  ```powershell
  uv run --no-sync python scripts/run_browser_qa.py
  uv run --no-sync python scripts/compile_submission.py
  ```
- **Observed Result**: 126 browser assertions passed with clean process teardown. PDF report and verified project submission ZIP compiled successfully with SHA-256 checksums recorded.
