# Start here: small experiments, low-energy default

Yeh tumhara working learning plan hai. Earlier discussions `archive/` mein hain; daily checklist nahi. Unke daily streaks, fixed study hours, public posts, aur deep interrogation ko compulsory mat samjho.

## Aaj kya karna hai?

Open the current lab from the [learning index](README.md). This plan is a reference; daily rereading required nahi. Detailed lessons one milestone at a time add karenge, actual results ke basis par.

## Session rules

- **Low-energy option: 10 minutes total**, including recall and recording. You may stop at a safe checkpoint and continue next session. Ten minutes is not a limit on lesson depth or understanding.
- **Almost no energy: 2 minutes.** One old question answer karo, check karo, next action likho. Recording optional in this mode.
- **No energy: rest.** No streak, catch-up debt, or doubled work tomorrow.
- **More energy: continue as useful**, with breaks. No need to fit every lab into ten minutes; extra work tomorrow ka minimum nahi banega.
- Setup/debugging bhi session ka work hai. Agar wahi time le gaya, lesson complete karna compulsory nahi.

Ten minutes is our starting experiment, not a promise that the full project fits this budget. After a few sessions, compare actual progress with the project deadline and adjust scope. Mandatory project requirements stay visible; optional sophistication comes later.

## 14-day target

Your confirmed baseline: **day 4**, Labs 01–03 completed by report. Use your learning-day labels rather than inferring the start date from chat timestamps.

**Finish line:** your own small collector retrieves and explains one observation from another Linux node and reports collection failure honestly. The archived syllabus includes optional breadth; finishing every item is not required before starting the project.

| Day | Target |
| --- | --- |
| 1–3 | Paths, files, file permissions — completed by report |
| 4 | Directory permissions; finish this block |
| 5–6 | Program/process, PID, inspect and stop your own practice process |
| 7 | Practice service, logs, one startup failure |
| 8–9 | IP/port/listener, localhost, connection failure; prepare second Linux node |
| 10–11 | SSH, host verification, key authentication, harmless remote command |
| 12 | Explain one raw local metric and parse it in Python |
| 13 | Collect it remotely and represent collection failure |
| 14 | End-to-end demo, repair gaps, begin project work |

These are targets, not confirmed forecasts. There is little setup buffer. Check the actual Linux environment before choosing service/VM setup. A lab need not equal a day.

Pace checks: **day 7 = service/process evidence; day 11 = remote command; day 14 = remote observation plus failure result.** If one slips, inspect the blocker, cut optional breadth, and get direct setup help. If core work still does not fit, revise the date explicitly; no doubled workload or hidden catch-up debt.

Ten minutes remains the low-energy default, but cannot guarantee the full 14-day outcome. Some tasks need multiple sessions or an optional longer session. Shell extras, additional metrics, numeric permission drills, and deep internals can continue during project work.

## Har concept ka learning loop

**Lesson-writing rule:** assume this is your first encounter. Start with the concrete problem, connect to known concepts, explain the mechanism, and only then introduce commands. Define new terminology and explain every new flag/argument. Show expected observations, why they follow, and useful alternate outcomes. Recall questions must follow from material already explained, not unexplained project context. Provide worked answers for later checking. A longer clear lesson can span several sessions; do not compress away the explanation to meet a timer.

1. **Need:** project ko is concept ki zaroorat kyun hai?
2. **Model:** shortest useful explanation padho.
3. **Predict:** command se pehle expected result bolo.
4. **Try:** small experiment run karo; output dekho.
5. **Explain:** notes band karke prediction aur observation compare karo.
6. **Check:** explanation verify karo; wrong tha toh correction record karo.

Reading is allowed. Reading ke baad kuch predict, do, or explain karna hai. Confusion par hint lo; a tiny lesson ke liye two hours struggle karna required nahi.

## Recording without another workload

**Small milestone:** 30–60 second private audio, one take, no editing:

> Maine kya expect kiya? Actually kya hua? Kyun? Abhi kya unclear hai?

**Big milestone:** 3–5 minute screen demo. Do the task, explain it, show one safe failure and recovery. This replaces that session's small recording.

At the next session, try recall **before** opening notes or replaying audio. Revisit one older question a few sessions later. If an answer is wrong, append a short correction; no polished re-recording needed.

Use any recorder already available. Private local storage is fine; no upload, editing app, or public posting requirement. Don't record passwords or private keys. Recording plus a reproduced experiment is the evidence; audio alone is not a pass.

## Route through prerequisites

These are milestones, not daily deadlines. Each may take several small sessions.

| Order | Question we will investigate | Evidence to move on |
| --- | --- | --- |
| 1. Paths and files | Where will this command look for a file? | Predict navigation and locate a file from a different directory |
| 2. Users and permissions | Who can read, change, or execute this? | Explain and safely fix a permission failure on a practice file |
| 3. Processes and signals | What is actually running? | Find your own practice process, send a signal, explain the result |
| 4. Services and logs | Who starts/restarts a service, and where is its failure recorded? | Diagnose a practice service using status and logs |
| 5. Network endpoints | Which machine and listener am I contacting? | Explain local versus remote access and investigate a failed connection |
| 6. SSH | Where does my command execute? | Run a remote command and explain authentication and returned output |
| 7. One remote metric | What does this number mean, and where did it come from? | Read one Linux metric remotely and explain its meaning and limits |

Big recording milestones: after 2, after 4, and after 7. Small recordings happen at completed experiment checkpoints, not after every command.

Python, HTTP, and CRUD get revisited only when the project exposes a gap. Prometheus and Grafana come after the remote metric experiment.

## Minimum tracking

Use [the tiny session log](SESSION-LOG.md). One entry per session if useful; no score, hours target, or mandatory commit.

Progress means: **I can do this and explain what happened.** If recall is fuzzy, do one changed example with a hint and try again. No need to restart the entire topic.
