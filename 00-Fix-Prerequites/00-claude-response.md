# SWFW_5S_12 — Master Prompt, Roadmap, and Burnout Protocol

**Project:** Distributed Linux Fleet Management
**Owner:** Adarsh Singh — B.Tech CSE, GCOE Aurangabad, Semester 5
**Window:** ~7 September to mid-December 2026, 14 weeks
**Planning baseline:** 10–12 focused hours per week `[FILL: your realistic hours in a bad week — every number in §5 scales off this]`
**Exam blackout:** `[FILL: your exam dates + SETU evaluation dates]`

---

## 1. How to use this document

Section 2 is a prompt you paste into a fresh AI session at the start of every work block. It is the only part you need to copy.

Sections 3 through 9 are yours to read once now and revisit at each gate. They are not instructions for the AI — they're the standard you hold yourself to.

The single most important idea in this document: **this project has a copyable half and an uncopyable half, and the copyable half produces all the visible output.** Prometheus, node_exporter, Grafana and pretty dashboards can be assembled in an afternoon from public tutorials with zero comprehension. Failure detection, graceful degradation, and safe remote execution cannot be copied from anywhere — and when they work correctly they look like *nothing happening*.

So the gradient of visible reward points directly away from the valuable work. Every structural decision below exists to fight that gradient.

---

## 2. THE MASTER PROMPT

Paste everything between the lines into a new session before each work block.

---

You are acting as a combination of senior infrastructure engineer, SRE, and technical interviewer. You are mentoring me through a semester-long project. Your job is to make me a better engineer, not to help me finish faster.

**Who I am.** Third-year CSE student, Semester 5, at a state government engineering college in India. Comfortable with Python, JavaScript, SQL, React, FastAPI, PostgreSQL, Docker basics. I have written basic C coursework only and no C++. I have no CI, no test-writing habit, and no load-testing experience in any prior project. I have no competitive-programming record. I over-claim on resumes when unchecked, and I am prone to solving the tooling problem instead of the actual problem.

**The project.** SWFW_5S_12, Distributed Linux Fleet Management, for the Zoho SETU 2026 program. A web-based system that onboards and manages multiple Linux nodes remotely and collects, stores and visualises system metrics using Prometheus and Grafana. The brief states it "prioritises correctness, system design, observability principles, and understanding of Linux internals. UI aesthetics are not a priority." Four requirements: (1) Linux nodes managed and monitored by the Fleet Manager, (2) node onboarding managed by the Fleet Manager, (3) node availability detection and failure-handling for graceful degradation, (4) controlled remote command execution. Phase two in Semester 6 extends the same project with harder work, so every decision I make now must survive being built on.

**What I am optimising for.** Being able to say honestly: give me a problem in this domain and I can reason about it from first principles, design a solution, implement it, debug it, explain it, test it, optimise it, and defend my decisions. Not completion. Not a demo. Defensibility under a fifth follow-up question.

**Rules you must follow.**

1. **Do not write my code.** If I ask for an implementation, ask what I have already tried and where it broke. You may review code I wrote, explain a concept, or describe an approach in prose. You may not hand me a working implementation of a project component.

2. **Naive first, always.** Before I build the good version of anything, make me build the obvious dumb version and measure how it fails. I am not allowed to add hysteresis to a failure detector before I have measured a fixed-timeout detector flapping. The measurement is what teaches the lesson; the sophisticated version without it is cargo cult.

3. **Interrogate me five levels deep.** After I finish any component, question me until I cannot answer. Do not accept my first answer. Do not accept "because that's the standard approach." When I can't answer, stop and tell me to go find out — don't tell me the answer immediately.

4. **Demand evidence, never claims.** I do not advance a gate by telling you something works. I advance by pasting command output, a measurement, a log excerpt, or a failing-then-passing test. If I say "it works," ask what you should paste to prove it.

5. **Police the hour caps.** Prometheus, node_exporter, Grafana and all dashboard work are capped at 30 hours total for the semester. If I am asking dashboard questions after that budget, tell me I am avoiding the hard part and redirect me to requirement 3 or 4. The same applies to any UI polish: the brief says aesthetics don't matter.

6. **Call out over-engineering.** If I'm building a plugin architecture for a thing with one implementation, or reaching for Kubernetes to run three VMs, say so plainly.

7. **Never let me ship code I can't explain.** If I paste AI-generated code, ask me to explain it line by line before it goes in. If I can't, it does not go in. This includes code generated by you.

8. **Correct my factual errors immediately.** If I say something wrong about Linux internals, Prometheus semantics, or distributed systems, stop and correct it with the reason. Do not let it pass to be polite.

9. **Distinguish stuck from avoiding.** If I've been on one bug more than two hours, help me get unstuck directly — Socratic questioning at that point is cruelty, not teaching. But if I'm asking a comfortable question to avoid a hard one, name it.

10. **Never fabricate.** No invented metrics, benchmark numbers, version specifics, or config parameters you aren't sure of. If you don't know, say so and tell me how to check. Mark uncertain claims explicitly rather than stating them smoothly.

11. **Be blunt.** Attack my work, decisions and habits — never me personally. "This design is wrong because X" rather than "you might consider." Don't compliment anything unless you can say precisely why it's good.

**End every session with three things:** what I demonstrably learned, what I still cannot explain, and the single next action.

---

## 3. What "extraordinary" means for this specific project

Here is what nearly everyone in your cohort will build: Prometheus and Grafana installed, node_exporter on three machines, an imported community dashboard, a web page listing nodes, SSH command execution via a form, and a ping-based up/down check.

That is the assignment. It is not extraordinary, and it will not survive interrogation.

Six things separate yours. Every one sits in the uncopyable half.

**A failure detector that adapts, compared against one that doesn't.** Start with a fixed timeout — if no heartbeat in 5 seconds, mark the node down. Then inject 200ms of network jitter with `tc netem` and measure your false-positive rate. It will be embarrassing. Now track the distribution of heartbeat inter-arrival times per node and adapt your threshold to observed behaviour, and measure again. The deliverable is not the adaptive detector. **The deliverable is the two numbers side by side.** Nobody does this. It's a conference talk in miniature.

**Four states, not two.** "Up" and "down" is a lie your system tells you. You need to distinguish a node that is powered off, a node that is reachable but whose exporter has crashed, a node that is alive but wedged — load average 90, disk full, OOM-killing things — and a network partition where the node is fine and you can't see it. Each one calls for a different response. Most implementations collapse all four into "down" and that collapse is the interesting failure.

**Graceful degradation you actually defined.** The brief doesn't define it, which means the definition is yours and you will be asked for it. Decide: when a node is unreachable, do you serve its last known metrics with an explicit staleness age, or refuse to serve them? What happens to a command queued for a node that vanished mid-execution? If four of ten nodes are unreachable, is the fleet degraded or is your monitoring degraded — and how would you tell? Write these answers down as an ADR *before* you implement.

**A remote execution model with real safety.** "Controlled" is doing a lot of work in that requirement. Command allowlisting rather than arbitrary shell. A dry-run mode. Per-node authorisation. An append-only audit log recording who ran what, where, when, and what came back. Idempotency keys so a retried request doesn't execute twice. And an explicit contract for partial failure: three nodes succeeded, one timed out, one refused — what does your API return, and what does the operator see? "How do you stop someone running `rm -rf /` across fifty nodes" is the question you will be asked, and you should have a real answer.

**A chaos harness as a first-class deliverable, not a testing afterthought.** A script that deliberately breaks your fleet: `virsh suspend` a node to simulate a partition, kill the exporter while leaving the node up, fill a disk with `fallocate`, saturate CPU with `stress-ng`, add latency and packet loss with `tc netem`. Run it repeatedly and record what your detector did each time. This harness is where your entire evidence base comes from, and it converts your project from a demo into an experiment.

**Onboarding that is idempotent and resumable.** Register a node, install the exporter, add it to Prometheus service discovery, verify metrics are arriving. Now kill your fleet manager halfway through step three. What state is that node in? Can you re-run onboarding safely? Half-completed distributed operations are the real content of infrastructure engineering and almost no student project touches them.

---

## 4. The Linux internals curriculum

The brief explicitly demands "understanding of Linux internals." This is where most people fail interrogation: they install node_exporter and can't say what a single number means.

You must be able to explain every metric you display, from its source file upward. Do this by reading the raw sources by hand *before* you install any exporter.

**`/proc/loadavg`.** What load average actually measures on Linux — runnable *plus* uninterruptible-sleep processes, which is unlike other Unixes — why a load of 4 on a 4-core box is not necessarily saturation, and why a high load can coexist with idle CPU when processes are blocked on I/O.

**`/proc/stat`.** The CPU time fields: user, nice, system, idle, iowait, irq, softirq, steal. That these are cumulative counters since boot, so a rate requires two samples and a subtraction — which is why Prometheus has `rate()`. What `iowait` really means and why it's widely misread. What `steal` tells you on a VM, which matters because you're running VMs.

**`/proc/meminfo`.** The difference between `MemFree` and `MemAvailable`, why low free memory is usually healthy rather than alarming, what the page cache is doing, and why `Buffers` plus `Cached` is reclaimable. Then the question you'll be asked: which number would you alert on, and why not the other one?

**Disk and I/O.** `/proc/diskstats`, utilisation versus saturation, and why `%util` is misleading on an SSD that services requests in parallel. Queue depth and service time as the numbers that actually matter.

**Process states.** R, S, D, Z, T. Specifically why a process in D state cannot be killed, since that's exactly the "node alive but wedged" case from your four-state model.

**systemd.** Units, targets, `systemctl status` and what it's actually reporting, journald, and how a service that fails to restart differs from one that's flapping.

**Networking, enough of it.** What `tc netem` does to a packet, what `ss -tn` shows you, and what a TCP connection in `SYN-SENT` means when you're diagnosing whether a node is down or filtered.

**The discipline:** write a script in week 0 that reads these files directly and computes five metrics itself. That script is the naive-first version of your entire project, and after writing it you will understand node_exporter instead of merely running it.

---

## 5. The 14-week roadmap

Gates require evidence. You do not pass a gate by believing you passed it.

Every hour figure assumes the 10–12 hour baseline. Scale proportionally when you fill in your real number.

### Week 0 — pre-semester, roughly 11 days available

Three Linux VMs running, reachable over SSH with key auth. Write the hand-rolled metrics collector from §4. Read `/proc/stat`, `/proc/meminfo`, `/proc/loadavg` and explain every field out loud.

**Install nothing else.** No Prometheus, no Grafana, no web framework.

**Gate 0:** paste the output of your collector reading three nodes, and explain what `iowait` means and why `MemAvailable` differs from `MemFree`.

### Weeks 1–2 — the fleet manager skeleton, ~22h

Node inventory in Postgres. A REST API to register, list, and remove a node. A deliberately ugly web page. Reachability check by SSH. This is your existing stack, so it should move fast — that speed is the reason it comes first.

**Gate A:** onboard a node end to end through your own API, with the node appearing in the inventory and reporting reachable. Paste the request and the response.

### Weeks 3–4 — observability, ~26h, HARD CAP

Prometheus, node_exporter on all nodes, Grafana, and the dashboards you need and no more.

The one design decision that matters this fortnight: **your fleet manager must drive Prometheus's target list.** Generate `file_sd` targets from your inventory so that onboarding a node automatically makes it scraped. Do not hand-edit `prometheus.yml`. That coupling is the whole point of requirement 2.

**This is where the project dies if you let it.** When week 4 ends, observability work stops. Total spend 30 hours, cap included. Anything else is a dashboard you don't need.

**Gate B:** add a node through your API and show metrics arriving in Prometheus with no manual config edit. Then explain why Prometheus pulls rather than being pushed to, and what that choice does to your ability to detect a dead node.

### Weeks 5–7 — failure detection, ~34h

Naive first: a fixed-timeout detector. Then the chaos harness v1. Then measure false positives under injected jitter and loss. Then the adaptive detector. Then measure again. Then implement the four-state model.

This is the heart of the project. It will feel slow and produce almost nothing visible, which is precisely why it's valuable.

**Gate C:** a table of detection latency (p50, p95, p99) and false-positive rate for both detectors under at least three injected failure modes. Real numbers from your own harness.

### Weeks 8–10 — controlled remote execution, ~34h

Allowlisted commands, dry-run, per-node authorisation, append-only audit log, idempotency keys, partial-failure semantics, timeout handling.

Treat this as security-sensitive work, because it is. Write down your threat model first: what stops a bad command, what stops a replayed command, what stops an unauthorised one.

**Gate D:** execute a command across five nodes with two deliberately broken, and show the audit log plus whatever your API returns for a partial failure. Then explain your injection defence.

### Week 11 — graceful degradation, ~11h

Implement the ADR you wrote in §3. Staleness markers, queued-command handling, and the distinction between a degraded fleet and degraded monitoring.

**Gate E:** demonstrate the system with 40% of nodes suspended, still serving correct and honestly-labelled information.

### Week 12 — the measurement campaign, ~11h

Run the full chaos suite. Collect every number. Write the report: what you measured, under what conditions, what surprised you, and what you'd do differently. Include the naive-versus-adaptive comparison as the centrepiece.

**Gate F:** the report exists, with real numbers and at least one finding that surprised you.

### Week 13 — hardening and defence, ~11h

README, architecture diagram, ADR set complete, five-minute demo video showing the chaos harness breaking things. Then defence rehearsal: answer the §8 question ladder out loud until you stop hesitating.

### Week 14 — buffer

Deliberately empty. It will not stay empty. `[FILL: move this to wherever your exams actually land.]`

---

## 6. The burnout protocol

Burnout on a solo semester project has specific mechanical causes. Generic advice about breaks doesn't address any of them.

**Cause: yak-shaving with nothing to show.** Three days lost to VM networking before writing project code is demoralising in a way that three days of hard project work isn't.
**Counter:** never be more than two days from a running system. Build vertical slices — a thin end-to-end path first, then deepen it. Never build a complete layer before touching the next one.

**Cause: invisible progress.** A correct failure detector looks like nothing happening. Weeks 5–7 produce almost no demo-able output and that's when people quit.
**Counter:** this is exactly why the public journal exists. Writing down "my detector had a 40% false-positive rate under jitter and here's why" converts invisible work into visible progress. §7 and this section are the same mechanism.

**Cause: the everything-is-broken state.** You changed five things and now nothing works and you can't tell which change did it.
**Counter:** one change at a time when debugging. Commit before each change. `git bisect` exists for this.

**Cause: the perfectionism spiral.** Rewriting the inventory schema for the fourth time because it isn't elegant.
**Counter:** timebox with an escape hatch. If something isn't working after N hours, use the crude version, write a one-line TODO recording the debt, and move on. Debt recorded honestly is fine; debt hidden is not.

**Cause: exam collision.** Non-negotiable and entirely predictable.
**Counter:** plan the blackout in advance. Two weeks of near-zero project hours around exams, scheduled now. A plan that pretends exams won't happen is a plan that breaks in week 9 and takes your morale with it.

**Cause: no feedback loop.** Solo work with nobody checking means small errors compound silently.
**Counter:** the master prompt's interrogation rule, weekly. Plus one commit a day, even a tiny one — the streak is the feedback.

**Two hard rules.**

Take one full day off a week with zero project work. Not the residual day where you feel guilty — a scheduled one. Fourteen weeks at eleven hours is a marathon and unrecovered fatigue makes you slower, not more dedicated.

**The two-week rule:** if you haven't shipped a visible increment in two weeks, stop and re-scope rather than pushing harder. Grinding on a spec you've outgrown is the most common way these projects die, and it always looks like discipline while it's happening.

**Permission to descope, in writing.** If hours run short, cut in this order: UI polish first, then extra dashboards, then the adaptive detector (keep the naive one plus the measurement showing why it's insufficient — that's still a real finding), then the fourth node state. **Never cut:** the chaos harness, the audit log, or the measurement report. Those three are the project's entire value.

---

## 7. Documenting in public, sustainably

Your goal here is legitimate — visible proof of work — but content creation is the easiest thing in the world to let eat your build hours. Constrain it.

**The repo is the primary artifact.** Public from day one. It contains the code, a real README with an architecture diagram, `docs/adr/` holding numbered decision records, and `docs/journal/` holding dated entries. The repo is worth more than every post combined, because interviewers actually open it.

**ADR format** — one per real decision, and write it *before* implementing: context, the decision, the alternatives you rejected and why, the consequences, and a section headed "how I'd know this was wrong." That last section is what distinguishes an engineer from someone following a tutorial. Target eight to twelve ADRs across the semester. Candidates: service discovery mechanism, pull versus push, failure-detector design, the four-state model, command authorisation model, audit log storage, degradation semantics.

**Journal format** — for every bug that costs you more than fifteen minutes: the symptom, your first hypothesis, **why that hypothesis was wrong**, and the actual cause. The third field is the one everybody omits and the only one that becomes an interview answer.

**Posts: one per fortnight, seven total.** Derived from the journal, not written fresh — if the journal is good, a post is thirty minutes of editing.

**Write findings, not progress.** "Why my node-failure detector had a 40% false-positive rate under 200ms of jitter" gets read and remembered. "Week 3 update: set up Prometheus" gets ignored and is also slightly embarrassing in retrospect. Every post should contain a number, a mistake, or a mechanism explained.

**Hard cap: one hour a week average on all public content.** If you exceed it, reduce frequency — never build hours. And a rule that protects you later: **never publish a claim you haven't measured.** You already have a resume habit of over-claiming; a public repo makes that permanent and searchable.

---

## 8. The defensibility ladder

For each of the four requirements, you must survive five levels. Rehearse these out loud in week 13. If you hesitate, that component isn't finished.

**On monitoring:** What does load average measure? → Why isn't it CPU utilisation? → Why does Prometheus pull instead of push? → What does pull do to your ability to detect a dead node versus a dead exporter? → Your scrape interval is N seconds; what's the worst-case age of a number on your dashboard, and how does that interact with your failure-detection threshold?

**On onboarding:** What happens when I register a node? → What if the exporter install fails? → What if your fleet manager dies between step two and step three? → How do you make that resumable? → How do you tell a half-onboarded node from a fully-onboarded unreachable one?

**On failure detection:** How do you know a node is down? → Why that timeout value? → How do you distinguish partition from failure? → What was your false-positive rate before and after adapting the threshold? → What does your detector do when *your own* clock jumps?

**On remote execution:** How do you run a command remotely? → What stops an arbitrary command? → What stops a replayed command? → Three of five nodes succeeded — what does your API return and what should the operator do? → How would you make this safe for fifty nodes and three operators with different permissions?

If any answer is "the tutorial did it that way," that component is unfinished.

---

## 9. What this project is not

It is not a DSA substitute. No amount of this work fixes an absent competitive-programming record, and that record sits *earlier* in the hiring chain than any project conversation. Budget those hours separately and never let the fleet manager borrow against them, however interesting it gets.

It is also not a resume line yet. It becomes one when the measurement report exists. Until then it's a Prometheus install with ambitions.