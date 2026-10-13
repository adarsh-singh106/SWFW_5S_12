# Working roadmap

Updated 2026-10-13 by Codex. Sequence is proposed, not authorization or a deadline.

Reading through [Document 04: input validation](learn/node-inventory/04-input-validation-contract.md) is complete per the student (2026-10-13). Next: agree the exact port contract and attempt the focused student-written function. For current approval and evidence status, use [the learning checkpoint](LEARNING-STATE.md).

| Increment | Engineering acceptance | Learning evidence | Video checkpoint |
| --- | --- | --- | --- |
| Foundation | Minimal docs and safe ignores; preserve original scripts when accessible; record baseline and agent discovery honestly | Explain evidence versus assertions when relevant | Housekeeping: not required |
| First feature: persistent node inventory | Browser creates/lists endpoints; rejects invalid/duplicate entries; survives restart; shows Not checked | Trace browser → HTTP → validation → database → response; explain registration versus verification | Optional short working demo after verification |
| Verified onboarding | Minimal documented manual steps; automate agreed configuration; approved SSH identity/authentication approach; bounded probe; evidence distinguishes relevant failures | Explain host identity, user authentication, process timeout, and uncertainty | Success plus representative failure |
| Prometheus/Grafana monitoring | Multi-node scrape/storage/dashboard demonstrated; missing/stale observations explicit | Trace metric from Linux through collection/storage/query/display | Real metrics and scrape failure |
| Availability and graceful degradation | Reproducible independent-node failures and automatic recovery within agreed boundaries; bounded automatic retries for safe operations; no false zero or unsupported health claims | Defend evidence limits, retry safety, and recovery semantics | Failure and automatic recovery experiment |
| Controlled operations | Authorized structured operation; bounded execution; audit and outcome verification | Defend privilege, input handling, and failure paths | Safe operation plus failure |
| Integrated workflow | Reproduce onboarding → monitoring → investigation → action → verification against all four requirements; demonstrate on three independent nodes under the reported scope; record reproducible workload, latency, resource use, and recovery measurements with limits | Architecture teach-back, workload assumptions, and unresolved limitations | Walkthrough and technical deep dive |

Track engineering, learning, and video status separately in LEARNING-STATE.md. Implement one agreed coherent increment; routine supporting work can be batched. Foundation follow-ups must not become a new gate to product work when unrelated to its correctness.

The [charter](PROJECT-CHARTER.md) preserves the reported instructor feedback and unresolved wording. Agree concrete recovery and workload acceptance criteria before implementing those increments. Beyond the acceptance baseline, prioritize useful operator workflows with measured engineering depth; expand scope when needs and evidence justify it. This direction does not approve a stack, larger-fleet claims, or additional implementation.
