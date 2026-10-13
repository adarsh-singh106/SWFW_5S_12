# Current learning and engineering checkpoint

Date: 2026-10-13
Author/environment: executing Codex agent, Windows PowerShell in C:/Users/adars/Desktop/ZOHO/SWFW-12-Sem5.

## Current work and approval

- Mode: LEARN. Topic: Feature 1 — Code Practice & Review Organization.
- Student proposed keeping hands-on code practice and reviews in a dedicated `practice/` subfolder with independent numbering and bidirectional linking to parent lessons. Approved and implemented.
- Reorganized student code to `learn/node-inventory/practice/validate_port.py` and review guide to `learn/node-inventory/practice/practice-01-port-review.md`.
- Next action: reconcile the permissive `int()` conversion with Document 04's proposed strict input policy; then proceed to Document 05: persistence, records, and a first save/read exercise.

## Engineering state and review

- Created `learn/node-inventory/practice/` subfolder.
- Moved `validate_port.py` into `practice/`.
- Created `learn/node-inventory/practice/practice-01-port-review.md` (Practice 01 Review) with bidirectional links to `learn/node-inventory/04-input-validation-contract.md` (Parent Document 04).
- Application code and dependencies remain unapproved.

- Student updated `validate_port.py` with `(bool, float)` guard, EAFP parsing, boundary check, and `__main__` entrypoint.
- Inherited session check results (no saved test suite):
  - Valid: `22` -> `22`, `'22'` -> `22`.
  - Rejections: `True`, `False`, `22.5`, `0`, `-5`, `70000`, `'abc'`, `None` all raised expected `ValueError`.
- Codex recheck on 2026-10-13: 15 core cases passed (five valid inputs and ten invalid inputs). Five policy gaps reproduced: whitespace, leading plus, underscores, non-ASCII decimal digits, and bytes are accepted. The first diagnostic hit a console Unicode encoding error; rerunning with ASCII-safe output confirmed all five results.
- Result: basic conversion/range practice works; full strict-contract compliance is not demonstrated. Corrected the practice review: conversion alone is not production-grade, and `isdigit()` does not enforce ASCII-only input. Student implementation behavior preserved.
- Next topic: Document 05 / Database Persistence: records and tables, then parameterized save/read, transactions, and duplicate constraints. SQLite remains a proposed teaching/application choice, not an approved implementation.

## Video and handoff

- No recording, upload, publication, or runtime demonstration performed. Assess a video after a verified working inventory increment.
- Student authorized commit preparation and commit creation. Scope: practice script, its historical review and verified limitations, lesson navigation, and checkpoint. No application feature implementation. Removed trailing whitespace without changing script behavior.
- Resume with the single next action above. Remaining project unknowns are in [the charter](PROJECT-CHARTER.md).
