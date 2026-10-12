# Documentation map

Start each working session with [the current checkpoint](LEARNING-STATE.md), then open the current lesson it names.

| Need | Read |
| --- | --- |
| Project requirements, scope, and unknowns | [Project charter](PROJECT-CHARTER.md) |
| Sequence of working features and acceptance criteria | [Roadmap](ROADMAP.md) |
| Current work, evidence, and exact next action | [Learning state](LEARNING-STATE.md) |
| First feature's explanations and exercises | [Node inventory learning guide](learn/node-inventory/README.md) |
| Recording plans and review expectations | [Video plan](VIDEO-PLAN.md) |

## Where material belongs

- `learn/<topic>/`: guided explanations and practical exercises grouped by a feature, concept, or problem. Start with feature groups; extract shared concept guides only when reuse makes that helpful.
- Each topic's `references.md`: separate official/primary references, community material, and student-supplied material. Link to sources and explain their relevance; keep generated lessons distinct from external material.
- Student-authored notes: create a clearly labelled file inside the relevant topic when there are actual notes. Preserve the student's wording; label any AI feedback separately.
- `decisions/`: create an Architecture Decision Record (ADR) when a consequential decision needs durable reasoning. Include status, context, alternatives, decision, consequences, and related evidence. Proposed is not accepted; a replacement decision should link to the superseded one. ADRs are our decision records, not a second parallel system.
- `architecture/`: create current system/data-flow descriptions when implemented components justify them. Label any proposed parts.
- `evidence/<feature>/`: create reproducible commands, environment details, observed results, and limitations when experiments or implementation produce evidence. Expected output in lessons is not evidence.

The last three directories are conventions, not empty folders to create now. Small choices can stay in the feature guide. Do not add a second tracker for the same information.

## Keeping documents trustworthy

Generated learning guides identify their drafter/date, reference sources, and verification status. Student understanding is tracked separately in LEARNING-STATE.md. Authorship alone does not establish correctness.

Keep one authoritative location for each fact and link to it. Update affected docs with the corresponding engineering change. External reading is optional unless a lesson identifies a necessary section. Prefer source links and attributed summaries over copied articles; do not commit restricted ZohoLearn content.

Keep the checkpoint short; use Git history for earlier snapshots and evidence records for significant experiment results. No extra report is required for every small edit.
