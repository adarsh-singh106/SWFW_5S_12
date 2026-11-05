# Project charter

Updated 2026-11-05 by executing Codex agent (Windows PowerShell); local source inspection only, no GCE execution. Official scope and reported instructor feedback below remain as originally recorded; current implementation evidence is in the learning checkpoint.

## Official scope (user-supplied paraphrase)

`SWFW_5S_12`: Distributed Linux Fleet Management. Overarching specification: a web-based system managing multiple remote Linux nodes, including VMs or bare-metal machines.

| Enumerated requirement | Planned evidence | Current state |
| --- | --- | --- |
| 1. Node onboarding and management | Register/list three real nodes; independently verify fingerprints and explicit enrollment | Implemented: inventory API, guided onboarding and browser UI. Actual three-node GCE identity/onboarding evidence PENDING; operator RBAC not implemented |
| 2. Collect, store, visualize system metrics using Prometheus and Grafana | Four expected up=1 targets, stored time-range samples, rendered Grafana panels | Implemented: metrics export, Prometheus configuration, Grafana datasource/dashboard provisioning. Actual GCE scrape/storage/visualization evidence PENDING |
| 3. Detect availability and handle failures gracefully | Fresh observations, isolated outage, bounded failure, unaffected peers and automatic recovery | Implemented: periodic SSH checks, classification/freshness and recovery observation. Actual GCE failure/recovery evidence PENDING; acceptance scenarios 08-13 NOT IMPLEMENTED/SKIPPED |
| 4. Controlled remote command execution | SUCCESS and meaningful output for three read-only actions on each node, matching audit history and catalog rejection | Implemented: allowlisted operations and SQLite audit records. Actual GCE outputs/audit/rejection evidence PENDING |

All four requirements remain **awaiting live acceptance**, not complete. Local tests establish
local contracts, not deployment success. The [runbook section 15](DEPLOYMENT-RUNBOOK.md#15-exact-manual-acceptance-procedures-for-the-four-official-requirements)
defines the manual evidence. The acceptance runner does not silently enroll keys, treat
FAILURE/UNCERTAIN as success, or report unexecuted scenarios as passed.

Correctness, system design, observability, and Linux understanding take priority over aesthetics. No authenticated assignment material is copied here; official publication/IP permissions are unverified.

## Product and learning direction

Zoho's requirements are the acceptance baseline. The broader goal is a flagship portfolio product demonstrating independent software engineering ability through useful operator workflows, defensible decisions, and reproducible evidence. Develop beyond the assignment in validated increments; feature count or additional technologies alone do not establish quality.

**Fleet Manager: Know what's wrong before you act.** Intended users: small Linux teams, homelabs, and college labs. Workflow: onboarding → monitoring → investigation → controlled action → verification.

Explainable failures, evidence-based diagnosis, traceable operations, and reproducible experiments are hypotheses to validate, not extra official requirements. Priorities: P0 official scope; P1 security/correctness/reliability/testing; P2 validated differentiation; P3 optional research.

Success includes independent implementation/debugging/explanation, reproducible evidence, and an authentic technical portfolio. Open-source publication is an objective subject to permission, not a current license decision.

## Decisions and constraints

- Mandatory: Prometheus and Grafana; use Prometheus for time-series storage unless another need is demonstrated.
- Approved organization: one Git repository, application under `fleet-manager/`, prerequisite history preserved.
- Follow shared learning/approval rules and nested security/monitoring constraints. Do not treat WSL distributions sharing a kernel as independent failure domains.
- Approved and implemented for the first inventory API slice: Python 3.12, FastAPI, and SQLite. SQLite stores inventory, not monitoring time series. The browser dashboard is now implemented; the first-slice decision remains recorded in [ADR 0001](decisions/0001-inventory-backend.md).
- Approved local access boundary: a single shared bearer token from the environment, with startup failure when missing; see [ADR 0002](decisions/0002-local-inventory-authentication.md). It is not operator identity or RBAC.
- Approved one-node SSH check: pinned host key, explicit non-root key credential, bounded connection/banner/auth phases, and a separate observation history; see [ADR 0003](decisions/0003-verified-ssh-observations.md). This does not establish overall node health or remote command execution.
- Do not add heavy infrastructure without a demonstrated need.

## Official submission guidelines & timeline (SETU 2026, confirmed 2026-10-15)

Source: Official SETU 2026 project submission guidelines received by the student.

- **Submission Window:** 2 November 2026 (10:00 AM) to 5 November 2026 (5:00 PM).
- **Submission Format:** Single file upload (1 file only, PDF or ZIP).
  - PDF: `<STUDENT_NAME>_SWFW_5S_12.pdf`
  - ZIP (recommended for codebase + report): `<STUDENT_NAME>_SWFW_5S_12_PROJECT-FILES.zip` containing the PDF report and project files.
- **Mandatory Additional Requirement for SWFW_5S_12:** **Flow Diagram** included directly inside the PDF report along with screenshots and build steps.
- **Reporting Rule:** All diagrams, screenshots, build steps must be embedded in the same PDF.

## Known unknowns

Detailed evaluation rubric, weekly time budget, precise node-count constraint (beyond 3-node reported demo), supported Linux distributions, publication/IP restrictions, deployment environment, and additional team members. Ask when an answer affects an upcoming decision.

## Instructor feedback reported by the user (2026-10-12)

Source: the user's pasted session transcript, summary, and account of the instructor's answer. The recording has not been inspected; these are reported clarifications, not independently verified assignment text.

- Onboarding is manual but should require minimal necessary steps, with configuration automated where applicable.
- Automatic retries and automatic recovery are expected. Define their scope and safe retry conditions before implementation; an unknown operation outcome must not imply that repeating it is safe.
- The instructor reportedly permits any language if the student can defend each technology and design choice. Python scripting was explicitly described as acceptable; no application stack is approved by this report.
- The reported demonstration scope is three nodes. Whether this means exactly three, a maximum, or a required test configuration remains unresolved; it does not establish a permanent product limit.
- Configuration was transcribed as automatic via "Command ID". Verify the wording and meaning before designing around it.
- Evaluation emphasis was transcribed as "architecture and volumetric", alongside an industry-standard architectural and product expectation. The exact workload criteria and meaning of "volumetric" remain unresolved.
- Clarify recovery boundaries: restoring observation after connectivity returns, reconciling interrupted work, repairing services, and recovering a failed host are different responsibilities.

Earlier assistant stack lists and architecture sketches remain suggestions, not accepted decisions. The portfolio ambition does not by itself justify a language switch or additional infrastructure.
