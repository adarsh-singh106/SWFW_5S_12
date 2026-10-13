# Project charter

Updated 2026-10-12 by executing Codex agent.

## Official scope (user-supplied paraphrase)

`SWFW_5S_12`: Distributed Linux Fleet Management. Overarching specification: a web-based system managing multiple remote Linux nodes, including VMs or bare-metal machines.

| Enumerated requirement | Planned evidence | Current state |
| --- | --- | --- |
| 1. Node onboarding and management | Register/list nodes; later verify identity and connectivity | Proposed |
| 2. Collect, store, visualize system metrics using Prometheus and Grafana | Real scrape, stored series, Grafana display | Pending |
| 3. Detect availability and handle failures gracefully | Isolated failure/recovery experiments and honest observation states | Pending |
| 4. Controlled remote command execution | Authorized structured operation, audit trail, outcome verification | Pending |

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
- Proposed, not approved: Python/FastAPI plus SQLite for node inventory and a plain browser page. SQLite would store inventory, not monitoring time series.
- Do not add heavy infrastructure without a demonstrated need.

## Known unknowns

Official deadline, submission/demo format, detailed evaluation rubric, weekly time budget, precise node-count constraint, supported Linux distributions, publication/IP restrictions, deployment environment, and additional team members. Ask when an answer affects an upcoming decision.

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
