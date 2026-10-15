# Current learning and engineering checkpoint

Date: 2026-10-15
Author/environment: executing Codex agent, Windows PowerShell in C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5.

## Current work and approval

- Mode: LEARN. Current topic: [Document 06](learn/node-inventory/06-service-layer-integration.md) and [Practice 03](learn/node-inventory/practice/practice-03-service-layer.md), service integration.
- Student authorized review and separate commits by cluster: storage practice, service lesson/exercise, and curriculum navigation/checkpoint. This does not authorize implementing the proposed service.
- Exact next action: explain why `add_node()` cannot currently provide the proposed response ID; agree storage return/error/cleanup contracts before writing `node_service.py`.

## Engineering evidence

- Existing `practice/db_storage.py` provides schema initialization, parameterized insertion, and list retrieval. Student implementation was preserved unchanged.
- Codex tested a temporary database using separate Python processes: repeated initialization, initially empty inventory, quoted-name insertion, duplicate rejection without another row, and persisted retrieval with `not_checked` status passed. Existing local `inventory.db` was not used or modified and is now ignored with SQLite companion files.
- Reproduced gaps: `add_node()` returns `None`; a NOT NULL violation is incorrectly reported as duplicate. Connection context managers do not close connections; explicit cleanup remains needed. Schema/normalization limits remain documented. Concurrency and power-loss recovery were not tested.
- Earlier validator checks passed 15 core cases but left five strict-policy gaps: whitespace, plus signs, underscores, Unicode decimal digits, and bytes. No new validator changes or rerun in this session.
- No `node_service.py` or web application exists. Application framework/runtime decisions remain unapproved. Practice SQLite use is not approval of the final application stack.

## Learning evidence and uncertainty

- Inherited Antigravity notes report that the student explained whitespace normalization. Original response was unavailable; not independently verified here. Trimming prevents some textual variations, not every duplicate or invalid endpoint.
- Reviewed Practice 02's production-readiness claims and corrected transaction/connection explanations. Document 06 and Practice 03 are proposals with unresolved contracts, not completed learning or implementation.
- Current documentation links and staged whitespace are checked during commit preparation. Earlier checkpoints remain in Git history.

## Video and handoff

- No recording, upload, publication, or push. No service runtime demonstration.
- Resume with the single next action above. Project unknowns remain in [the charter](PROJECT-CHARTER.md).
