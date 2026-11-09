# Final execution report — 9 November 2026

**Status: READY WITH LIMITATIONS** — local manual-testing handoff, not full live acceptance.

Executing environment: Cline coding agent with scoped acceptance, QA and read-only cloud teammates; Windows PowerShell, Python 3.12.8, Node 24.18.0, uv 0.11.32. Working directory: `C:\Users\adars\Desktop\ZOHO\SWFW-12-Sem5\fleet-manager`. Start branch main, HEAD `2326a668db139b852cd837ba55917bba12e396da`, 0 behind / 9 ahead of origin/main. No push, reset, switch, rebase or history change. No local commit created; release changes remain reviewable in working tree.

## Changes and preserved work

- `src/fleet_manager/security/session.py`: reject malformed session cookie grammar before ASCII hashing, preventing unauthenticated malformed-input HTTP 500; auth regression coverage added.
- `scripts/gce_acceptance_test.py`, `tests/test_gce_acceptance.py`: explicit deterministic simulation for 08–13, persistent live-incomplete exit 2 and regression tests; no destructive infrastructure support.
- `scripts/package_source_bundle.py`, `tests/test_final_release_packaging.py`: safer runtime/credential/archive exclusions and no followed symlink traversal.
- `scripts/compile_submission.py`: installed-Chrome PDF generation, mandatory embedded diagram validation, normalized ZIP, required-file checks, private-key-header scan, clean extraction/CRC/hash and extracted-source syntax validation.
- README updated for actual browser auth/native Fleet Health. Submission report, diagrams, selected fixture screenshots, evidence, checklist and final output files added.
- User's existing `docs/LEARNING-STATE.md` is NOT edited, staged or committed. Starting bytes/diff/hash saved under `.local/final-release/20261109T135321/`; final byte comparison is recorded in evidence. No claims about student learning or video completion added to that protected document.

## Fresh QA

See `submission/evidence/qa-summary.md`, the indexed per-command records and acceptance matrix. Initial complete run: 530 Python passed / 7 existing warnings; frontend 74 pass executions (37 unique tests through two compatibility entry points); browsers 126 and 117 assertions, zero unexpected console/network errors and cleanup true. Static checks and cached offline wheel/sdist build passed. **Final post-fix run: 535 passed, 7 warnings, 150.55 seconds; frontend 74 pass executions; browsers 126/117; lint/format/Mypy/offline build all PASS.** Exact final timestamps/commands/exits are in the included QA evidence. One transient browser launch PermissionError was retained; sequential retry passed with cleanup true.

Acceptance runner all 14, `--mock` and `--mock --allow-fault-injection`: exit 2; 2 local passes, 6 skipped, 6 simulated, 0 failed. No skipped/simulated gate counted as live PASS. Exact 14-row matrix is `submission/evidence/acceptance-matrix.md`. Manual tests are all PENDING.

## GCP read-only result and cleanup

Project `project-3682976b-7d4a-465a-933`, zone `asia-south1-a`; existing principal/session inspected. All four initially and finally observed RUNNING, no external IP and no NIC accessConfigs. Initial/final controller internal IP 10.160.0.2, node-a 10.160.0.5, node-b 10.160.0.3, node-c 10.160.0.4. Boot disks retain IDs/attachments and READY control-plane state: controller 20 GiB pd-balanced, nodes 10 GiB pd-standard. Raw local snapshots preserve fields; sanitized submission evidence avoids SSH public keys and credential metadata.

IAP SSH **NOT ATTEMPTED / BLOCKED** on every VM. Effective firewall rules permit observed IAP source to TCP22 with no returned higher-priority deny, but complete effective IAM/access-context proof and independently trusted current host identity were not established; inspected local public identity does not match node-b/c instance authorization. Project grants alone do not prove effective tunnel authorization. Installed stable CLI lacks the requested IAP resource policy read; beta help attempted a bootstrap and failed non-interactively, with no component installation pursued.

No NAT removal/restoration was needed: all four configurations were originally absent and remain absent. No VM power, disk, firewall, IAM, metadata, key, VPC, route, DNS or network-security mutation was performed. Comparison observations are non-atomic, not a guarantee against unrelated concurrent activity. No public IP was allocated by this run. See `submission/evidence/cloud-summary.md` and sanitized snapshot comparison for scope and normalization details.

Deployed API/build identity is UNKNOWN. Local auth/native-health endpoints are not claimed live. Prometheus/exporter/Grafana target samples, service state, scrape errors and actual dashboards were NOT freshly verified. Historical healthy observations and IAP resets are not fresh live evidence. Browser Prometheus is MOCKED. No cloud failure/recovery drill was manufactured.

## Deliverables and verification

- `submission/final/Adarsh_Singh_SWFW_5S_12.pdf`
- `submission/final/Adarsh_Singh_SWFW_5S_12_PROJECT-FILES.zip`
- `submission/Adarsh_Singh_SWFW_5S_12_FINAL_REPORT.md`
- `submission/MANUAL-ACCEPTANCE-CHECKLIST.md`
- `scripts/compile_submission.py`
- `submission/evidence/index.json`, `submission/evidence/qa-summary.md`, `submission/evidence/acceptance-matrix.md`, `submission/evidence/cloud-summary.md`
- `submission/final/SHA256SUMS.txt` and `submission/final/package-manifest.json`

The exact output SHA-256 hashes are deliberately in the adjacent generated SHA256SUMS.txt, not self-embedded in this report inside the hashed ZIP (which would create a circular hash dependency). The external release receipt records the same hashes and PDF/ZIP verification result. Compilation fails on absent mandatory diagrams; both flow and architecture diagrams are embedded in the PDF.

## Limitations and exact next action

READY WITH LIMITATIONS means deliverables and local QA are available, but cloud trust/effective-IAP prerequisites, deployment identity, genuine monitoring and genuine independent-host failure/recovery acceptance remain open. All developer manual checks remain PENDING. The local charter records 2–5 November 2026; 12 November 2026 is unconfirmed. Ask organizers; no extension invented.

Exact first manual command:

```powershell
Set-Location 'C:\Users\adars\Desktop\ZOHO\SWFW-12-Sem5\fleet-manager'
```

Then follow checklist section 1 to enable password authentication, select a new ignored database and run `uv run --no-sync uvicorn fleet_manager.main:app --host 127.0.0.1 --port 8000 --workers 1`. Open **http://127.0.0.1:8000/dashboard**. Do not reuse a screenshot password or bootstrap credential. No further cloud action is implied by this handoff.