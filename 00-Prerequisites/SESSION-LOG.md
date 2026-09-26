# Tiny session log

[Back to all labs](README.md)

This is a resume bookmark: break ke baad kahan se start karna hai? Recording ka transcript nahi. One line is enough: **last step → next step**. Add a confusion only if there is one.

Copy this when useful; short phrases are enough. A recording can carry the explanation, so don't transcribe it here.

```text
Date / lab / last completed step:
Evidence or output (one useful line):
What I can explain / what is still unclear:
Next tiny action:
Recording (optional filename or location):
```

After time away, read only the last entry and resume its next action. No backlog to clear.

## 2026-09-23

- Your update: Lab 01 completed and recording made. Outputs/recording have not been reviewed here.
- Next: Lab 02 recall check, then the practice-file experiment.
- Recording location and any remaining confusion: not shared; no need to fill these unless useful.

## 2026-09-24

- Your update: Lab 02 completed.
- Recall checked in chat: correctly explained that `notes/node.txt` searches for a nested `notes` directory when already inside `notes`; gave `cat node.txt` as a correct fix.
- Clarification: the working directory itself need not be wrong; the relative path must match it. Full form of the other fix: `cat ./node.txt`.
- Next: Lab 03, identify your user and inspect a practice file's permissions. Lab 02 terminal output and recording have not been reviewed here.

## 2026-09-26

- Your update: Lab 03 completed; output, recording, and recall have not been reviewed here.
- Requested a detailed prerequisite syllabus before continuing; added it to `archive/prerequisite-syllabus.md`.
- Next learning action: brief Lab 03 recall, then directory permissions. No new lab started.

## Day 4 — timeline clarification

- You confirmed the 14-day target and requested moving on from completed Lab 03.
- Added checkpoints to the learning plan and Lab 04 on directory permissions; no Lab 03 repeat required.
- Pace: progress made, but day-14 completion is not yet established. Processes, services, networking, SSH, and remote collection remain.
- Next: Lab 04, then processes. Lab 04 completion is not yet reported.

## Lab 04 — first experiment reviewed

- Shared terminal output: ordinary user `ash` (UID 1000), Linux home `/home/ash`, host name `DeathNode`; WSL versus VM not yet established.
- Verified from output: removing owner `x` on `box` caused `cat box/note.txt` to fail; restoring it restored reading. User correctly explained the directory-access requirement.
- `ls -l box` showed the filename with unavailable metadata (`?`), consistent with directory read permission but no owner search permission.
- Remaining evidence: step 4 (remove directory `r` while keeping `x`) was not included in the shared output. Next: predict and run that experiment, then restore permissions.
- Reworded recall questions to use the actual lab rather than unexplained project context.

## Lab 04 — completion update

- You reported Lab 04 complete and asked to save Q2's answer in the same lab for later.
- Added a worked explanation comparing directory listing (`r`) with known-name lookup (`x`), including both experiment cases.
- Q2 understanding remains a revision item; step 4 terminal output and the big recording have not been shared. Do not treat them as independently verified.
- Next topic: processes. No requirement to repeat Lab 04 before moving on; revisit Q2 briefly in a later recall session.

## Lab 05 — ready to start

- You requested moving forward. Added the program/process/PID experiment with each new command option explained.
- Next action: open Lab 05 and locate `sleep` in Terminal A; use another terminal on the same Linux machine to inspect the running process.
- Lab 05 completion is not yet reported. Lab 04 Q2 remains a later recall item, not a blocker.
