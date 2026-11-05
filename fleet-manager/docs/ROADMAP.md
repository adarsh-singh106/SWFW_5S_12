# Working roadmap

Updated 2026-10-27 by Codex. Sequence is proposed, not authorization or a deadline.

Reading through [Document 04: input validation](learn/node-inventory/04-input-validation-contract.md) was reported complete by the student (2026-10-13). The current approved engineering slice implemented a register/list API with persistent inventory; student understanding of this production flow has not yet been independently assessed. For current evidence and next action, use [the learning checkpoint](LEARNING-STATE.md).

| Increment | Engineering acceptance | Learning evidence | Video checkpoint |
| --- | --- | --- | --- |
| Foundation | Minimal docs and safe ignores; preserve original scripts when accessible; record baseline and agent discovery honestly | Explain evidence versus assertions when relevant | Housekeeping: not required |
| First feature: persistent node inventory | Register/list API, invalid/duplicate rejection, `NOT_CHECKED`, shared-token enforcement, and persistence across two Uvicorn processes are verified on Windows; browser UI and real operator identity remain pending | Trace authentication → HTTP validation → database → response; explain registration versus verification and concurrent duplicate handling | Optional short API demo; no video evidence yet |
| Verified onboarding | Explicit one-node SSH identity/authentication check and separate observation history verified with a disposable loopback target; real managed-node setup, total DNS deadline, workload bounds, and wider onboarding remain pending | Explain host identity, user authentication, phase timeouts, and uncertainty; student teach-back not yet demonstrated | Success and representative failure tested locally; no video evidence yet |
| Prometheus/Grafana monitoring | Multi-node scrape/storage/dashboard demonstrated; missing/stale observations explicit | Trace metric from Linux through collection/storage/query/display | Real metrics and scrape failure |
| Availability and graceful degradation | Reproducible independent-node failures and automatic recovery within agreed boundaries; bounded automatic retries for safe operations; no false zero or unsupported health claims | Defend evidence limits, retry safety, and recovery semantics | Failure and automatic recovery experiment |
| Controlled operations | Authorized structured operation; bounded execution; audit and outcome verification | Defend privilege, input handling, and failure paths | Safe operation plus failure |
| Integrated workflow | Reproduce onboarding → monitoring → investigation → action → verification against all four requirements; demonstrate on three independent nodes under the reported scope; record reproducible workload, latency, resource use, and recovery measurements with limits | Architecture teach-back, workload assumptions, and unresolved limitations | Walkthrough and technical deep dive |

Track engineering, learning, and video status separately in LEARNING-STATE.md. Implement one agreed coherent increment; routine supporting work can be batched. Foundation follow-ups must not become a new gate to product work when unrelated to its correctness.

The [charter](PROJECT-CHARTER.md) preserves the reported instructor feedback and unresolved wording. Agree concrete recovery and workload acceptance criteria before implementing those increments. Beyond the acceptance baseline, prioritize useful operator workflows with measured engineering depth; expand scope when needs and evidence justify it. This direction does not approve a stack, larger-fleet claims, or additional implementation.
