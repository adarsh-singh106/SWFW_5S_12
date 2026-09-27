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

## Lab 05 — completed with terminal evidence

- Shell A PID: 38; shell B PID: 43. Observed sleep PIDs: 45, 48, 50, 52; each reported PPID 38 and user ash.
- Shared output shows Ctrl+C interruptions, a short sleep returning naturally, and `/usr/bin/sleep` still resolving after an interruption.
- Extra experiment: shell B ran `kill 52`; shell A reported Terminated. Repeating `kill 52` reported No such process, and the final sleep process listing had no rows.
- Explained distinction: Ctrl+C sends SIGINT to the foreground process group in this setup; plain `kill 52` sends SIGTERM to that PID. Neither deletes the executable.
- Next recall: why could shell B send a signal to a process parented by shell A? Then continue to signals without repeating the completed basic process experiment.
- Lab 05 recording and the user's own conceptual explanation have not been reviewed. Lab 04 Q2 remains a later revision item.

## Lab 06 — ready to start

- You requested moving forward. Added the STOP/CONT/TERM experiment, with new command options and variable syntax explained.
- Explained directly: the same-user setup allowed B to signal A's child; being its parent was not required.
- Next: start a fresh practice sleep, identify its PID, and compare its state after pause, resume, and termination. Lab 06 completion is not yet reported.
- After signals: check service-manager availability before the services/logs lab.

## Learning preference clarified — 2026-09-27

- You explicitly prefer self-explanatory first-principles material and allow lessons to take longer than ten minutes.
- Updated the plan: ten minutes is a low-energy session option, not a content/depth limit; longer lessons may span sessions.
- Expanded Lab 06 with the problem behind signals, kernel delivery, waiting versus stopped versus exited, shell-variable expansion, foreground behavior, and worked recall answers.
- Lab 06 completion is still not reported. Next: read its model, then perform the experiment at your own pace.
