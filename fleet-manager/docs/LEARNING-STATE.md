# Current learning and engineering checkpoint

Date: 2026-10-12
Author/environment: executing Codex agent (session identity; runtime CODEX_VERSION=0.158.0), Windows PowerShell 5.1.26100.9444. Editor launch path is unverified.

## Current work and approval

- Mode: LEARN. Current feature: persistent node inventory, beginning with the registration flow.
- User approved organizing documentation by purpose/topic and preparing the first lesson. Documentation work is complete; application implementation, dependencies, and technology choices remain unapproved.
- Next action: read [registration flow](learn/node-inventory/01-registration-flow.md), then answer its section 7 scenario or identify the unclear step. Next proposed coding unit is SSH-port validation after agreeing its contract and implementation scope.

## Engineering state

- Starting Git state: clean main at 321b203. Application src/ and tests/ contain placeholders; no application capability has been implemented.
- Added documentation map, node-inventory guide, registration-flow lesson, and separate references page; updated application README navigation and this snapshot.
- Continuity review: shared instructions now require resuming the current lesson with concrete explanations and a focused student task; nested instructions link to the charter/checkpoint/documentation map/roadmap. Roadmap points to lesson 01. User authorized separate local commits for coherent file groups; separate checkouts need the corresponding changes before resuming. Publishing/pushing is not authorized.
- Documentation validation: initial lesson work passed prerequisite path/SHA-256 comparison. The subsequent continuity review passed the cumulative nine-file scope check, 31 local links, whitespace/diff checks, and prerequisite comparison against HEAD. External lesson references were inspected; no application tests apply to these documentation changes.
- Git currently tracks 19 prerequisite files. Earlier snapshots claimed 18; use the verified count of 19. Earlier checkpoint text remains available in Git at 321b203; its historical test claims are not fresh verification.
- Original WSL scripts remain uninspected/unpreserved. Starting a stopped distribution requires permission; this work did not start WSL or change its configuration.
- Application runtime and independent Linux-node baseline remain pending. Agent instruction discovery: Codex UNVERIFIED; Antigravity UNVERIFIED by separate canary tests.

## Learning state

- Explained in conversation: registration versus observation, persistence, honest save outcomes, and guided incremental implementation.
- New lesson available: participants, HTTP request/response, registration/storage flow, and response uncertainty. Availability does not mean the student has read or understood it.
- Independently demonstrated/applied for this feature: none recorded. The student previously found abstract questions unclear; use concrete scenarios, one focused exercise at a time.
- Deferred technical review: previous lab health labels and timeout claims exceed their evidence. Preserve original prerequisite material and carry corrections into application design.

## Video state

- Documentation/lesson preparation: Not required; no new runtime demonstration.
- First working inventory demo: assess after implementation and verification; no recording or publication performed here.

## Decisions and constraints

- Prometheus/Grafana remain mandatory. Proposed FastAPI/SQLite/plain browser page choices are not accepted decisions.
- ADR, architecture, and evidence directories will be created only when actual decisions or results justify them; conventions are in [the documentation map](README.md).
- Unknowns remain in [the charter](PROJECT-CHARTER.md). Source preservation and agent discovery follow-ups do not block this lesson.
