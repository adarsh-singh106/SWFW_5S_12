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

## Lab 06 — simpler language requested

- You asked for the Markdown itself to use easy-to-understand language, after the waiting/start distinction remained unclear.
- Rewrote Lab 06 in conversational Hinglish using the sleep lifecycle: process starts, requests a wait, waits, then gets CPU time to continue and exit.
- Clarified that waiting/stopped/exited are not all possible states; separated ready/running, waiting, stopped, and exited. Moved advanced details below the core experiment.
- Added this writing preference to the learning plan. Lab 06 practical completion is still not reported.

## Language preference corrected

- You clarified that learning documents should stay in English, using easy words and clear explanations.
- Rewrote Lab 06 in simple English and updated the learning plan for future lessons. This replaces the previous Hinglish preference for lesson text.
- Kept the practical steps, explanations, and recall answers. Lab 06 completion is still not reported.

## Lab 06 — completed with evidence and explanation

- Shared output: A shell PID 11; B shell PID 15; sleep PID 17, PPID 11, user ash.
- Verified sequence: S+ initially, T after STOP, S with the same PID after CONT, no process row after TERM.
- User correctly explained pause versus waiting, same-process continuation, and termination. Clarified that STOP suspends execution without freezing elapsed time, and TERM ends the process rather than deleting the executable.
- The + suffix initially indicated membership in the terminal's foreground process group; its absence after CONT is consistent with resuming without putting the job back in the foreground.
- Next: ask for `ps -p 1 -o pid,comm,args` in the user's Linux terminal to identify its init process before designing the services/logs lab. WSL versus VM remains unconfirmed. Lab 06 recording has not been reviewed.

## Lab 07 — ready, with an environment check

- You requested moving on. Added the services/logs lesson in simple English, starting with why a service manager is useful.
- The user's PID 1 and service-manager availability are still unknown. The lesson checks both before selecting the systemd path; no setup changes are assumed.
- Next: read sections 1–2, then share the section 3 results. If systemd is available, continue the read-only status/log observations.
- Lab 07 is not complete yet. Creating and debugging a disposable practice service remains the following milestone.

## Lab 07 — WSL environment identified

- User output confirms Debian on WSL 2, WSL version 2.7.11.0, and PID 1 init(Debian) running /init. systemctl resolves to /usr/bin/systemctl.
- systemd is not currently the system manager at PID 1. Checked Microsoft's official systemd setup documentation; the reported WSL version supports it.
- Added section 3A to Lab 07. Next user action: inspect /etc/wsl.conf and package status for systemd and systemd-sysv before changing configuration.
- No packages installed, system settings edited, or WSL restart performed by the assistant. Service inspection remains pending setup verification.

## Lab 07 — configuration and packages checked

- User output: /etc/wsl.conf does not exist; systemd and systemd-sysv are installed (ii), version 252.39-1~deb12u2.
- Added explained instructions to create the missing config, restart WSL after saving work, and verify PID 1 plus service-manager access.
- No installation is needed for this step. Configuration creation and restart are not yet reported as performed; systemd activation is not yet verified.
- Next user action: exit the package-list pager with q, then follow Lab 07 section 3A.

## Lab 07 — systemd activation verified

- Initial config command was split at /etc/ and failed without creating the file. User reran it on one line; cat confirmed [boot] and systemd=true in /etc/wsl.conf.
- Latest shared output: PID 1, executable name systemd, arguments /sbin/init. systemd activation is verified; the earlier /init result is historical.
- Next: section 4, list running services through systemctl. Status and log observations remain pending; Lab 07 is not yet complete.

## Lab 07 — video support requested

- You said the purpose and concepts of the lesson were difficult to follow and asked for YouTube resources.
- Added two Learn Linux TV links to the lab: systemd/systemctl first, journalctl later. Links and topic coverage were checked against the creator's published pages/descriptions.
- Suggested watching a small portion, then explaining the service manager's purpose before returning to the status experiment. No extra course or mandatory video completion added.
- Lab 07 service/log observations are still pending.

## Lab 07 & Prerequisites Test — completed with distinction

- You reported completing reading and performing Lab 07.
- Prerequisites Check Test completed covering Labs 01 to 07.
- Full test record with user's exact answers and detailed evaluations saved to `00-Prerequisites/labs/test.md`. Score: ~90% (Pass with distinction).
- Key conceptual clarifications noted: Linux permission "first match" rule (no fallback to others for file owner) and `Ctrl+C` sending `SIGINT`.
- Next: Lab 08 on network endpoints, IP addresses, ports, and listeners.

## Lab 08 — completed with audio recall

- User performed Lab 08 commands (`ip addr`, `ss -tlpn`, Python HTTP server on port 8080, and `curl`).
- Verified distinctions: `lo` (127.0.0.1) vs `eth0` network interface.
- Recall questions verified: IP vs port explained using hotel address vs room number; connection refused explained as absence of listening process; `0.0.0.0:8080` explained as accepting connections across all interfaces on port 8080.
- User doubts clarified: dynamic IP behavior of `eth0` under default WSL 2 NAT vs static IPs in production servers; `LISTEN` state and `Recv-Q` / `Send-Q` backlog queues in `ss -tlpn`.
- Full review, checkpoint evaluation, and explicit answers appended directly to `00-Prerequisites/labs/08-network-endpoints.md` in Section 10.
- Next: Lab 09 on SSH client, server, key authentication, and preparing the 2nd node.



