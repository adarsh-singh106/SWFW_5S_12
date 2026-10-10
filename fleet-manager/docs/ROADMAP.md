# Working roadmap

Updated 2026-10-09 by Codex. Sequence is proposed, not authorization or a deadline.

| Increment | Engineering acceptance | Learning evidence | Video checkpoint |
| --- | --- | --- | --- |
| Foundation | Minimal docs and safe ignores; preserve original scripts when accessible; record baseline and agent discovery honestly | Explain evidence versus assertions when relevant | Housekeeping: not required |
| First feature: persistent node inventory | Browser creates/lists endpoints; rejects invalid/duplicate entries; survives restart; shows Not checked | Trace browser → HTTP → validation → database → response; explain registration versus verification | Optional short working demo after verification |
| Verified onboarding | Approved SSH identity/authentication approach; bounded probe; evidence distinguishes relevant failures | Explain host identity, user authentication, process timeout, and uncertainty | Success plus representative failure |
| Prometheus/Grafana monitoring | Multi-node scrape/storage/dashboard demonstrated; missing/stale observations explicit | Trace metric from Linux through collection/storage/query/display | Real metrics and scrape failure |
| Availability and graceful degradation | Reproducible independent-node failures/recovery; no false zero or unsupported health claims | Defend evidence limits and failure semantics | Failure experiment |
| Controlled operations | Authorized structured operation; bounded execution; audit and outcome verification | Defend privilege, input handling, and failure paths | Safe operation plus failure |
| Integrated workflow | Reproduce onboarding → monitoring → investigation → action → verification against all four requirements | Architecture teach-back and unresolved limitations | Walkthrough and technical deep dive |

Track engineering, learning, and video status separately in LEARNING-STATE.md. Implement one agreed coherent increment; routine supporting work can be batched. Foundation follow-ups must not become a new gate to product work when unrelated to its correctness.
