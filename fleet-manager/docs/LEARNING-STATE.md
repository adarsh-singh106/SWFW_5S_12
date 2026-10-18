# Current learning and engineering checkpoint

Date: 2026-10-18
Author/environment: executing Codex agent, Windows PowerShell in C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5.

## Current work and approval

- Mode: LEARN. Topic: [Document 10: Linux System Metrics Architecture & Node Exporter](learn/metrics-observability/10-linux-metrics-and-node-exporter.md).
- Entered Milestone 3: Official Requirement 2 — System Metrics Collection & Visualization with Prometheus & Grafana.
- Key foundations established:
  1. Linux `/proc` virtual filesystem architecture (in-RAM dynamic files, zero disk footprint).
  2. Raw CPU ticks (jiffies) delta calculation vs fixed percentages.
  3. Memory truth: `MemFree` vs `MemAvailable` and the Linux disk-cache eviction model.
  4. Mathematics of telemetry scale: why relational SQLite fails under high-frequency writes (86.4M rows/day, lock contention) vs TSDB compressed storage.
  5. Node Exporter daemon architecture (port 9100, `/metrics` endpoint, Prometheus text format).
  6. Pull vs Push backpressure advantages and the fundamental rule: missing metrics $\neq$ 0.
- Exact next action: Student reviews Document 10, answers the check-understanding scenario (`MemFree` vs `MemAvailable`), and proceeds to Document 11 (Prometheus scrape pipeline & Grafana dashboard integration).

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
