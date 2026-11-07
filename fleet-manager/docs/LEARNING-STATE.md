# Current learning and engineering checkpoint

## Chunk 10F: administrator password authentication and session management - 2026-11-07

Author/environment: executing Antigravity agent, Windows PowerShell, repository `.venv` Python 3.12, Node.js and isolated headless Chrome/CDP runner. User authorized Chunk 10F implementation and one logical conventional commit. Pre-edit HEAD matched `35cae2859bde5351dd0cf6acfc38114445ad804a`; working tree was clean and `main` was 5 commits ahead of `origin/main`. Root and product AGENTS.md, charter, checkpoint, database repositories, API dependencies, and frontend request handling were inspected before modifying code.

- **Authentication Architecture & Password Security**: Replaced the raw Bearer-token browser modal with single-administrator password authentication using Argon2id hashing via `pwdlib[argon2]`. Enforced bounds of 12-128 characters, constant-time verification, and zero storage/logging of plaintext passwords. Implemented SQLite schema evolution to `PRAGMA user_version = 6` creating the `administrator_credentials` table with a singleton `id=1 CHECK (id = 1)` constraint, storing Argon2id hashes and bootstrap password-change flags.
- **Server-Managed Session & CSRF Architecture**: Built an opaque, server-managed in-memory session store (`SessionStore`) storing strictly SHA-256 verifiers of session secrets. Issued sessions via `HttpOnly`, `Path=/`, `SameSite=Lax` cookies with bounded idle timeout (1800s / 30m) and absolute expiration (43200s / 12h). Implemented robust CSRF verification combining strict `Origin`/`Referer` checks and synchronizer tokens (`X-CSRF-Token`). Rate-limited failed login attempts (5 attempts per 60s window with 300s lockout, bounded to 1,000 tracked IPs to avoid memory exhaustion).
- **First-Run Bootstrap Lifecycle**: Supported `FLEET_MANAGER_INITIAL_PASSWORD` for automated initial provisioning. Insecure placeholder bootstrap (`CHANGEME`) is strictly restricted to loopback connections, fails closed on remote interfaces, and forces mandatory password change on first login. Once an administrator credential is persisted in SQLite, `FLEET_MANAGER_INITIAL_PASSWORD` is permanently ignored on subsequent restarts. If unset, an interactive first-run setup wizard (loopback restricted) initializes the instance.
- **API Bearer Compatibility & Independence**: Kept the existing `FLEET_MANAGER_API_TOKEN` Bearer token mechanism fully intact and backwards-compatible for programmatic clients, scripts, and Prometheus scraping. Browser dashboard requests authenticate exclusively using session cookies; raw tokens and passwords are never retained or persisted in JavaScript memory (`state.js`) or client-side storage (`localStorage`/`sessionStorage`/cookies).
- **Frontend Redesign & Dialog Ownership**: Redesigned `#auth-modal` into a multi-view accessible modal covering First-Run Setup (password creation, confirmation, inline length validation), Normal/Initial Login (password input, show/hide visibility toggle, accessible error states), and Mandatory First-Login Password Change (bootstrap password context, new password, confirmation). Integrated with the shared `dialog-ownership.js` system (`activateDialog(modal, { priority: true })`) to ensure onboarding and auth modals maintain mutually exclusive interactivity and focus trapping without state corruption.
- **Local Recovery Path**: Created standalone maintenance script [`scripts/reset_admin_password.py`](file:///C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5/fleet-manager/scripts/reset_admin_password.py) prompting interactively via `getpass` without echoing input, hashing with Argon2id, and safely updating the credential record in SQLite without deleting inventory, audit history, or SSH trust records.
- **Verification Evidence**:
  - Full Python suite (`pytest -q`): 485/485 passed (including 19 new tests in `tests/test_auth_redesign.py`, all auth unit tests, backup/restore, connectivity, and lifecycle checks).
  - Python UI integration suite (`pytest tests/test_ui.py`): 8/8 passed.
  - Frontend ES-module unit suite (`node --experimental-vm-modules --test tests/dashboard_modules.cjs tests/dashboard_regression.cjs`): 68/68 passed (covering setup submission, inline validation, forced password change, and visibility toggle).
  - Code hygiene: `ruff check src scripts tests` passed; `ruff format --check src scripts tests` passed across 97 files; `mypy src` passed across 48 source files.
  - Isolated Chrome/CDP browser QA (`scripts/run_browser_qa.py`): 87 assertions passed with zero unexpected console/network errors and `cleanup: true` at `.local/browser-qa/20261107T105359-4873729a/`. Captured all 5 required authentication journey screenshots:
    - `01-first-run-setup.png`
    - `02-changeme-initial-login.png`
    - `03-mandatory-password-change.png`
    - `04-normal-login.png`
    - `05-authenticated-dashboard.png`
- **Evidence Limits & Remaining Limitations**: Tests executed against local loopback FastAPI processes and mocked SSH transport; live multi-node GCE production deployment and physical hardware failures remain pending cloud demonstration. Student teach-back and video demonstration remain pending.
- **Exact Next Action**: Review the Chunk 10F commit, browser QA screenshots, and test reports with the student; verify student understanding of Argon2id hashing, session verifiers, and loopback security boundaries before proceeding to milestone submission or final packaging.

## Chunk 10E: operations workbench and audit history redesign - 2026-11-07

Author/environment: executing Codex agent, Windows PowerShell, repository `.venv` Python 3.12, Node.js and isolated headless Chrome/CDP runner. User authorized Chunk 10E implementation and one logical conventional commit. Pre-edit HEAD matched `62154624a67d701b6e8318dc070a4201bd11a5a8`; working tree was completely clean and `main` was 4 commits ahead of `origin/main`. Root and product AGENTS.md, charter, checkpoint, backend command catalog, and API response contracts were inspected before modifying code.

- **Operations Workbench Architecture**: Replaced the single-column operations console with a full-width Operations Workbench located directly beneath the fleet inventory. On desktop, structured as target context banner, two-column layout (Dispatch Console 42%, Result Inspector 58%), and full-width Audit History below. On tablet and mobile (<= 1024px), sections stack vertically. Internal horizontal scrolling is strictly confined to technical output containers (`.terminal-box` pre elements and `.table-responsive`), eliminating page-level horizontal overflow. Selecting "Operations" on any inventory row brings the workbench into view with reduced-motion awareness and moves keyboard focus appropriately; the "Return to Inventory" button restores focus directly to the invoking row's "Operations" button.
- **Dispatch Console & Inline Validation**: Implemented four accessible native radio controls styled as action tiles for the allowlisted actions (`system.uptime`, `system.memory`, `system.disk`, `service.status`). Dynamic argument inputs for `path` and `service_name` display contextually; hidden argument inputs are disabled to prevent hidden required-input browser validation failures. Inline client-side validation enforces POSIX absolute paths without traversal or whitespace for disk queries, and alphanumeric/safe metacharacters without leading hyphens for service status, while backend catalog validation remains authoritative.
- **Live Read-only Command Preview**: Integrated an allowlisted command preview displaying exact compiled invocations (`uptime`, `free -m`, `df -h -P -- <path>`, `systemctl --no-pager status -- <service>`), matching backend catalog compilation via safe DOM text nodes. Clearly labelled as a read-only preview of allowlisted commands, not an interactive shell or terminal.
- **Execution Lifecycle & State Ownership**: Separated staged target, in-flight execution, latest execution result, and inspected historical record into distinct in-memory state mappings. Fixed global button-lock behavior so in-flight execution on one node does not disable dispatch controls when switching to independent nodes. Preserved epoch-based stale-response protection against out-of-order responses. Added accessible live screen-reader announcements for dispatch progress, terminal outcomes, and audit inspection. Handled HTTP 409 conflict, HTTP 429 capacity rejection, HTTP 503 admitted timeout (offering inspection of admitted operation ID), and network failure without replay.
- **Result Inspector & Audit History**: Presenting terminal outcome, job ID, target node, action/arguments, execution duration (calculated strictly from valid started/completed timestamps), exit code, failure category, requested/started/completed timestamps, and truncation tag. Output streams are rendered safely via pure text nodes into preformatted monospace containers preserving Linux formatting (`white-space: pre; word-break: normal;`), eliminating decorative terminal dots and hardcoded blue/cyan styles in favor of Graphite + Warm Neutral + Muted Sage tokens. Copy output button provides explicit visual and live feedback. Semantic Audit History table renders requested time, action, arguments, duration, exit code, failure category, outcome badge, and record inspection control; pagination uses honest record counts ("Showing records 1–20") and recovers cleanly from empty subsequent pages.
- **Verification Evidence**:
  - Full Python suite (`pytest -q`): 466 passed, 1 pre-existing Starlette/httpx deprecation warning.
  - Python UI integration suite (`pytest tests/test_ui.py`): 8 passed.
  - Frontend ES-module unit suite (`node --experimental-vm-modules --test tests/dashboard_modules.cjs tests/dashboard_regression.cjs`): 60 passed (including 14 new tests covering validation, preview, duration calculation, outcome rendering, state separation, stale protection, and pagination recovery).
  - Code hygiene: `ruff check` passed; `ruff format --check` passed (89 files); `mypy src` passed (42 source files); `git diff --check` passed with zero whitespace errors.
  - Isolated Chrome/CDP browser QA (`scripts/run_browser_qa.py`): 79 assertions passed with zero unexpected console or network errors and `cleanup: true` at `.local/browser-qa/20261107T083035-8ecb9397/`. Captured and visually inspected 17 screenshots across 1440, 1024, 768, and 390px viewports, verifying responsive stacking, focus restoration, live execution feedback, clipboard interaction, and lack of page-level horizontal overflow.
- **Evidence Limits & Remaining Limitations**: Verified against local loopback FastAPI processes and mocked SSH transport; multi-node live GCE deployment and physical network partitions were not executed in this local session. Student teach-back and video demonstration remain pending.
- **Exact Next Action**: Review the Chunk 10E commit, screenshots, and test results with the student; verify student understanding of execution state ownership vs audit history before proceeding to Milestone 4 submission packaging or subsequent release tasks.

## Chunk 10D: onboarding redesign remediation - 2026-11-07

Author/environment: executing Codex agent, Windows PowerShell, repository `.venv` Python, Node.js and isolated headless Chrome/CDP. User approved continuing the seven existing modified files and one logical commit. Pre-edit HEAD was `458ffbc443752f298f72857be2244fb5b22e71c9`; `main` was three commits ahead of `origin/main`, with exactly seven unstaged tracked changes and no staged or untracked files. Existing work was preserved.

- Continued the existing onboarding UI: independently verified host-key acknowledgement remains tied to the current node, exact scanned fingerprint and scan revision; it resets on rescan, node switch and reopen. The backend still rechecks the presented fingerprint. Scanned and trusted fingerprints, setup state, connectivity state and actual SSH check outcome remain separate. No backend/API/SSH transport/schema/authentication policy/deployment change was made.
- Added shared dialog ownership for authentication and onboarding: authentication takes priority, only the top dialog is interactive, original background `inert` values are restored after the last close, and focus returns to the prior dialog or a usable control. Direct node switching does not overwrite ownership. A mismatch now shows the scanned and pinned fingerprints, blocks trust, explains rescan versus administrative review, and leaves rescan available. Removed temporary scan debug output and updated stale browser QA assertions.
- RED evidence: new ES-module dialog ownership and mismatch tests failed on the existing implementation before fixes. Final focused Python UI/auth/onboarding/trust/connectivity suites: 89 passed, one existing Starlette/httpx deprecation warning. Frontend ES-module command (`dashboard_modules.cjs` plus `dashboard_regression.cjs`): 46 passed. Ruff check and format check passed for `src tests scripts` (89 formatted files); mypy passed for 42 source files; `git diff --check` found no whitespace errors. Repository-wide `ruff check .`/`format --check .` include pre-existing lesson practice files and fail there; the only new runner formatting issue was corrected, then the project code scope passed.
- Isolated browser QA passed at `.local/browser-qa/20261107T042204-f568786b/`: 63 assertions, 13 screenshots, zero unexpected console or network failures, cleanup true. It covered auth retry while onboarding is open, focus/background restoration, direct node switch, mismatch and rescan, failed HTTP-200 SSH outcome and successful retry, keyboard interaction, and 1440/1024/768/390px plus short-viewport layout. Screenshots were inspected locally. Earlier unsuccessful QA runs were diagnostic; each reported cleanup true.
- Evidence limits: browser QA uses disposable loopback data and mocked SSH transport; no live GCE/three independent nodes, cross-browser screen reader check, student teach-back or video evidence occurred. Existing 10C observations remain historical. Exact next action: review this 10D commit and browser evidence with the student, then obtain separate approval before Chunk 10E.

## Chunk 10C: fleet overview and node inventory - 2026-11-06

Author/environment: executing Codex agent, Windows PowerShell, local `.venv/Scripts/python.exe`, Node.js and isolated Chrome/CDP QA. The user authorized this chunk and one conventional commit. Pre-flight HEAD matched `67478d0247a1ea3af4506df7a8877f8e3bac332c`; working tree was clean and `main` was two commits ahead of `origin/main`. Root/nested instructions, charter, checkpoint, dashboard, frontend state, API schemas and tests were inspected before editing.

- Files changed: `src/fleet_manager/ui/templates/dashboard.html`; `src/fleet_manager/ui/static/js/fleet.js`, new `inventory-view.js`; `src/fleet_manager/ui/static/css/layout.css`, `components.css`, `responsive.css`; `tests/test_ui.py`, `tests/dashboard_modules.cjs`; `scripts/browser_qa.cjs`; and this checkpoint. No backend, API, schema, SSH, scheduler, metrics, dependency or deployment file changed.
- Decisions: six overview counts use the existing `/api/nodes/status` states directly. Browser refresh time is recorded only after successful fetch; an outage marks the inventory stale/unverified while retaining the last success time. Each row renders the API observation timestamp, age and expiry using `observation_ttl_seconds`, with explicit missing/invalid timestamp states. Connectivity, setup and failure reason have separate columns. Rendering uses DOM nodes and `textContent`; existing actions and memory-only request ownership remain in `fleet.js` and `state.js`.
- One semantic table renders the API data at every width. At 1440px, inventory occupies the full workspace width and all columns/actions fit without internal horizontal scrolling. At 1024px, endpoint and failure reason are visually hidden to prioritize node, connectivity, setup, observation and actions. At 768px, those priority columns use internal table scrolling. At 390px, the same table rows form labelled compact records; no second data fetch or state path was added. Search has a visible label, filters expose `aria-pressed`, and a live result count shows visible/total nodes.
- Test evidence: TDD RED had three new ES-module tests fail before implementation. `pytest tests/test_ui.py -q`: 8 passed, one existing Starlette/httpx deprecation warning. `node --experimental-vm-modules --test tests/dashboard_modules.cjs tests/dashboard_regression.cjs`: 32 passed. Ruff lint passed; Ruff format check passed for 77 files; mypy passed for 42 source files. Isolated browser QA passed with cleanup true and no unexpected console or network failures at `.local/browser-qa/20261106T164710-adfdce19/`. Browser assertions cover API TTL, refresh/outage behavior, search count, filters, icons, focus, reduced motion, authentication, operations/onboarding interactions, all four widths, no page overflow, 1440px no inventory scroll, and a 390px record.
- Screenshots: before 10B layout `.local/browser-qa/20261106T162225-491b4b4b/dashboard-{1440x900,1024x800,768x1024,390x844}.png`; after `.local/browser-qa/20261106T164710-adfdce19/` with the same dashboard filenames plus `inventory-390x844.png`. Real Chrome screenshots were rendered and inspected. Remaining visual/accessibility limitation: at 768px, primary row actions toward the right need internal table scrolling; 1024px intentionally omits endpoint/failure reason visually. Mobile rows retain semantic table markup and visually hidden column headers, but assistive technology behavior across browsers was not independently tested. No live GCE, SSH or Grafana verification, student teach-back or video assessment occurred.
- Exact next action: review this commit and screenshot set; obtain explicit approval before onboarding redesign.

## Chunk 10B: premium design foundation and application shell - 2026-11-06

Author/environment: executing Codex agent, Windows PowerShell, local `.venv/Scripts/python.exe`, Node.js, isolated Chrome/CDP browser QA. User approved this scope and one conventional commit. Git was clean at start (`main` ahead of `origin/main` by one commit); existing history and prerequisites were preserved.

- Files changed: `src/fleet_manager/ui/static/css/tokens.css`, `layout.css`, `components.css`, `responsive.css`; `src/fleet_manager/ui/static/icons.svg`; `src/fleet_manager/ui/templates/dashboard.html`; `src/fleet_manager/ui/static/js/fleet.js`, `operations.js`; `tests/test_ui.py`; `scripts/browser_qa.cjs`; and this checkpoint.
- Decisions: Graphite surfaces, warm neutral text and muted sage accent use local system fonts and CSS tokens; header separates brand, loopback control context and navigation. One local stroked SVG sprite supplies interface icons. Shared focus rings, input/button treatments and reduced motion apply across the existing screen. Narrow navigation wraps so actions remain visible. No new dependency or remote asset was added.
- Corrected the existing ambiguous “Observed Nodes Availability” ratio by removing its display and calculation. The existing state counts remain REACHABLE, UNREACHABLE, CHECK_ERROR, STALE and NOT_CHECKED; overview metric redesign, including any coverage or SSH success ratio, is reserved for a later approved increment.
- Observed tests: `pytest tests/test_ui.py -q` 8 passed, one existing Starlette/httpx deprecation warning; `node --experimental-vm-modules --test tests/dashboard_modules.cjs tests/dashboard_regression.cjs` 24 passed; Ruff check and format check passed (77 files); mypy passed (42 source files). A first ES-module invocation without the required Node VM flag failed due to `vm.SourceTextModule` being unavailable, then the documented flag passed. Isolated browser QA passed with cleanup true and no unexpected console/network failures at `.local/browser-qa/20261106T162049-6ff7f7eb/`. Browser checks included auth/logout/reload, API outage recovery, local SVG rendering, focus visibility, reduced motion, no remote resource requests and four viewport overflow assertions.
- Real screenshots: before `.local/browser-qa/20261106T161403-a22875ef/`; after `.local/browser-qa/20261106T162225-491b4b4b/`, each at 1440x900, 1024x800, 768x1024 and 390x844. The before run and final run used the same viewport list. Visual inspection found no page-level horizontal overflow or clipped shell actions after navigation wrapping. Existing inventory table still has internal horizontal scrolling, including at 1440px when the operations column is visible; its rightmost actions require scrolling. Its workflow redesign belongs to Chunk 10C. This local browser evidence does not establish live GCE, SSH, Prometheus or Grafana behavior. Student understanding and video evidence were not assessed.
- Exact next action: review the four before/after screenshot pairs and this commit; request explicit approval for Chunk 10C before inventory/overview work.

## Chunk 09: phase-aware SSH timeout classification - 2026-11-06

Author/environment: executing Codex agent, Windows PowerShell, repository
`.venv/Scripts/python.exe`. Authorized scope: local reliability correction,
tests, documentation, and one commit; no GCE access, deployment, VM change, UI
work, schema migration, or new dependency.

- User-supplied production report: stopping node C left controller `/healthz`
  at HTTP 200 and nodes A/B connected; C recorded `TIMEOUT`/`CHECK_ERROR`;
  after restart, the scheduler restored `REACHABLE`/`CONNECTED` and Prometheus
  later reported its exporter `up = 1`. No raw GCE logs were inspected here.
- Source inspection of Paramiko 5.1.0 showed that its internal multi-address
  connector re-raises a TCP `TimeoutError` directly while Fleet Manager's broad
  handler recorded it as generic `TIMEOUT`. The user-reported stopped-node-C
  evidence is consistent with TCP establishment timeout, but the historical
  observation does not prove that phase retrospectively.
- The transport now resolves IPv4/IPv6 stream candidates explicitly, applies
  the configured timeout to every TCP attempt, tries later candidates, and
  closes every attempted socket. It passes a successful socket to Paramiko
  while retaining the original normalized endpoint and port for strict host-key
  verification. No thread, hidden retry loop, dependency, enum, or schema was
  added.
- Deterministic all-failed policy: any TCP timeout becomes
  `CONNECTION_TIMEOUT`; all-refused becomes `CONNECTION_REFUSED`; other mixed
  socket errors remain `UNKNOWN_ERROR`. A wrapped post-connect SSH timeout is
  `TIMEOUT`; the existing parent deadline remains `EXECUTION_TIMEOUT`. The
  existing status contract maps only refused/connection-timeout to
  `UNREACHABLE`; all other failures remain `CHECK_ERROR` with their stored
  reason.
- RED evidence: the new transport suite initially failed 11 tests before the
  preconnect implementation, and the wrapped protocol-timeout case failed
  before cause-aware classification. A mutation that disabled timeout priority
  was caught by the mixed IPv6-timeout/IPv4-refusal test. The full suite also
  exposed the existing real process-backed banner-stall assertion; it was
  updated from `UNKNOWN_ERROR` to the more specific `TIMEOUT` and strengthened
  to verify persisted outcome and error category.
- Observed local verification: focused SSH transport/loopback tests 20 passed;
  freshness tests 14 passed; connectivity service, executor, status, and
  scheduler tests 42 passed; focused real banner-stall test 1 passed. Full
  pytest passed 466 tests with one existing Starlette/httpx deprecation warning
  in 109.89 seconds. Ruff lint passed, Ruff format check passed after formatting
  77 files, and mypy reported no issues in 42 source files.
- Evidence limit: candidate ordering and failures are deterministic local test
  doubles except for the existing loopback SSH and banner-stall coverage. No
  cloud endpoint was contacted, so this commit does not reclassify the earlier
  GCE row or claim live post-change verification. Authentication timeout remains
  represented by Paramiko's authentication exception contract. Student
  understanding and video evidence were not assessed.
- Exact next action: in a later approved increment, add a disposable dual-stack
  integration harness that exercises real operating-system resolver ordering
  and mixed IPv4/IPv6 failures through the isolated worker.

## Acceptance correction - 2026-11-05

Author/environment: executing Codex agent, Windows PowerShell, repository `.venv/Scripts/python.exe`.
Authorized scope: focused acceptance/runbook correction, local verification only; no GCE operations,
no live fault injection, no commits/pushes. Earlier entries below are preserved historical reports;
the previous ?14/14 mock passes? did not establish real fault-scenario or GCE evidence.

- Removed automatic trust enrollment: test 03 is an explicit independent-fingerprint manual gate.
- SSH probes originate from the controller API; actual inventory IDs are resolved by endpoint.
- Read-only operations require nine SUCCESS results with real output shapes and matching audit records.
- Prometheus checks the controller plus all three exact exporter instances at up=1; Grafana checks
  datasource configuration, proxied Prometheus results and provisioned dashboard panel contracts.
- Tests 08-13 stay SKIPPED/NOT IMPLEMENTED even when the compatibility opt-in flag is supplied.
  Offline mode reports 2 local passes and 12 skips; exit 2 means incomplete, never full acceptance.
- Tunnel now forwards 8000/3000/9090 on explicit loopback with ExitOnForwardFailure.
  Runbook section 15 supplies exact manual procedures and evidence limits for all four requirements.
- Observed local verification: Python 458 passed (one Starlette/httpx deprecation warning);
  frontend ES modules 12 passed; isolated Chrome/CDP runner exit 0, cleanup true, report at
  `.local/browser-qa/20261105T073619-b92a36af/`; Ruff lint and format passed (89 files);
  Mypy passed (42 source files). Tunnel Bash syntax and dry-run passed without invoking gcloud.
- Evidence limit: local mocked transport/browser behavior is not live SSH, GCE, Prometheus or
  Grafana evidence. All four official requirements still await live acceptance. Student understanding
  was not assessed; no independent learning demonstration or video completion is claimed.
- Exact next action: review runbook section 15, then obtain a separate authorized live session to
  independently verify all three host fingerprints before explicit enrollment. Fault tests need a
  separately authorized maintenance window and restoration plan; do not infer approval here.


## Final Milestone: GCE One-Shot Deployment Package & Acceptance Test Automation - 2026-11-05

Author/environment: executing Antigravity agent, Windows PowerShell, Python 3.12.8 from `.venv/Scripts/python.exe`, Node v24.18.0. User-authorized scope: GCE one-shot deployment package and acceptance testing automation; stop at delivery.

- **Infrastructure Verification & Firewall Discovery**:
  - GCE Project: `project-3682976b-7d4a-465a-933`, Zone: `asia-south1-a`.
  - Topology: Controller `10.160.0.2`, Nodes `10.160.0.5` (A), `10.160.0.3` (B), `10.160.0.4` (C).
  - Verified VPC firewall `default-allow-internal` covers `10.128.0.0/9` (`tcp:0-65535`), ensuring internal Node Exporter TCP 9100 communication from controller to managed nodes is permitted without extra firewall rules.
  - Enforced loopback invariant on controller (`127.0.0.1:8000`, `127.0.0.1:3000`) and established SSH port forwarding through existing IAP SSH connection (`-L 8000:127.0.0.1:8000 -L 3000:127.0.0.1:3000`), avoiding VPC exposure or new ingress rules.
- **Reproducible Deployment Package (`deploy/gce/`)**:
  - `00-config.env`: Centralized environment and IP topology configuration.
  - `01-start-vms.sh`: Boots all 4 VMs, polling until `RUNNING` status.
  - `02-setup-nodes.sh`: Installs and enables `prometheus-node-exporter` on managed nodes via IAP SSH.
  - `03-setup-controller.sh`: Installs prerequisites, Astral `uv`, standalone CPython 3.12 (guaranteeing Python 3.12 on Ubuntu 26.04), Prometheus, Grafana, directory permissions, and systemd units.
  - `04-deploy-app.sh`: Locked virtualenv sync (`uv sync --locked --no-dev`), high-entropy operator token generation in `/etc/fleet-manager/fleet-manager.env` (mode 0600), and unit enablement.
  - `05-transfer-keys.sh`: Transfers `~/.ssh/fleet-bootstrap` via IAP SCP to `/etc/fleet-manager/id_ed25519` (mode 0600, `fleet-manager:fleet-manager`) and initializes writable `/var/lib/fleet-manager/known_hosts`.
  - `06-start-tunnel.sh`: Launches local secure IAP SSH port forwarding tunnel.
  - `07-cleanup-vms.sh`: Stops all 4 VMs, confirms `TERMINATED` status, preserves persistent disks & firewall rules, and reports residual storage charges (~$1.60/month across 40 GB).
  - `deploy-all.sh`: Idempotent master deployment orchestrator. All scripts enforce `--dry-run` by default and require `--execute` for live cloud actions.
- **Automated Acceptance Test Suite (`scripts/gce_acceptance_test.py`)**:
  - Built 14 comprehensive tests across 2 tiers: Non-Destructive Baseline (Auth barrier, SSH reachability, onboarding/host-key trust, status derivation, read-only remote commands, Prometheus scrapes, Grafana health) and Opt-In Fault-Injection (credential rejection, host-key mismatch rejection with rollback, timeout/unreachability, recovery, partial fleet failure, crash reconciliation, and offline DB restore with safety snapshot).
  - Implemented offline `--mock` execution mode allowing 100% of test logic to run and pass locally in CI without cloud VMs.
- **Deployment Source Integrity & Standalone Bundle Packaging**:
  - Implemented `scripts/package_source_bundle.py` creating a self-contained, reproducible source tarball (`dist/fleet-manager-source-bundle.tar.gz`) directly from the working tree.
  - Successfully bundles 196 verified files, capturing uncommitted changes and untracked core files (`onboarding.py`, `trust.py`, `readiness.py`, `ui/static/`, `ui/templates/`, `tests/test_gce_acceptance.py`), reflecting intentional file deletions without relying on git clone, git archive, or remote GitHub repository access.
  - Strict exclusion filters verified: `.git`, `.venv`, `.local`, `__pycache__`, SQLite databases (`*.db*`), private keys (`id_*`, `*.key`), and secret `.env` files are excluded.
  - Generated and validated SHA-256 digest (`003e7c922f5b56005afff11402713ded37aacba76519f64eb42b268f660c5d7a`) with companion `.sha256` and JSON manifest.
  - Updated `deploy/gce/04-deploy-app.sh` and `deploy-all.sh` with `--bundle` support and pre-flight `sha256sum -c` verification prior to extraction on `fleet-controller`.
- **Observed Verification Baseline**:
  - Standalone bundle test suite (`tests/test_package_source_bundle.py`): **5/5 passed**.
  - Python test suite: **434 passed**, 1 warning (Starlette deprecation), 0 failures.
  - Acceptance suite: **14/14 passed** in `--mock` mode.
  - Frontend ES-module regression suite (`tests/dashboard_regression.cjs`): **12/12 passed**.
  - Frontend Chrome CDP browser QA suite (`scripts/run_browser_qa.py`): **passed cleanly (exit code 0)**.
  - Static analysis: Ruff lint passed across `src`, `tests`, `scripts`; Ruff format confirmed 89 files formatted; Mypy passed across 44 source files with zero issues.
  - Dry-run validation: `deploy-all.sh --dry-run` and `07-cleanup-vms.sh --dry-run` validated cleanly via Git Bash.
  - Cloud safety: Zero VMs started/stopped; all 4 VMs remain `TERMINATED`; zero cloud mutations; zero git commits/pushes.
- **Exact next action**: Execute one-session GCE live deployment using `deploy-all.sh --execute` and run `scripts/gce_acceptance_test.py` once operator provides cloud execution authorization.

Author/environment: executing Antigravity agent, Windows PowerShell, Python 3.12.8 from `.local/windows-verify/Scripts/python.exe`. Authorized scope: Chunk 09 Pass 2 (Verification Script Security and Safety); stop after Pass 2.

- Credential hardening:
  - Removed hardcoded API token from `scripts/verify_live_monitoring.py`.
  - Enforced `FLEET_MANAGER_API_TOKEN` environment variable across all live verification scripts (`smoke_test.py`, `verify_live_monitoring.py`).
  - Removed CLI `--token` argument to prevent secret exposure in process listings (`ps`).
  - Added HTTP error sanitization preventing credential/Authorization header echoing in diagnostics or exception messages.
  - Sourced Grafana credentials from `GRAFANA_USER` and `GRAFANA_PASSWORD` environment variables.
- Live data protection:
  - Enforced read-only execution by default against live instances in `smoke_test.py` and `verify_live_monitoring.py`.
  - Added `--allow-live-mutation` and `--isolated-test-env` opt-in guards: refused persistent smoke node creation on non-isolated targets due to absence of a safe deletion API.
  - Ephemeral test runs cleanly clean up temporary directories (`tempfile.mkdtemp`) upon completion.
- Live service restart safeguards:
  - Made service stop/restart strictly opt-in behind `--allow-service-restart` in `verify_live_monitoring.py`.
  - Explicitly states target service (`prometheus-node-exporter`) before execution and restores prior service state in `finally` blocks. Fleet Manager itself is never restarted.
  - Validated platform support (Linux systemd/systemctl) before attempting service management commands.
- Three-endpoint lifecycle safety:
  - Added preflight port conflict detection across all endpoint ports (2201-2203, 9101-9103) in `setup_three_endpoints.py`.
  - Added active setup detection to prevent duplicate start invocations from colliding.
  - Replaced broad process signals with targeted per-endpoint PID tracking and process command-line token ownership verification, preventing accidental termination of unrelated processes.
  - Implemented automatic rollback on partial startup failure and safe restoration of Prometheus `targets.json` from backup.
  - Replaced hardcoded POSIX ownership (`ash:ash`) with dynamic least-privilege user discovery (`SUDO_USER` / current user) only when executed as root.
  - Made machine-readable evidence generation opt-in via `--evidence` in `verify_three_endpoints.py`.
- Observed verification:
  - Standalone suite: 16 passed in `tests/test_verification_scripts.py`.
  - Full project suite: 275 passed, 1 warning (Starlette testclient deprecation), zero failures.
  - Ruff check: all checks passed across `src`, `tests`, `scripts`.
  - Ruff format: all 71 files formatted cleanly.
  - mypy: passed across 40 source files (`src` and `scripts/backup_restore.py`).
  - WSL Debian and Ubuntu remained stopped.
- Limits: live three-endpoint execution and Linux systemd service restart tests require running on an active Debian/WSL2 host and were not executed during this pass.
- Exact next action: proceed to Chunk 09 Pass 3 or subsequent scheduled pass.

## Chunk 06, Pass 2: remote operation instrumentation - 2026-11-02

Author/environment: executing Antigravity agent, Windows PowerShell, Python 3.12.8 from `.local/windows-verify/Scripts/python.exe`. User-authorized scope: remote operation instrumentation; stop after Pass 2.

- Operation metrics lifecycle: added `fleet_operations_total` (Counter, labels `action`, `outcome`), `fleet_operation_duration_seconds` (Histogram with buckets `0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, +Inf`, labels `action`, `outcome`), and `fleet_operations_active` (Gauge, label `action`) in `Telemetry`.
- Lifecycle measurement boundaries: active gauge increments upon admission in `on_start()` after worker process/executor capacity is reserved, and decrements reliably in `finally` across all paths (success, exit codes, SSH failures, timeouts, child crashes, storage errors). Duration measures elapsed monotonic time from `on_start()` to result return/failure. Rejected requests (invalid actions, node not found, concurrent same-node exclusion, capacity saturation) do not increment counters or corrupt active counts.
- Unconfirmed results: if SQLite persistence fails after remote execution completes, `operations_total` marks `UNCERTAIN` rather than falsely reporting a confirmed persisted outcome. Recovered historical records in `reconcile_in_flight()` are not counted as new executions.
- Application composition: injected `telemetry=telemetry` into `OperationService` in `main.py`, sharing the exact same `Telemetry` instance exposed by `/metrics`.
- Observed verification:
  - 34 passed in `tests/test_observability_unit.py` (20 Pass 1 + 14 Pass 2 tests).
  - 33 passed in `tests/test_operations_unit.py`.
  - 4 passed in `tests/test_operations_transport_loopback.py`.
  - 24 passed in `tests/test_monitoring_unit.py` and `tests/test_freshness.py`.
  - Ruff check and format check passed across all changed and relevant source and test files.
  - mypy passed across all 39 source files without issues.
- Limits: Grafana dashboard panels and Prometheus alerts for operations are not yet added.
- Exact next action: Proceed to Chunk 06 Pass 3 (Grafana panel additions, end-to-end monitoring verification, and learning guide).

## Chunk 06, Pass 1: collector self-observability - 2026-11-02

Author/environment: executing Codex primary agent, Windows PowerShell, Python 3.12.8 from `.local/windows-verify/Scripts/python.exe`. User-authorized scope: collector reliability only; stop after Pass 1. Engineering evidence below does not establish student understanding or video completion.

- Existing lifecycle: each `Telemetry` owns its registry and event metrics. `/metrics` renders it; a dynamic callback reads `ConnectivityService.fleet_status()` from SQLite inventory/latest observations and derives five display-status counts without SSH probes. Previously, collection exceptions silently removed those counts from HTTP 200 responses.
- Added fixed `collector="fleet_status"` health series: success is 1 on success and 0 on failure; errors increase once per failed collection attempt; last-success time is Unix seconds and survives failures. Timestamp 0 means no successful collection yet. Without an attached service there is no attempt, success is 0, and errors do not increase. These values reset with a new Telemetry instance/process.
- Each configured scrape triggers one collection; successful scrapes do not increase application event counters. Failure omits unavailable counts, retains collector health, and returns HTTP 200. Exposition failure returns a sanitized HTTP 500. Collection runs before health metrics are read; renders are serialized per registry to prevent mixed collection results. No cache or background refresh was added.
- Observed: initial two regression tests failed on missing health samples, then passed after implementation. Final standalone observability suite: 20 passed. Combined observability, monitoring-unit, and freshness run: 44 passed. Ruff check and format check passed for five changed Python files; mypy passed for four metrics modules. One existing Starlette/httpx deprecation warning remains.
- Validation commands, from `fleet-manager/`:
  - `.local/windows-verify/Scripts/python.exe -m pytest --noconftest -p no:cacheprovider tests/test_observability_unit.py -q`
  - `.local/windows-verify/Scripts/python.exe -m pytest --noconftest -p no:cacheprovider tests/test_observability_unit.py tests/test_monitoring_unit.py tests/test_freshness.py -q`
  - `.local/windows-verify/Scripts/python.exe -m ruff check src/fleet_manager/metrics/registry.py src/fleet_manager/metrics/router.py src/fleet_manager/metrics/telemetry.py tests/test_observability_unit.py tests/test_metrics.py`
  - `.local/windows-verify/Scripts/python.exe -m ruff format --check src/fleet_manager/metrics/registry.py src/fleet_manager/metrics/router.py src/fleet_manager/metrics/telemetry.py tests/test_observability_unit.py tests/test_metrics.py`
  - `.local/windows-verify/Scripts/python.exe -m mypy src/fleet_manager/metrics/__init__.py src/fleet_manager/metrics/registry.py src/fleet_manager/metrics/router.py src/fleet_manager/metrics/telemetry.py`
- Limits: local standalone validation only. Existing `test_metrics.py` and `test_prometheus_pipeline.py` depend on uncommitted application composition and were not executed; the former's label allowlist now includes `collector`. The new suite uses only the existing router in a minimal FastAPI app and requires neither `main.py` nor application `conftest.py`. Large-fleet scrape latency and live Prometheus/Grafana behavior remain unverified; serialized scrapes can wait behind a slow query.
- Exact next action: review the Pass 1 diff and agree Pass 2's operation-metric contract. Proposed later split, pending explicit scope: Pass 2 operation instrumentation; Pass 3 Grafana/monitoring integration and deployment verification. No operation metrics, Grafana or deployment changes, application composition edits, staging, commits, or pushes belong to this pass.

## Release candidate service verification - 2026-10-27

Author/environment: executing Codex primary agent; Windows PowerShell driving Debian 12 WSL2 systemd. No student understanding was assessed in this session.

- Observed: locked production install in `/opt/fleet-manager`; enabled systemd unit active as unprivileged `fleet-manager`, with sandbox directives verified. Live authentication, inventory, dashboard, and metrics checks passed; stop/start/restart preserved inventory.
- Observed: online backup and separate-path restore of disposable schema-v3 data; node, observation, and operation counts each remained 1, representative records matched, integrity check returned `ok`, and the service started and restarted against the restored database. Backup, manifest, and restored files were mode 0600.
- Observed: existing Prometheus target `up`, 5 fleet status series, Grafana health `ok`, provisioned datasource and dashboard present. Installed monitoring configuration was not changed.
- Corrected deployment database-path handling, backup permissions, environment timeout key, and runbook installation/restore paths. Focused tests: 13 passed; changed Python files passed Ruff check and format check. Evidence: `fleet-manager/.local/release-candidate-evidence.txt` (ignored local file).
- Limit: WSL2 is not an independent native Linux host; fresh-host boot and browser rendering remain unverified. Next action: demonstrate on a clean Debian VM and capture the required report screenshots/flow diagram separately.

Date: 2026-10-27
Author/environment: executing Antigravity agent, Windows PowerShell & Debian 12 WSL2; Python 3.12 via uv; systemd services (ssh, prometheus, prometheus-node-exporter, grafana-server). Session policy: edits confined to this project; no commits or pushes.

## Current status: reproducible Linux deployment and release readiness

- Completed SWFW_5S_12 reproducible Debian 12 Linux deployment and release readiness milestone.
- **Deployment Artifacts & Configuration**:
  - Configuration template: [`deploy/fleet-manager.env.example`](file:///C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5/fleet-manager/deploy/fleet-manager.env.example) documenting all settings with no embedded credentials.
  - Systemd service unit: [`deploy/fleet-manager.service`](file:///C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5/fleet-manager/deploy/fleet-manager.service) with sandboxing directives (`NoNewPrivileges=true`, `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp=true`, `CapabilityBoundingSet=`).
  - Deployment runbook: [`docs/DEPLOYMENT-RUNBOOK.md`](file:///C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5/fleet-manager/docs/DEPLOYMENT-RUNBOOK.md) documenting prerequisites, service accounts, directory trees, host-key enrollment, lifecycle commands, and disaster recovery.
  - Monitoring provisioning: Reproducible Prometheus config (`prometheus.yml`, `targets.json`) and Grafana datasources/dashboards (`dashboards.yaml`, `prometheus.yaml`, `fleet-monitoring.json`).
- **Database Backup & Disaster Recovery**:
  - Implemented [`scripts/backup_restore.py`](file:///C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5/fleet-manager/scripts/backup_restore.py) providing safe online SQLite backups via `sqlite3.Connection.backup()`, integrity validation (`PRAGMA integrity_check`, `PRAGMA user_version = 3`), metadata manifest generation (SHA-256 checksum, table record counts), and pre-flight verified restoration.
  - Verification self-test passed on both Windows and Debian Linux.
- **Release Smoke Test**:
  - Implemented [`scripts/smoke_test.py`](file:///C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5/fleet-manager/scripts/smoke_test.py) validating API authentication, inventory registration, status derivation, `/metrics` exposition, `/dashboard` security headers (`nosniff`, `DENY`), and live Prometheus/Grafana service health.
  - Verified against live Debian 12 WSL2 services and Windows.
- **Automated Test Baseline & Linting**:
  - 119/119 unit and integration tests passing on Windows and Debian Linux.
  - Ruff check and format check clean across all 62 files; Mypy clean across 39 source files.

## Previous status: three-endpoint Linux fleet integration demonstration

- Completed SWFW_5S_12 three-endpoint integration demonstration on WSL2 with automated setup and verification scripts ([`setup_three_endpoints.py`](file:///C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5/fleet-manager/scripts/setup_three_endpoints.py) and [`verify_three_endpoints.py`](file:///C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5/fleet-manager/scripts/verify_three_endpoints.py)).
- **Infrastructure & Failure Domains**:
  - Transparently documented shared failure domains: single Windows 11 host and shared WSL2 Linux kernel (`6.18.33.2-microsoft-standard-WSL2`), root filesystem, and underlying hardware metrics.
  - Three isolated service endpoints on loopback ports: `endpoint-alpha` (SSH 2201, Exporter 9101, ID 1), `endpoint-beta` (SSH 2202, Exporter 9102, ID 2), and `endpoint-gamma` (SSH 2203, Exporter 9103, ID 3).
  - Pinned unique ED25519 host keys individually in `known_hosts`; verified host key mismatch enforcement and least-privilege credentials.
- **Monitoring & Metrics Isolation**:
  - Real Node Exporters scraped individually by Prometheus; verified active target status (`up=1`), available memory, and root disk metrics across all endpoints.
  - Scrape failures strictly distinguished from SSH connectivity failures.
- **Observed Failure & Recovery Latencies**:
  - Simulated SSH failure on `endpoint-beta`: detected in **1.108s** (`CONNECTION_REFUSED`, derived status `UNREACHABLE`). Healthy peers `endpoint-alpha` and `endpoint-gamma` remained unaffected (`CONNECTED`). Exporter on port 9102 remained `up=1`.
  - SSH service restored on `endpoint-beta`: recovered in **1.151s** (`CONNECTED`, derived status `REACHABLE`).
  - Simulated exporter failure on `endpoint-gamma`: Prometheus detected down in **5.048s** (`up=0`). Peer exporters (9101, 9102) remained `up=1`. Fleet Manager SSH check to `endpoint-gamma` remained `CONNECTED` and `REACHABLE`.
  - Exporter restored on `endpoint-gamma`: Prometheus detected recovery in **4.038s** (`up=1`).
- **Remote Operations & Persistence**:
  - Executed all 4 catalog actions across targets: `system.uptime` (alpha), `system.memory` (beta), `system.disk` (gamma), `service.status` (alpha). All returned exit code 0 and valid Linux outputs.
  - Verified durability of audit records across control-plane restart.
- **Automated Test Suite & Code Quality**:
  - 119 tests passing on both Windows and Debian Linux.
  - Ruff lint clean, Ruff format clean (60 files), Mypy clean (39 source files).
  - Clean teardown verified: test processes terminated and `/etc/prometheus/targets.json` restored to baseline.

## Previous status: fleet operations dashboard

- Completed SWFW_5S_12 fleet operations dashboard milestone with a lightweight, browser-based single-page application over existing backend endpoints (`GET /` and `GET /dashboard`).
- **Dashboard architecture & features (`fleet_manager.ui`)**:
  - Real-time fleet overview stats, node onboarding form, and live inventory table displaying derived connectivity statuses (`NOT_CHECKED`, `REACHABLE`, `UNREACHABLE`, `STALE`, `CHECK_ERROR`), freshness duration, observation timestamps, and detailed failure reasons.
  - Interactive manual SSH connectivity check button with dynamic badge updates.
  - Controlled remote operations panel: allowlisted action selection (`system.uptime`, `system.memory`, `system.disk`, `service.status`) with dynamic typed argument inputs.
  - Terminal-style output inspector displaying exit status, execution duration, output truncation indicator (for >= 64 KiB output), and chronological operation audit history.
  - Direct operational links to the provisioned Grafana dashboard and control-plane `/metrics`.
  - Comprehensive UI state handling: loading spinners, error alerts, empty states, and partial-failure messages.
- **Security & guardrails**:
  - Ephemeral in-memory operator authentication: bearer token is retained only in a JavaScript closure variable; never stored in `localStorage`, `sessionStorage`, or cookies.
  - Strict DOM text-node rendering (`textContent` and `createTextNode`) prevents XSS injection from malicious node names, untrusted arguments, or remote command output.
  - HTTP response security headers `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` enforced on UI routes.
  - Loopback-only service architecture with no external network exposure.
- **Live verification & test suite**:
  - Live Uvicorn server verification (`scripts/verify_dashboard_live.py`) passed end-to-end: HTML delivery, security headers, 401 unauthenticated guardrail, XSS payload resistance, status reporting, operation execution, and history retrieval.
  - Live SSH execution verification (`scripts/verify_remote_operations.py`) passed against Debian 12 WSL2 OpenSSH target.
  - 119 tests passing on both Windows and Debian Linux (including UI tests in `test_ui.py`). Ruff lint/format clean across 58 files; mypy clean across 39 source files.

## Previous status: controlled remote operations (safe read-only operations slice)

- Completed SWFW_5S_12 controlled remote command execution milestone with strict security guardrails, feature module `fleet_manager.operations`, and live verification on Debian 12 WSL2 and Windows.
- **Action catalog & validation**: Implemented explicit allowlist in `catalog.py` for safe read-only operations (`system.uptime`, `system.memory`, `system.disk`, `service.status`). Arbitrary commands and destructive actions (`service.restart`, `reboot`, etc.) are rejected with 422 `invalid_action`. Arguments are strictly typed and sanitized (e.g. `service.status` enforces `^[a-zA-Z0-9_\-\.@]{1,64}$` with no leading hyphens or metacharacters; `system.disk` enforces absolute POSIX path without directory traversal or shell characters).
- **Transport & process execution boundary**: Remote execution is performed strictly over authenticated SSH channels (`ParamikoOperationTransport`) reusing strict host-key checking and least-privilege credentials. Commands are never executed locally on the control plane. `ProcessOperationExecutor` provides child-process isolation (`python -m fleet_manager.operations.worker`), bounded execution timeout, bounded output memory (default 64 KiB with `output_truncated` flag), admission control (`OperationBusy` -> 429), and per-node concurrency exclusion (`OperationInProgress` -> 409).
- **Schema version 3 & audit trail**: SQLite schema upgraded to `PRAGMA user_version = 3` with append-only table `operation_executions` recording job ID, node ID, action, arguments, requested/started/completed timestamps, outcome, failure category, exit code, bounded stdout/stderr, output truncation flag, and sanitized audit metadata (`operator_type`, `operator_digest_prefix`).
- **Failure & uncertainty classification**: Distinguishes `SUCCESS`, `FAILURE`, `TIMEOUT`, and `UNCERTAIN` (`TRANSPORT_ERROR` after dispatch, `CONTROL_PLANE_RESTARTED`). Exactly-once execution is never claimed over unreliable networks. On startup, `reconcile_in_flight()` safely marks any leftover `RUNNING` rows as `UNCERTAIN`.
- **API endpoints**:
  - `POST /api/nodes/{id}/operations`: authenticated synchronous bounded execution.
  - `GET /api/nodes/{id}/operations`: list operation audit records for node.
  - `GET /api/nodes/{id}/operations/{op_id}`: retrieve single operation audit record.
- **Live demonstration & verification**:
  - Executed `scripts/verify_remote_operations.py` against real Linux target (Debian 12 WSL2 sshd on port 22 with `ash` user): verified `system.uptime`, `system.memory`, `system.disk`, and `service.status` (ssh service) returned authentic Linux kernel/system outputs with exit code 0.
  - Demonstrated rejection of invalid bearer tokens (401), disallowed actions (422), and shell injection attempts (422).
  - Verified crash reconciliation: simulated in-flight crash job updated to `UNCERTAIN` (`CONTROL_PLANE_RESTARTED`).
- **Automated test suite**: 114 tests passing on Windows and Debian Linux (including 15 unit/API tests in `test_operations.py` and 2 loopback SSH tests in `test_operations_ssh_loopback.py`). Ruff lint and format check clean across all 54 files; mypy found 0 issues across 37 source files. Clean process and service shutdown verified.

## Previous status: Prometheus + Grafana monitoring pipeline

- Completed SWFW_5S_12 Prometheus + Grafana monitoring milestone on Debian 12 WSL2.
- **Control-plane metrics**: Implemented `GET /metrics` text exposition endpoint in `fleet_manager.metrics` with strict bounded label cardinality (`outcome`, `status`, `reason`, `le`). Arbitrary node names, IPs, credentials, or raw SSH outputs are completely excluded. Exposes `fleet_connectivity_checks_total`, `fleet_connectivity_check_duration_seconds` (histogram with bounded buckets), `fleet_connectivity_active_checks`, `fleet_connectivity_max_concurrent`, `fleet_nodes_by_status` (dynamic collector), `fleet_scheduler_cycles_total`, `fleet_scheduler_checks_skipped_total`, and `fleet_scheduler_running`. Loopback security boundary documented (ADR 0005).
- **Real Linux host metrics**: Official distribution package `prometheus-node-exporter` (v1.5.0-1+b6) installed and running via systemd on port 9100, exposing kernel statistics from `/proc` and `/sys` (CPU, memory, disk, network). No homegrown collector used.
- **Prometheus server**: Official Debian package `prometheus` (v2.42.0+ds-5+deb12u1) installed and running via systemd on port 9090. Configured with file-based service discovery (`targets.json`) scraping Fleet Manager (port 8000) and Node Exporter (port 9100).
- **Grafana provisioning**: Official Grafana OSS 10.4.2 installed and running on port 3000. Automated provisioning configured for Prometheus datasource (UID `prometheus`) and a 9-panel operational dashboard (`fleet-monitoring.json`) rendering real PromQL queries for CPU usage, memory usage, root disk availability, network traffic, scrape targets health, and fleet connectivity states.
- **End-to-end live pipeline verification (`scripts/verify_live_monitoring.py`)**:
  - Registered test node and triggered SSH connectivity check (`HOST_KEY_UNKNOWN`).
  - Scrapes verified: `up{job="fleet-manager"} == 1`, `up{job="node_exporter"} == 1`.
  - PromQL queries verified: `fleet_connectivity_checks_total` incremented, `fleet_nodes_by_status{status="CHECK_ERROR"} == 1.0`, host CPU usage (0.32%), host RAM usage (8.85%), host root disk (953 GiB available).
  - Grafana API verified: Datasource health returns `status: OK, message: "Successfully queried the Prometheus API"`; dashboard provisioned with 9 active panels.
  - Exporter unavailability tested: stopped `prometheus-node-exporter` via systemctl; Prometheus detected `up{job="node_exporter"} == 0` while `up{job="fleet-manager"}` remained `1`; restarted exporter and verified recovery to `1`.
  - Scrape vs SSH probe semantics verified: SSH check failure does not fail HTTP `/metrics` scrape (test covered in `test_prometheus_pipeline.py`).
- **Automated test suite**: 97 tests passing on Windows and Debian Linux (including `test_metrics.py` and `test_prometheus_pipeline.py`). Ruff lint and format check clean across all 40 files; mypy found 0 issues across 27 source files. Clean process and service shutdown verified.

## Previous status: observation freshness + automatic connectivity monitoring

- Completed SWFW_5S_12 observation freshness policy, derived display status endpoint `GET /api/nodes/status`, and periodic automatic monitoring via `ConnectivityScheduler`.
- Configurable observation TTL (default 180s) determines node display states (`NOT_CHECKED`, `REACHABLE`, `UNREACHABLE`, `STALE`, `CHECK_ERROR`) purely from immutable observations and the query clock instant. A stale success is never reported reachable/healthy. Administrative node state remains strictly separated in inventory.
- `ConnectivityScheduler` runs automatic periodic checks across registered nodes utilizing the existing bounded `ProcessSSHExecutor` child-process isolation and identical SSH credentials. Configurable polling interval (default 60s) with modest uniform jitter (+/-10%) prevents synchronized thundering herds.
- Concurrency and backpressure: checks are throttled by `asyncio.Semaphore(max_concurrent)`. When executor capacity is exhausted, `ConnectivityBusy` is handled gracefully without retry storms or unbounded queues, logging structured warnings. Overlapping checks on the same node are excluded.
- Shutdown and process safety: graceful shutdown cancels background scheduler loops and cleans active tasks cleanly. Duplicate scheduling within one instance is rejected (`RuntimeError`). Multi-worker deployments require explicit cross-process coordination (ADR 0004).
- Verification on Windows and Debian 12 WSL2: Ruff lint and format check passed across all 34 files; mypy found 0 issues in 23 source files; pytest passed all 92 tests on both Windows and Debian Linux (including freshness, status API, concurrency, backpressure, duplicate start prevention, and clean shutdown).

## Previous status: bounded per-node SSH checks

- User approved capacity limits, a total elapsed-time budget, duplicate-node exclusion, and shutdown control. The production API now runs each SSH check in a child process with process-local admission (default four), a total deadline (default 12 seconds), and kill/reap on timeout or graceful shutdown. Full capacity returns 429, duplicate active node returns 409, and interrupted checks return 503; these rejections are not persisted as SSH observations. Existing inventory, auth, and successful observation contracts remain intact. See ADR 0003.
- Executing Codex agent on Debian 12 WSL2, 2026-10-27: initial focused test failed because the executor did not exist. After implementation, `uv lock --check` and `uv sync --locked` passed with 38 resolved packages; Ruff lint passed; Ruff format check passed for 29 files; mypy found no issues in 21 source files; full pytest passed 68 tests with one existing Starlette/httpx deprecation warning. The separately run disposable loopback SSH tests passed 2/2. Tests simulate blocked DNS and sequential attempts inside killable child workers; the disposable loopback SSH server verifies the production process path. No managed node or remote command was contacted.
- Evidence limits: bounds and same-node exclusion are per application process; use one Uvicorn worker. Graceful shutdown is covered; abrupt parent termination and OS process creation stalls are not. The shared bearer token is not operator identity or RBAC. Student understanding, native Linux deployment, independent-node failure experiments, and video evidence remain unverified. Existing tracked deletions were preserved.
- Exact next action: student explains why a Python thread timeout cannot stop a blocked DNS call and traces how child termination, process reaping, and the SQLite TIMEOUT observation stay in the right order. Then choose the next small observation-freshness or Prometheus milestone.

## Previous checkpoint: verified SSH connectivity slice

- User approved one-node SSH identity and login verification. `POST /api/nodes/{id}/connectivity-check` checks a registered endpoint with an explicitly trusted host key and configured non-root private key, then stores a UTC outcome separately from inventory. `GET /api/nodes/{id}/connectivity` reads the latest observation. Existing inventory responses and `NOT_CHECKED` registration state remain unchanged. SQLite version 1 inventories migrate transactionally to version 2; no historical inventory database was used.
- Debian 12 WSL2 verification on 2026-10-27: `uv sync --locked` resolved 38 packages; `ruff check src tests` passed; `ruff format --check src tests` passed for 26 files; `mypy src` found no issues in 19 source files; `pytest -q` passed 56 tests with one existing Starlette/httpx deprecation warning. Tests used isolated temporary databases and disposable loopback SSH servers. Successful login, unknown and changed host keys, failed authentication, refusal, timeout and DNS classification, API persistence, and migration were covered. No managed node was contacted and no remote command was executed.
- Security and evidence limits: the shared API token is not operator identity or RBAC. Connection, banner, and authentication phases have five-second timeouts; OS DNS resolution and multiple addresses have no single total deadline or concurrency cap. A disposable in-process SSH server demonstrates local SSH behavior, not a real managed Linux server or independent failure domain. Student understanding has not been independently demonstrated; no video checkpoint was recorded. The three pre-existing tracked deletions remain untouched.
- Exact next action: student explains how a pinned host key differs from client authentication, then traces an unknown-key attempt through transport, service, and observation storage; agree a bounded concurrency and total deadline design before adding scheduling or wider fleet checks.

## Previous checkpoint: architecture cleanup and Debian WSL2 verification

- User approved feature-oriented cleanup and Linux runtime verification. Production code now has `main.py` for lifecycle/error mapping, `config.py` for validated settings, `inventory/` for HTTP schema/router and framework-independent domain/service/SQLite repository, and `security/auth.py` for the bearer boundary. `/api/nodes`, OpenAPI auth, error responses, and SQLite version 1 schema remain unchanged. Essential dependency direction is recorded in `fleet-manager/AGENTS.md`.
- Before the refactor, 31 tests passed on Windows. After it, Windows Ruff lint and format checks passed for 16 files, mypy found no issues in 12 source files, and pytest passed 31 tests with one Starlette/httpx deprecation warning. No new product feature was added.
- Inspected both WSL2 environments: Debian 12 had Python 3.11.2 and no uv; Ubuntu 26.04.1 had Python 3.14.4 and no uv, plus a systemd user-session startup warning. Selected Debian. Installed uv 0.13.6 and uv-managed CPython 3.12.16 only under `/home/ash/.local/`, with the project virtual environment at `/home/ash/.local/share/fleet-manager-env`; no system Python or WSL service was modified.
- Debian `uv sync --locked` installed 29 packages in the isolated Linux environment. Ruff lint passed; Ruff format check passed for 16 files; mypy found no issues in 12 source files; pytest passed 31 tests with the same single deprecation warning; module import succeeded. A real Debian Uvicorn loopback smoke check returned missing/invalid auth 401, POST 201, GET 200, and duplicate 409. A second Uvicorn process read the same SQLite record (ID 1) after the first stopped; both processes exited cleanly. The temporary Linux database was deleted by the harness and the ignored harness was removed.
- Evidence limit: this is WSL2 Debian Linux user-space verification, not native Linux deployment or independent node failure testing. No SSH, metrics, remote nodes, or production service was contacted. The student has not yet completed a teach-back. Three pre-existing tracked deletions remain untouched.
- Exact next action: student traces `main.py` → authenticated `inventory/router.py` → service → repository for a successful and duplicate POST, then explains why `config.py` rejects a missing token before SQLite initialization. Agree the next small product slice after that.

## Previous checkpoint: Milestone 1 verification and local inventory access

## Current status: Milestone 1 verification and local inventory access

- User approved live loopback verification and a minimal authentication boundary. The current `/api/nodes` GET and POST routes require one environment-supplied bearer token. Missing, incorrect, malformed, or duplicate Authorization headers return a generic 401 with `WWW-Authenticate: Bearer`. Missing, short, or malformed token configuration fails application startup before storage initialization; format checks cannot prove entropy. This shared token is not operator identity or RBAC; see [ADR 0002](decisions/0002-local-inventory-authentication.md).
- Baseline before authentication: the original 20 tests passed. A real Uvicorn loopback server returned POST 201, GET 200, and duplicate 409 using an isolated SQLite database. After that server stopped, a second server read the same persisted record. An interrupted tool call left that second server running; its record was read, then the orphan was stopped. The later controlled smoke test below verified graceful shutdown of both processes.
- Final automated verification on Windows: 31 pytest tests passed with one Starlette/httpx deprecation warning; Ruff lint and format checks passed for 11 files; mypy found no issues in 7 source files. Tests cover auth success/failure, malformed and duplicate headers, secret absence from responses/OpenAPI/test logs, fail-closed startup, existing inventory behavior, and no application SSH/socket/subprocess execution.
- Real HTTP smoke test used two distinct Uvicorn processes, actual `127.0.0.1` HTTP requests, an in-memory generated token, and an isolated temporary database. Process 1 returned missing auth 401, POST 201, GET 200, duplicate 409, and invalid input 422. After a clean stop, process 2 returned GET 200 with the same node ID and data, then stopped cleanly. The temporary smoke script/database were removed. No managed node, SSH service, remote operation, or external server was contacted.
- Engineering evidence is local Windows evidence only. Linux deployment, TLS, user identity, RBAC, SSH host identity, metrics, availability, and remote actions remain unverified or unimplemented. No video or student teach-back was completed in this session.
- Exact next action: student traces how a missing bearer token is denied before inventory use, explains why the token cannot identify an operator, and then chooses a small next scope such as operator identity/RBAC design before any remote action.

## Previous checkpoint: first production inventory slice

## Status and approval boundary at that checkpoint

- User approved the Python foundation and first production register/list API slice. No later fleet features are approved by this checkpoint.
- Production package: FastAPI `POST /api/nodes` and `GET /api/nodes`, domain validation, service coordination, and versioned SQLite inventory. New records have `NOT_CHECKED` state. No SSH, metrics collection, remote commands, browser UI, authentication, or authorization exists in this slice.
- Verification on Windows: `uv sync --locked` checked 30 packages; `ruff check src tests` passed; `ruff format --check src tests` passed for 9 files; `python -m mypy src` found no issues in 6 source files; `pytest -q` passed 20 tests with one Starlette/httpx deprecation warning; application import printed `Fleet Manager Inventory API`. Tests used temporary SQLite databases. No live server, Linux host, remote node, or Prometheus/Grafana test was run.
- Windows Application Control blocked the prebuilt mypy executable and compiled extension. A source build of locked mypy 2.4.0 with `MYPY_USE_MYPYC=0` and `uv sync --locked --no-binary-package mypy --reinstall-package mypy` succeeded; `python -m mypy src` then passed. This local workaround is documented in the README.
- Three tracked deletions predated this slice and remain untouched: `docs/SWFW_5S_12_FINAL_REPORT.md`, `docs/learn/submission-guide/13-system-architecture-and-submission-guide.md`, and root `package_submission.py`. Historical claims below about these files and complete submission are not current evidence. The learning index no longer links to missing Document 13.
- Learning: prior exercises and student understanding reports are preserved below as historical records. This session did not independently assess a student teach-back. Engineering verification, learning mastery, and video/submission readiness remain separate.
- Exact next action: have the student trace one POST through API, validation, service, SQLite UNIQUE constraint, and response, then explain why a duplicate concurrent request returns 409 and why `NOT_CHECKED` is honest. After that, agree a small authenticated onboarding or inventory-management scope before implementation.

## Historical checkpoint (2026-10-26; superseded as current status)

Author/environment: executing Codex agent, Windows PowerShell in C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5.

## Current work and approval

- Historical claim: Mode COMPLETE for Milestone 5. The referenced Document 13 is currently deleted from the working tree; completion is unverified.
- Milestone 5 Progress:
  1. Document 13 created: 360° system architecture, mandatory SWFW_5S_12 end-to-end Flow Diagram, and first-principles viva defense cheat-sheet.
  2. Technical Report created: `SWFW_5S_12_FINAL_REPORT.md` with complete architecture, requirement-by-requirement verification, failure taxonomy, and setup guides.
  3. Packaging Utility implemented & executed: `package_submission.py` generated `ADARSH_SWFW_5S_12_PROJECT-FILES.zip` (73 clean source files, 342.92 KB, verified SHA-256).
- Historical claim at that date: all four scope requirements were 100% complete and ready for submission. Current source inspection and tests do not support this claim; only the first production inventory API slice is verified.

## Engineering evidence

- `add_node()` returns `cursor.lastrowid` after transaction commit.
- `node_service.py` coordinates validation, sanitization (whitespace stripping), database initialization, and record generation (`id`, `name`, `address`, `ssh_port`, `status='not_checked'`).
- `demo_milestone_01.py` executes 5-step verification: DB init, valid node registration, input gatekeeper rejection (Port 99999), database duplicate rejection (`UNIQUE(address, ssh_port)` constraint violation), and disk persistence verification across queries.
- Clean isolation supported via optional `db_path` parameter, ensuring zero test pollution of default `inventory.db`.

2026-10-16 evidence clarification (Codex, source inspection only): the demo's Step 5 reads via another database connection in the same Python process; it does not verify a process restart. Its success footer is unconditional, so earlier exit-code evidence alone is insufficient. The new guide supplies a separate two-process rehearsal; commands were not executed this session. Existing code and unrelated uncommitted work were preserved.
- Local `.gitignore` verified to exclude `*.db` and `/fleet-manager/recordings/`.

## Learning evidence and uncertainty

- Student demonstrated first-principles understanding of layered architecture: Input Gatekeeper (Python service) vs Database Integrity Guardrail (SQLite engine).
- Key distinction internalized: "Saving a contact != Calling a contact" -> initial state must explicitly be `not_checked`, missing observations are not zero.
- Video demonstration storyboard prepared in simple Hinglish/English covering Problem, Expectation, Live Run, Failure Recovery, and Core Principles.
- 2026-10-16: Expanded storyboard connects Documents 01–06 to the eventual operator workflow. Earlier learning claims above are inherited checkpoint reports, not independently reassessed this session. Expected input rejection is distinguished from remote failure/recovery; broader feature and security gaps remain explicit.

## Video and handoff

- `fleet-manager/recordings/` folder created (protected by `.gitignore`).
- Storyboard and execution instructions provided to student. No video committed or uploaded to Git.
- Recording remains deferred. Resume with the exact next action above after reviewing the draft cautions below.
- Submission constraints: Official window confirmed (2 Nov 2026 10 AM to 5 Nov 2026 5 PM). Single ZIP upload (`NAME_SWFW_5S_12_PROJECT-FILES.zip`) containing report PDF + code. Report PDF requires a mandatory Flow Diagram for SWFW_5S_12, screenshots, and build steps.

## Commit preparation checkpoint ? 2026-10-16

Author/environment: Codex executing in Windows PowerShell, Python 3.14; repository instructions inspected locally. Scope: review and commit existing work in separate clusters; no feature implementation or learning reassessment.

- Observed: all practice Python files parsed; isolated demo produced both expected rejections and no `[FAIL]` output; a separate Python process read the committed registration successfully.
- Observed through in-process ASGI requests in temporary storage: POST 201 (default port), duplicate 409, invalid port 400, missing fields 422, and GET 200 after registration. No live HTTP server or remote host was tested.
- Open bug: GET before the first registration raises SQLite `OperationalError: no such table: nodes`. Address validation, error classification, connection cleanup, and the demo's unconditional footer remain unresolved.
- Connectivity lesson/practice are drafts requiring technical review before implementation. No probe code exists; do not treat their proposed states or exercises as approved engineering design.
- Earlier student mastery and submission-source claims are inherited reports, not independently verified during commit preparation. No recording, upload, or push performed.
- Exact next action: review Document 08's draft cautions with the student before the connection-refused exercise; agree the probe contract before writing `probe_engine.py`.

## Draft lesson commit follow-up ? 2026-10-16

Author/environment: Codex, Windows PowerShell, Python 3.14.6. Authorized scope: prepare and commit existing changes by topic.

- Observed: Document 08 additions grouped into ICMP diagnostics, probe levels/SSH banners, and TCP handshake/failure modes; trailing whitespace removed and staged whitespace checks passed. Documentation only; no runtime or remote-network tests performed.
- Review remains pending: new numerical certainty, zero-risk, identity, firewall-defense, and fixed-latency claims are unverified. Existing draft warning retained; these commits do not approve the probe design or demonstrate student understanding.
- Next action unchanged: review Document 08's draft cautions with the student before the connection-refused exercise, then agree the probe contract before implementation.

## Probe practice commit review - 2026-10-16

Author/environment: Codex executing in Windows PowerShell, Python 3.14.6. Scope: prepare existing practice work and commit separate code, test, and documentation clusters; no feature integration.

- Observed: all three new Python files parsed successfully; the supplied test script passed all three assertions groups with exit code 0. Two local simulated services exercised banner acceptance and non-SSH rejection; the TEST-NET connection timed out on this run. No real SSH daemon, authentication, remote Linux host, or recovery was tested.
- Both probe engine copies are byte-identical and preserved in their existing practice locations. The test imports the connectivity-practice copy. Earlier statements that no probe code exists describe the previous checkpoint only.
- Remaining gaps: fragmented/preamble banner handling, protocol validation, host identity, total deadline, refusal-path coverage, and reliable failure classification. Fixed test ports and the external timeout make the harness environment-dependent. Do not infer host health from the boolean result.
- Student understanding remains unassessed this session. Next action: review these limitations and agree the probe contract before API integration. No recording, upload, or push.


## Grouped commit preparation - 2026-10-18

Author/environment: executing Codex agent, Windows PowerShell. Authorized scope: prepare and commit existing changes in related groups; no feature redesign or learning reassessment.

- Observed: all six inventory-practice Python files parsed successfully. Temporary-database checks passed for empty inventory initialization, trimmed registration, duplicate rejection, lookup, and persistence of synthetic probe results. No remote sockets, live API, browser, background-worker lifecycle, or legacy schema migration were tested.
- Code review limits: background exceptions are swallowed; probes run sequentially followed by a 15-second sleep; cancellation is not awaited. `last_seen` updates on failures as well as successes. Endpoint probe outcomes do not establish host health or identity. These remain practice changes, not production-readiness evidence.
- Lessons 09 and 10 remain drafts requiring technical review. Absolute latency, database throughput, compression, memory-reclamation, and scrape-failure/host-health claims are unverified. Document 11 is referenced but absent. Earlier claims of established foundations are inherited reports, not demonstrated understanding in this session.
- Removed two trailing-whitespace occurrences in database code and converted six Markdown hard breaks to explicit backslashes; staged whitespace checks passed. No recording, upload, push, or feature implementation performed.
- Exact next action: review Document 10's technical claims and the student's MemFree/MemAvailable answer before proceeding to the proposed Document 11; agree any engineering fixes separately.
