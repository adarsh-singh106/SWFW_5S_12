# Manual acceptance checklist — SWFW_5S_12

Prepared 9 November 2026 by Cline on Windows PowerShell. **Every developer manual test below is PENDING.** Automated QA is not evidence that the developer completed these actions. Never execute disruptive cloud tests during this handoff.

## 1. Local startup — PENDING

Exact first command (PowerShell):

```powershell
Set-Location 'C:\Users\adars\Desktop\ZOHO\SWFW-12-Sem5\fleet-manager'
uv sync --locked
$env:FLEET_MANAGER_ENABLE_PASSWORD_AUTH='true'
$env:FLEET_MANAGER_DATABASE_PATH=(Join-Path $PWD '.local\manual-acceptance\inventory.db')
Remove-Item Env:FLEET_MANAGER_INITIAL_PASSWORD -ErrorAction SilentlyContinue
uv run --no-sync uvicorn fleet_manager.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open **http://127.0.0.1:8000/dashboard**. Expected: first-run administrator setup for a NEW database; an existing database shows login instead. Never delete an existing database just to repeat setup. Save screenshots locally outside tracked source. Health endpoints: `/healthz`, `/readyz`; API specification: `/openapi.json`. Source configuration ports are API 8000, Prometheus 9090, Grafana 3000 and Node Exporter 9100; these are not proof that cloud services currently listen.

## 2. First administrator setup — PENDING

Set a new unique strong password through the setup screen; verify confirmation/validation and dashboard entry. Do not put the password into screenshots, shell history or reports. Reload and confirm setup is no longer available. A separately initialized local/demo `CHANGEME` database must force password replacement before inventory access. Never use that credential in production.

## 3. Login/logout — PENDING

Sign out; verify protected data is inaccessible and sign in again. Inspect browser storage: session cookie must be HttpOnly, SameSite protected, Secure on HTTPS; no password/session secret in localStorage. Idle timeout is 30 minutes; absolute timeout is 12 hours. Server restart invalidates in-memory sessions. Capture login screen and signed-out protected API response, sanitized.

## 4. Add/edit/delete node — PENDING

Use Inventory to register a dedicated non-production Linux host with address and SSH port. Confirm persistence after application restart. Test IPv4, IPv6, FQDN and hostname syntax; syntax validity must not imply DNS resolution. Reject invalid ports, whitespace/command text and normalized duplicate address/port with clear validation/conflict. Delete only a disposable test record. Expected initial state: NOT_CHECKED.

## 5. Scan/trust host key — PENDING

For the isolated Linux test host configure the application environment BEFORE restarting the local process:

```powershell
$env:FLEET_MANAGER_SSH_USERNAME='your-existing-non-root-test-account'
$env:FLEET_MANAGER_SSH_PRIVATE_KEY='C:\path\to\existing\private-key'
$env:FLEET_MANAGER_SSH_KNOWN_HOSTS='C:\path\to\reviewed\known_hosts'
```

These are user-supplied existing paths, not files supplied in the ZIP. Scan the presented key. Independently compare its SHA-256 fingerprint with the host console (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` for the presented algorithm). Explicitly trust only the matching key. Verify persisted known_hosts entry. Changed/unknown keys must never silently enroll; test mismatch only using a disposable local server, never by changing cloud SSH keys. Capture fingerprint/trust UI with no private key material.

## 6. Connectivity — PENDING

Run a connectivity check against that host. Expected: a timestamped CONNECTED observation after strict host-key verification and user authentication, not a claim that every host service is healthy. Missing SSH configuration returns 503. Concurrent same-node checks return 409; full pool 429. Confirm errors do not display a previous success as a new healthy result.

## 7. Availability/freshness/failure recovery — PENDING

In an independently isolated LOCAL Linux test environment only: capture reachable baseline, make its test SSH endpoint unavailable, wait for observation, confirm UNREACHABLE or CHECK_ERROR according to cause, and confirm unrelated peers continue. Restore that local endpoint and wait for a new reachable observation. Pause only the local observation source to exceed TTL and inspect STALE separately from connectivity. NOT_CHECKED must remain distinct. No cloud VM stops/restarts, firewall changes or exporter disruption are authorized by this checklist.

## 8. Four allowlisted operations — PENDING

From Workbench run `system.uptime`, `system.memory`, `system.disk` with path `/`, and `service.status` with a known local test service name. Expected bounded output and explicit terminal outcome/exit code. Inactive service may legitimately return nonzero; do not call it success without interpreting the result. Confirm arbitrary action, metacharacter injection, invalid path/service and extra arguments are rejected. A timeout/unknown outcome must not trigger automatic replay. Verify 409/429/503 handling with the deterministic harness rather than flooding production.

## 9. Audit history — PENDING

Inspect each admitted operation: target, action/arguments, ID, requested/started/completed timestamps, duration, outcome, exit code, error category and truncation. Reload; records persist. Output is text, not executable markup. Never screenshot sensitive command output.

## 10. Fleet Health — PENDING

Configure `FLEET_MANAGER_PROMETHEUS_URL` only to the existing trusted Prometheus service (inspect `src/fleet_manager/metrics/health.py` for setting/default), then restart LOCAL application if needed. Check `/api/nodes/{id}/health` while authenticated. Inspect CPU/memory percent, filesystem capacity, network B/s and tooltips with source times. Missing/stale/collecting samples must show gaps, not zero/interpolated curves. CPU/network are five-minute rates. Browser QA screenshots are MOCKED, not live monitoring proof. Live Grafana/Prometheus acceptance remains pending unless separately verified with approved IAP and trusted SSH.

## 11. Security/CSRF boundaries — PENDING

Using browser developer tools and a disposable database, confirm unauthenticated access fails, wrong password returns a safe error, repeated attempts are throttled, and a state-changing request without the CSRF header or with a foreign Origin/Referer is rejected. Bearer scripts remain compatible only when a separately generated valid token is configured. Do not expose the token in evidence. Review automated security regression tests before crafting requests; never brute-force a real account.

## 12. Responsive/focus — PENDING

At 1440, 1024, 768 and 390px widths navigate dashboard, inventory, onboarding, workbench, audit and Fleet Health. Confirm keyboard navigation, visible focus, modal focus containment/restoration, readable errors and no page-level horizontal overflow. Save sanitized desktop/mobile screenshots. Preserve Graphite + Warm Neutral + Muted Sage styling.

## 13. Backup/restore — PENDING

Run the isolated self-test first:

```powershell
uv run --no-sync python scripts/backup_restore.py verify
```

For user data, use `backup SOURCE DESTINATION`, stop only your LOCAL app, then `restore BACKUP NEW_TARGET`; never overwrite the active database. Verify manifest/hash and record counts, select the new database path and restart locally. Backups include credential hashes and must be protected, never submitted.

## 14. Acceptance scenarios 08–13 — PENDING

Read `submission/evidence/acceptance-matrix.md`. Deterministic local tests are simulations, not genuine independent-host acceptance. Consult exact scenario definitions in `scripts/gce_acceptance_test.py` and runbook section 15. On a separately authorized disposable independent-Linux lab, establish healthy baseline, introduce only the prescribed isolated failure, verify timeout/classification/unaffected peers and restore it; capture monotonic timing and audit before/after. Infrastructure-mutating cloud drills require a NEW explicit authorization and safety review; they are not authorized here. Do not count SKIPPED/NOT IMPLEMENTED as PASS.

## 15. Final browser regression and artifacts — PENDING

```powershell
uv run --no-sync python scripts/run_browser_qa.py
uv run --no-sync python scripts/run_browser_qa.py --first-run
uv run --no-sync python scripts/compile_submission.py
Get-FileHash submission\final\Adarsh_Singh_SWFW_5S_12.pdf -Algorithm SHA256
Get-FileHash submission\final\Adarsh_Singh_SWFW_5S_12_PROJECT-FILES.zip -Algorithm SHA256
```

Expected automated browser fixtures: MOCKED SSH/Prometheus, zero unexpected console/network errors and cleanup true. Open the PDF, inspect diagram/screenshots/pages and extract the ZIP into a clean directory. Compare hashes to `submission/final/SHA256SUMS.txt`. Record your own pass/fail and screenshot references for each section only after performing it. Confirm official deadline with organizers: local charter says 2–5 November 2026; the supplied 12 November date is not locally established.