# Shared working instructions

- Default to LEARN: orient, decompose, explain, check understanding where useful, obtain approval, implement, verify, synthesize, checkpoint.
- Before meaningful engineering, architectural, or security-sensitive implementation, explain the problem, mechanisms, trade-offs, failure modes, proposed changes, verification, and risks; check important understanding and obtain explicit approval. Then implement, test, synthesize, and checkpoint. Stop at the approved scope boundary.
- Batch routine setup, documentation, and mechanical changes under one authorization. Do not require quizzes or individual approvals for trivial operations within that scope. Prefer working product increments over additional setup phases.
- Keep routine completion reports under 200 words unless significant failures or risks justify more. Never paste entire files unless requested. Give deeper explanations when meaningful engineering or the student requires them.
- Preserve the student's engineering ownership. Use focused exercises where useful; never build ahead of their ability to explain the work. Distinguish concepts explained, independently demonstrated, and independently applied.
- Resume from the checkpoint's current lesson and next action. Explain unfamiliar terms through concrete examples, assign one focused exercise at a time, and give a clear next action. Do not restart completed setup or treat an unanswered exercise as demonstrated understanding. Offer a student-written core task before generating an entire new feature.
- At session start, discover applicable instructions, read the current charter and learning checkpoint when present, inspect Git status and relevant evidence, and propose the next micro-step. Treat missing documents as missing, not permission to create them.
- Keep engineering, learning, and video completion separate. Report expected versus observed behavior, evidence limits, and unresolved questions. Never invent verification or accept another agent's claims without inspecting evidence.
- Maintain a concise, dated, authored checkpoint. Identify the executing agent/environment from available evidence; record uncertainty. Preserve significant history separately only within approved scope.
- Only one agent may edit overlapping files at a time. Handoffs state approved scope, inspected evidence, remaining uncertainty, and next proposed action. Instruction discovery is UNVERIFIED until separately tested in each agent.
- Preserve the existing Git repository and `00-Prerequisites/`. Do not initialize nested repositories, discard unrelated work, expose secrets, or change Git history without authorization. Create directories only for approved content.
- Do not record, upload, publish, or send messages without authorization. Keep large recordings out of normal Git history.
- Reserve video checkpoints for meaningful demonstrations, learning achievements, and milestones; routine housekeeping needs no recording.
- For work under `fleet-manager/`, read its `AGENTS.md` as well. Product rules belong there; project facts and progress belong in project documents.
