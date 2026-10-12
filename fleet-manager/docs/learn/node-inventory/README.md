# Learn: persistent node inventory

Drafted by Codex, 2026-10-12. Status: learning/design material; application implementation and technology choices await approval. No runtime results or student mastery are claimed.

[Documentation map](../../README.md) · [Current checkpoint](../../LEARNING-STATE.md) · [References](references.md)

## The working target

Open Fleet Manager, enter a node's name/address/SSH port, and see it listed as **Not checked**. Restart Fleet Manager and find the saved entry still present. Invalid or duplicate input produces an understandable error.

This starts official requirement 1, node onboarding and management, within the web-based multi-node specification. Completing this slice does not complete all onboarding: identity and connectivity verification come later.

## Start here

Read [01: Follow a registration request](01-registration-flow.md). It explains the participants, traces a concrete example, distinguishes registration from observation, and ends with one short exercise and the proposed first coding task.

You do not need to read all project documents or external references first. Stop where the explanation becomes unclear and bring that exact sentence or example to the conversation.

## Route through this feature

| Part | What we will understand and do | State |
| --- | --- | --- |
| Registration flow | Trace input from browser to backend/storage and back; agree on intended behavior | Lesson available; understanding not yet demonstrated |
| Validation | Define allowed inputs; student writes a focused Python validation function | Next proposed coding step; lesson/code not created |
| Persistence | Explain records, parameterized queries, commit, and duplicate handling; save/list records | Pending |
| Browser integration | Connect the page to the backend and handle responses honestly | Pending |
| Verification | Check invalid inputs, duplicates, restart persistence, and relevant failures | Pending implementation |

We will explain each new mechanism before implementing it. Supporting setup can be batched within the agreed scope. Later lessons are written when needed, using the actual decisions and code.

## Evidence we eventually need

- Engineering: actual create/list behavior, invalid/duplicate rejection, restart persistence, and appropriate error handling.
- Learning: your own explanation of the request flow plus an independently implemented change or investigated failure. Reading the guide is not demonstration.
- Video: assess whether a short working demonstration is useful after the slice works; no recording needed for preparing this lesson.

Framework, runtime setup, and the exact storage/validation contract remain proposals. See the [charter](../../PROJECT-CHARTER.md) for current technology status. Do not infer approval from examples in this guide.
