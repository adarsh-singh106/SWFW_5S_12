---
name: fleet-manager-browser-qa
description: Automates end-to-end browser quality assurance for Fleet Manager using controlled headless Chrome and disposable test data. Tests authentication, node inventory, host onboarding, operation dispatch, responsive rendering, console errors, and viewport screenshots.
---

# Fleet Manager Browser QA Skill

Automate repeatable, verifiable browser-based end-to-end quality assurance for the Fleet Operations Dashboard without touching live production inventory, SSH hosts, or external networks.

## Core Mandates

1. **Never Claim Visual Verification from String Tests**: HTML parsing, unit tests, and string assertions do not verify layout, styling, responsive breakpoints, or browser interaction. Real visual verification requires driving an actual browser engine and asserting runtime DOM state.
2. **Ephemeral Port & Strict Test Data Isolation**: Run browser QA against an ephemeral, OS-assigned loopback port (`127.0.0.1:0`) with ownership verification (`/__qa/owner`) and disposable SQLite database (`tempfile.TemporaryDirectory()`). Never use a hardcoded port or mutate the user's primary database.
3. **No External Network Dependencies**: The dashboard must render completely offline with zero CDN requests (no external fonts, scripts, or stylesheets).
4. **No URL-Token Authentication**: Do not authenticate via `?token=` query parameters. Authentication must occur via in-memory bearer token entered into the modal form. Stale URL token parameters must be scrubbed automatically.
5. **Clean Multi-Resource Teardown**: Server threads, temporary Chrome profiles, node driver subprocesses, and Chrome browser processes must be tracked and guaranteed to terminate cleanly in `finally` blocks, leaving no stranded processes or temporary database files behind.

---

## Explicit Verification Stages

To ensure reporting integrity, evidence for every stage must be strictly collected and distinguished:

1. **Browser process launched**: Chrome launched with isolated profile, local loopback proxy isolation, and verified remote debugging port (`DevToolsActivePort`).
2. **Page rendered**: Dashboard DOM loaded and initial authentication modal rendered with complete style assets.
3. **Interaction executed**: Real browser events dispatched via Chrome DevTools Protocol (CDP) / Node driver (`Input.insertText`, `click()`, `Input.dispatchKeyEvent`, `Emulation.setDeviceMetricsOverride`).
4. **Interaction assertion passed**: Explicit DOM state polling (`until()`) verified runtime DOM mutations (e.g. table rows updated, modal visibility toggled, error messages displayed, focus trapped).
5. **Screenshot captured**: PNG screenshots written to a unique run-specific output directory under `.local/browser-qa/<run_id>/` (never overwriting prior runs).
6. **Console/network inspection completed**: Browser console exceptions, `console.error` calls, `Log.entryAdded`, and HTTP network failure events captured and filtered for unexpected errors.
7. **Cleanup succeeded**: Ephemeral server stopped, Chrome process killed/waited, and temporary scratch directory unlinked.

---

## Execution Workflow

### Step 1: Run the Automated Browser QA Runner

Execute the complete automated test suite via the project runner:

```powershell
python scripts/run_browser_qa.py
```

Options:
- `--inject-failure`: Injects an early test failure to deterministically verify that all teardown handlers execute and clean up all owned processes and temporary directories even on unexpected error.

### Step 2: Automated Driver Test Sequence (`browser_qa.cjs`)

The driver connects to Chrome via CDP WebSocket and executes the full interaction matrix:
1. **Form Authentication**: Verify initial auth modal, enter invalid token to verify feedback, enter valid token to verify inventory unlock.
2. **Session Locking & Reload**: Click Logout to verify lock, reload page to verify credentials are not restored from history or URL, re-authenticate.
3. **Inventory Search & Filtering**: Type filter query (`beta`) to assert exact row match; toggle status pills (`REACHABLE`, `STALE` zero-result, `ALL`).
4. **Node Selection & Operation History**: Select node to open Operations Console, assert 20-record pagination, paginate forward (5 items) and back.
5. **Guided Onboarding Resume**: Reopen existing pending node, assert copyable POSIX bootstrap snippet format.
6. **Host-Key Scanning & Explicit Trust**: Trigger scan with fake loopback transport, enroll presented fingerprint, assert trust confirmation and state update.
7. **Keyboard Navigation**: Assert modal focus trapping (Tab/Shift-Tab) and Escape dismissal.
8. **Asynchronous Race Protection**: Verify delayed onboarding responses cannot overwrite another selected node's modal state.
9. **API Outage Recovery**: Simulate 503 outage, verify UI marks data stale, simulate recovery, verify refresh succeeds.
10. **Responsive Viewports**: Set device metrics for `1440×900`, `1280×800`, `768×1024`, and `390×844`, asserting that `scrollWidth <= innerWidth` without horizontal page blowout.

### Step 3: Inspect Artifacts

Artifacts are saved in `.local/browser-qa/<run_id>/`:
- `runner.json`: Server ownership, Chrome PID, exit codes, cleanup status.
- `browser.json`: Full report containing list of passed assertions, captured screenshots, console errors, and failed network requests.
- `onboarding-ready.png`: Screenshot of successfully verified onboarding state.
- `dashboard-1440x900.png`: Desktop layout screenshot.
- `dashboard-1280x800.png`: Laptop layout screenshot.
- `dashboard-768x1024.png`: Tablet layout screenshot.
- `dashboard-390x844.png`: Mobile layout screenshot.
