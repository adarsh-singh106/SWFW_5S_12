# Final fresh local QA — 9 November 2026

Author: Cline / QA teammate, Windows PowerShell. Final results after the malformed-cookie fix:

- Python: **535 passed, 7 pre-existing warnings**, 150.55 seconds, exit 0. Warnings: one Starlette/httpx TestClient deprecation and six per-request-cookie deprecations. No warning suppression or dependency changes.
- Frontend: **74 pass executions / 37 unique tests** through two compatibility entry points, exit 0. Node experimental VM module notices retained.
- Browser CDP: normal **126 assertions**, first-run **117 assertions**, both exit 0 and cleanup true, zero unexpected console/network failures. SSH, scans, operations and Prometheus are **MOCKED / DEMO**, not live metrics.
- Ruff lint and format check src/tests/scripts PASS; Mypy strict PASS (50 source files); whitespace check PASS (line-ending warnings retained).
- Offline wheel and sdist build PASS using pre-existing cached hatchling/dependencies via PYTHONPATH, no package installation. Exact path list is included for this workstation; a clean machine uses the locked build-system backend through uv normally.
- Acceptance all 14: exit **2**, **2 local passes / 6 skipped / 6 simulated / 0 failed**. No live gate closed by simulations.
- Focused packaging regressions: 16 pass / 1 existing warning before final full suite; acceptance-specific regression suite 37 pass, related connectivity/freshness 38 pass.

Initial failed invocations retained locally: frontend missing required experimental VM flag; build missing active-env hatchling (resolved through existing cache); a shell-limited partial pytest (not counted). Final normal browser first attempt hit Windows PermissionError reading its owned DevToolsActivePort, before driver launch; cleanup true. Sequential retry passed 126 assertions. No product assertions weakened. Initial full baseline was 530 tests; five malformed-cookie regression variants increased final count to 535.

## Exact final command records

| Check | Start UTC | End UTC | Exit | Exact command |
| --- | --- | --- | --- | --- |
| final_browser | 2026-11-09T08:35:53.5699266Z | 2026-11-09T08:36:02.7095956Z | 1 | `.venv\Scripts\python.exe scripts/run_browser_qa.py` |
| final_browser_retry | 2026-11-09T08:37:07.7901550Z | 2026-11-09T08:37:54.6092679Z | 0 | `.venv\Scripts\python.exe scripts/run_browser_qa.py` |
| final_build | 2026-11-09T08:35:53.5989482Z | 2026-11-09T08:35:56.9118464Z | 0 | `uv build --offline --no-build-isolation --out-dir C:\Users\adars\Desktop\ZOHO\SWFW-12-Sem5\fleet-manager\.local\final-release\20261109T135321\qa-20261109T082946Z\final-dist` |
| final_diff | 2026-11-09T08:35:53.3882812Z | 2026-11-09T08:35:53.8699483Z | 0 | `git diff --check` |
| final_first_run | 2026-11-09T08:35:53.4799411Z | 2026-11-09T08:36:40.7748799Z | 0 | `.venv\Scripts\python.exe scripts/run_browser_qa.py --first-run` |
| final_format | 2026-11-09T08:35:53.4169780Z | 2026-11-09T08:35:53.9147198Z | 0 | `.venv\Scripts\python.exe -m ruff format --check src tests scripts` |
| final_frontend | 2026-11-09T08:35:53.5224959Z | 2026-11-09T08:35:54.7519509Z | 0 | `node --experimental-vm-modules --test tests/dashboard_modules.cjs tests/dashboard_regression.cjs` |
| final_lint | 2026-11-09T08:35:53.3340649Z | 2026-11-09T08:35:53.8895133Z | 0 | `.venv\Scripts\python.exe -m ruff check src tests scripts` |
| final_mypy | 2026-11-09T08:35:53.3480430Z | 2026-11-09T08:35:55.3475913Z | 0 | `.venv\Scripts\python.exe -m mypy src` |
| final_python | 2026-11-09T08:35:53.5244975Z | 2026-11-09T08:38:26.4353531Z | 0 | `.venv\Scripts\python.exe -m pytest -q` |

## Inspection and evidence limits

Reviewed inventory syntax/normalization, strict SSH trust, bounded check/operation execution, availability/freshness, four-action catalog, session/CSRF/origin and fixed-query metrics paths. Confirmed malformed non-ASCII cookie caused request-level 500; fixed by validating generated 43-character URL-safe token grammar before lookup/revocation hashing. Regression verifies protected API 401, intentionally public session status 200/authenticated:false and idempotent logout 200. No auth bypass claimed.

Prometheus response length is validated after HTTPX buffers the body (262144-byte validation limit), not a hard streaming memory cap. The Prometheus URL is trusted operator configuration; hostile-server resource exhaustion was not experimentally tested. Host scan DNS/phase deadlines were not newly live-tested against hostile infrastructure. Single-worker process-local semantics remain mandatory.

No genuine live SSH, exporter, Prometheus, Grafana, independent-host failure/recovery or deployment-identity proof was obtained. No browser fixture is used as live evidence. All developer manual testing remains PENDING.
