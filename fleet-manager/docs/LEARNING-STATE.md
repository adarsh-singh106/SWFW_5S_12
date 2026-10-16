# Current learning and engineering checkpoint

Date: 2026-10-16
Author/environment: executing Codex agent, Windows PowerShell in C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5.

## Current work and approval

- Mode: LEARN. Topic: [Document 08: Linux Connectivity Probing & The SSH Handshake](learn/connectivity-probing/08-linux-probing-and-handshakes.md).
- Video recording deferred by student to design their own preferred demonstration format later. Learning resumed immediately with Document 07.
- Practice 04 completed: Student wrote and tested `app.py` with FastAPI, verified `POST /api/nodes` (201/400/409) and `GET /api/nodes`, and independently identified IPv4 octet bounds gap (`192.12.36.788`).
- Exact next action: Student reviews Document 08, checks understanding on the network failure scenario (Connection Refused vs Timeout), and proceeds to Practice 05 (`probe_engine.py`).

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
