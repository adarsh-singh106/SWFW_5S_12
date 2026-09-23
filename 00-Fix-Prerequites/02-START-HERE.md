# Start here: small experiments, low-energy default

Yeh tumhara working learning plan hai. Earlier two files background discussions hain; daily checklist nahi. Unke daily streaks, fixed study hours, public posts, aur deep interrogation ko compulsory mat samjho.

## Aaj kya karna hai?

Lab 01 aur recording complete karne ki tumhari update mil gayi. Next: [Lab 02: one file, different paths](05-LAB-02-Files-And-Paths.md). Start with its tiny recall check. Detailed lessons one milestone at a time add karenge, actual results ke basis par.

## Session rules

- **Default: 10 minutes total**, including recall and recording. Timer ends toh stop; unfinished experiment next session continue.
- **Almost no energy: 2 minutes.** One old question answer karo, check karo, next action likho. Recording optional in this mode.
- **No energy: rest.** No streak, catch-up debt, or doubled work tomorrow.
- **Extra energy: optional 15–20 minutes.** Extra work tomorrow ka minimum nahi banega.
- Setup/debugging bhi session ka work hai. Agar wahi time le gaya, lesson complete karna compulsory nahi.

Ten minutes is our starting experiment, not a promise that the full project fits this budget. After a few sessions, compare actual progress with the project deadline and adjust scope. Mandatory project requirements stay visible; optional sophistication comes later.

## Har concept ka learning loop

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

Use [the tiny session log](04-SESSION-LOG.md). One entry per session if useful; no score, hours target, or mandatory commit.

Progress means: **I can do this and explain what happened.** If recall is fuzzy, do one changed example with a hint and try again. No need to restart the entire topic.
