# Node inventory: references and supplied material

Curated by Codex, 2026-10-12. This page records external sources separately from the [AI-drafted lesson](03-registration-flow.md). Reading a source does not demonstrate student understanding or prove application behavior.

## Primary documentation and standards

| Source | Read when needed | Why it is here |
| --- | --- | --- |
| [MDN: Overview of HTTP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Overview) | Components and HTTP messages sections | Reference for browser/server roles, requests, methods, paths, and responses; page inspected 2026-10-12 |
| [MDN: Client-server overview](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Server-side/First_steps/Client-Server_overview) | Basic request/response flow | Supports the web interaction explanation; page inspected 2026-10-12 |
| [RFC 5737: IPv4 Address Blocks Reserved for Documentation](https://www.rfc-editor.org/rfc/rfc5737.html) | Section 3 | Documents the example-only address block containing 192.0.2.10; page inspected 2026-10-12 |

MDN is web-platform reference/teaching documentation, not the normative HTTP standard. The Fleet Manager paths, fields, and initial behavior are project proposals, not requirements imposed by these sources.

## Community material

No community article is required for Document 03. Add material when it helps answer a specific question; record its author, link, relevant claim, and any limitations. Do not treat community claims as approved design decisions.

## Student-supplied material

None supplied for this topic yet. When adding an article, video, or notes, record where it came from and what question it helps answer. Keep substantial personal notes in a separate, clearly authored file in this topic directory; distinguish AI feedback from the student's own explanation.

## Code and runtime verification

No application code or terminal output is presented as verified evidence in Document 03. Request data is illustrative. Database references below support Document 05; framework choice remains pending.

## Review sources for Documents 03-04 (Codex, 2026-10-13)

- [Python built-in functions](https://docs.python.org/3/library/functions.html): `int()` conversion accepts more than the proposed port grammar; `bool` subclasses `int`.
- [OpenSSH ssh manual](https://man.openbsd.org/ssh.1): host authentication and trusted host-key records. Machine metadata is not a replacement for authenticating the SSH server.
- [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html): transaction completion and assumptions about storage behavior; atomicity is not request idempotency.

These references support review corrections, not stack approval or runtime verification.

## Document 05 review sources (Codex, 2026-10-13)

- [Appropriate uses for SQLite](https://www.sqlite.org/whentouse.html): embedded deployment and one writer per database; suitability depends on workload.
- [Python sqlite3 documentation](https://docs.python.org/3/library/sqlite3.html): placeholders, transaction control, and the single-statement `execute()` interface.
- [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html): journaling and filesystem/hardware assumptions behind durability.

No persistence exercise was run during this documentation review.
