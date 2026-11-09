# Fresh 14-scenario acceptance matrix — 9 November 2026

Command: `uv run --no-sync python scripts/gce_acceptance_test.py --mock`.
Also verified with `--mock --allow-fault-injection`. Both exit **2**: total 14, PASSED 2, SKIPPED 6, SIMULATED 6, FAILED 0. This is intentionally incomplete acceptance, not a green live gate. Regression tests establish that simulation success never closes live acceptance. `--allow-fault-injection` does not authorize or implement destructive cloud tests.

| ID | Exact scenario | Fresh local result | Unmet genuine/manual requirement |
| --- | --- | --- | --- |
| 01 | Authentication Boundary | PASS local missing/invalid 401, valid 200 | Deployed auth boundary not reverified |
| 02 | Controller-origin SSH Connectivity | SKIPPED | Three actual CONNECTED observations from controller |
| 03 | Inventory Onboarding & Trust | SKIPPED manual | Independent host fingerprint comparison and explicit trust |
| 04 | Availability & Freshness Derivation | SKIPPED | Three fresh real CONNECTED/REACHABLE observations |
| 05 | Controlled Remote Operations | SKIPPED | Nine real successful uptime/memory/disk outputs and matching audit |
| 06 | Prometheus Scrape Pipeline | SKIPPED | Four actual up=1 targets and stored range samples |
| 07 | Grafana Service/Datasource/Dashboard | SKIPPED | Live service/data/dashboard plus genuine rendered panels |
| 08 | Invalid Credentials | SIMULATED | Injected AUTH_FAILED persists as CHECK_ERROR; real SSH rejection pending |
| 09 | Host-Key Mismatch Rejection | SIMULATED | Injected mismatch persists as CHECK_ERROR; genuine transport identity rejection pending |
| 10 | Timeout & Unreachable Node Handling | SIMULATED | Four injected categories; actual bounded deadline measurement pending |
| 11 | Transient Outage Node Recovery | SIMULATED | New manual injected CONNECTED observation; automatic scheduler/live recovery pending |
| 12 | Partial Fleet Failure Resilience | SIMULATED | Three local records, two reachable/one unreachable; independent-host outage/concurrency pending |
| 13 | Controller Crash Reconciliation | SIMULATED | Seeded RUNNING record becomes UNCERTAIN on lifespan restart, terminal record preserved, idempotent; actual process crash pending |
| 14 | Disaster Recovery: Backup & Restore Pre-Flight | PASS local | Empty temporary SQLite integrity/manifest/restore; nonempty deployed recovery pending |

## Scenario 08–13 classification

These were missing harness capability, not established missing product behavior. Deterministic test support now exercises persistence/classification/recovery/reconciliation using injected transports and temporary databases. Existing transport/security tests cover additional boundaries. No VM was stopped, no cloud credential/key changed and no network fault introduced. The live runner still reports these scenarios SKIPPED/NOT IMPLEMENTED because genuine infrastructure fault handling cannot be proven by injection.

Manual procedures: `submission/MANUAL-ACCEPTANCE-CHECKLIST.md` sections 5–8 and 14; `docs/DEPLOYMENT-RUNBOOK.md` section 15. All developer manual tests remain PENDING. Local simulation is useful regression evidence but not equivalent to three independently isolated Linux hosts, real deadlines, real host-key rejection, background scheduling or an actual crash.