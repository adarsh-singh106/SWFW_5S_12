# Prerequisite syllabus: Distributed Linux Fleet Management

Created: 2026-09-26. [Back to current learning index](../README.md).

**Timeline update:** you confirmed a 14-day target on learning day 4. See the [active checkpoints](../LEARNING-PLAN.md#14-day-target). Optional syllabus breadth can continue during project work; the target is one remote observation, not exhaustive mastery.

This is the detailed reference map you requested. It lives in `archive/` for reference; current progress and the next available lab live in the index. Earlier archived discussions are historical, not extra assignments.

**Destination:** explain how a command runs on a Linux machine, diagnose basic access/process/network failures, and collect one meaningful observation from another machine. Then start the Fleet Manager and learn deeper topics as its requirements demand them.

## 1. How to use this syllabus

- Modules are topics, not days or fixed-size lessons. Each becomes several small experiments when needed.
- Low-energy session option: 10 minutes including recall and recording. This is not a maximum lesson length. Two-minute recall-only sessions and complete rest days are allowed. No catch-up debt.
- Longer sessions are welcome when useful, with breaks. First-time explanations must remain self-contained; split a lesson across sessions instead of omitting the mechanism to fit a timer. This does not increase tomorrow's minimum.
- Read the explanation needed for one experiment, predict its result, run it, and explain the evidence. Don't read every module before beginning.
- Ask for a hint when stuck. Repeat a changed example after correcting a misconception; don't restart the whole course.
- A command list below is a set of tools to encounter, not a memorization exam. Looking up syntax is fine; you should understand what the command is meant to do.
- No fixed completion-date promise: use actual progress and the project deadline to decide scope. Ten-minute sessions are a sustainable starting policy, not proof that the full project will fit the available time.

## 2. Starting point and boundaries

As of this document's creation:

| Area | Evidence available | Action |
| --- | --- | --- |
| Paths/navigation | Lab 01 completion and recording reported | Revisit through short recall |
| Relative paths/files | Lab 02 completion reported; explanation checked in chat | Use in later experiments |
| Regular-file permissions | Lab 03 completion reported; output/recall not yet reviewed | Brief recall, then directory permissions |
| Python, HTTP, database CRUD | Prior self-assessment indicates usable familiarity | Patch gaps while building; no full prerequisite course |
| Git | Basic familiarity reported | Practice small diffs/commits with actual project changes |
| Processes, services, networking, SSH, metrics | Earlier diagnostic found gaps | Investigate with the modules below |

Reported completion is not the same as independently checked output. We can keep moving while collecting small pieces of evidence; no need to submit every recording.

The core path is:

**Files and shell → users/permissions → processes → services/logs → network endpoints → SSH → one remote observation.**

Environment setup supports this path. Python, HTTP, and Git are supporting skills, not separate courses blocking it.

## 3. Environment orientation — as needed

**First question:** which machine, operating system, user, and shell are executing my command?

Learn:

- Host versus guest; Windows terminal versus Linux shell; local versus remote execution.
- What your chosen Linux environment is: WSL, VM, or a Linux installation.
- Home directory versus a mounted Windows filesystem; why an experiment's environment matters.
- One Linux machine first. Add a second distinct Linux node when reaching SSH. Two terminal tabs alone are not two nodes.

**Experiment:** identify your environment, username, hostname, and working directory. Later repeat this on the remote node and compare.

**Evidence:** a small sketch of your actual setup, with local and remote machines clearly labeled. Use observations, not assumed IPs or usernames.

**Recall:** when you open another terminal tab, what has changed, and what has not?

**Defer:** cloud accounts, complex virtual networks, and three-to-five-node topology until the project needs them. Service labs require a suitable service manager; check the environment before applying systemd-specific steps.

## 4. Module A — filesystem, paths, and the shell

**First question:** how does a command locate a file, and where does its output go?

Learn:

- Files, directories, filesystem root, home, current working directory.
- Absolute/relative paths and `/`, `~`, `.`, `..`.
- Basic roles of `/home`, `/etc`, `/var`, `/tmp`, `/usr`, `/dev`, and `/proc`; learn one relevant example for each rather than memorizing a tree.
- Create, inspect, copy, and rename practice files. Distinguish moving a file from changing the shell's directory.
- Arguments, spaces, and basic quoting; a filename with spaces should remain one argument.
- Standard input, standard output, and standard error; overwrite versus append redirection; one simple pipe.
- Exit status as a program's reported success/failure signal, separate from printed output.

Tools encountered: `pwd`, `cd`, `ls`, `mkdir`, `cat`, `less`, `cp`, `mv`, `printf`, `grep`, `>`, `>>`, `|`, and basic exit-status inspection.

**Experiments:** read one file from two directories; explain a wrong relative path; pass a filename containing spaces; filter a small practice output; compare append and overwrite on disposable content.

**Exit evidence:** reproduce and fix the relative-path failure, and explain where a simple command's output went. Shell features can be introduced across later modules when they are first useful.

**Recall:** does a successful `cd` move a file? Does text printed on screen prove a command succeeded?

Existing lessons: [Lab 01](../labs/01-paths.md), [Lab 02](../labs/02-files-and-paths.md).

## 5. Module B — users and permissions

**First question:** a file exists at the correct path; why might my command still be denied access?

Learn:

- User and group identities; owner, group, and others permission classes.
- Read/write/execute bits for regular files; interpret `ls -l` output.
- Directory permissions separately: listing names, accessing entries, and changing directory entries are different operations.
- Ownership versus permission changes; symbolic `chmod` first. Read common numeric modes only when encountered; no octal drill required before progressing.
- Why root/privileged execution can change the result of an experiment.
- `sudo` as running an authorized command under another identity, not a universal repair operation.
- Difference between a missing file and inaccessible contents; a read-only file does not by itself explain whether its name can be removed from its directory.

Tools encountered: `whoami`, `id`, `ls -l`, `ls -ld`, `chmod`; understand the purpose of `chown` and `sudo` before using them where necessary.

**Experiments:** remove and restore read permission on your own practice file; separately vary directory permissions in a disposable directory and predict listing versus known-file access. Restore permissions after each experiment.

**Exit evidence:** diagnose one file-permission failure and one directory-permission failure as an ordinary user, using identity and permission output.

**Recall:** which permission changed? Why can metadata remain visible when reading contents fails? Why might a privileged retry hide the original problem?

Existing lessons: [Lab 03](../labs/03-file-permissions.md) and [Lab 04: directory permissions](../labs/04-directory-permissions.md).

**Big recording 1:** demonstrate a path failure and a permission failure, explain their different causes, and fix both. Three-to-five minutes total, replacing the small recording that session.

**Defer:** ACL administration, capabilities, SELinux/AppArmor policy, and advanced ownership setups.

## 6. Module C — programs, processes, and signals

**First question:** what changes when a stored program starts running?

Learn:

- Program file versus running process; shell versus Python interpreter versus your script.
- PID, parent PID, user identity, working directory, and process lifetime.
- Foreground/background execution and the relationship to a terminal session.
- CPU use versus waiting; basic memory observations without deep virtual-memory theory.
- Signals as requests/events; ordinary termination versus forced termination.
- Exit status, standard streams, and cleanup when a program stops.

Tools encountered: `ps`, `top`, `sleep`, `kill`, and basic shell job controls only as needed.

**Experiments:** run a small process you understand, find its PID, inspect it from another terminal, terminate only that practice process, and verify its exit. Restart it and compare identity with the earlier run.

**Exit evidence:** explain what ran, how you identified it, what signal you sent, and what observation confirmed termination.

**Recall:** does every process have a network port? Does a familiar program name guarantee the same running process? Does `kill` mean deleting a file?

**Defer:** scheduler internals, detailed process-state edge cases, namespaces, cgroups, and full signal programming. Return to these when debugging creates a need.

## 7. Module D — services and logs

**First question:** how can a program be managed independently of my interactive terminal?

Learn:

- Service versus process; service manager versus its command-line client.
- A minimal systemd unit: what command runs, under which user, and from which directory.
- Start/stop/restart/status; starting now versus enabling at boot.
- Configured restart behavior; do not assume every service restarts automatically.
- Logs as evidence: time, unit, reported error, and relevant surrounding lines.
- Service configuration versus the state actually observed at runtime.

Tools encountered: `systemctl`, `journalctl`, and the process/path tools already learned.

**Experiments:** run a disposable practice service; observe its process and logs; introduce one wrong path or permission; diagnose and restore it. Use a local console and avoid interrupting the service that provides your only remote connection.

**Exit evidence:** show service status plus the log entry explaining one failure. Fix the cause and demonstrate recovery.

**Recall:** does enabled mean running? Does a port keep a process alive? What evidence distinguishes a failed startup from a service you deliberately stopped?

**Big recording 2:** explain the chain from service configuration to process to log evidence, including one failure and recovery.

**Defer:** advanced dependency graphs, custom targets, socket activation, and detailed hardening policies.

## 8. Module E — networking and endpoints

**First question:** which machine and application endpoint am I trying to reach?

Learn:

- Network interface, IP address, loopback, local network, and basic routing purpose.
- Port, socket, listener, and established connection; distinguish these from PID.
- Binding to loopback versus an interface/all interfaces; what localhost refers to on each machine.
- TCP as a byte-stream transport; encryption/authentication require additional protocols such as SSH or TLS.
- DNS as name resolution, separate from connecting to the resulting address.
- HTTP request/response over a connection in the simple HTTP service we test.
- Refusal, timeout, name-resolution failure, and application error as different observations, not automatic proof of one root cause.
- A failed probe does not by itself prove that the remote machine is powered off.

Tools encountered: `ip addr`, `ip route`, `ss`, `curl`, and `ping` with its limits explained.

**Experiments:** inspect a practice listener; request it locally; compare a wrong port with the correct one; stop the practice server and observe the error. Then access it from a second node and investigate the bind address if remote access fails.

**Exit evidence:** sketch client → destination IP/port → listener/process, and use listener inspection plus connection output to investigate one failure.

**Recall:** can SSH work while another service on the same host fails? What does localhost mean from the remote node? What does a timeout tell you, and what does it leave unknown?

**Defer:** subnetting drills, dynamic routing protocols, packet-analysis mastery, firewall administration, and performance tuning. Introduce the minimum needed for your actual lab network.

## 9. Module F — SSH and remote execution basics

**First question:** how does my local command cause work on another machine and return the result?

Learn:

- SSH client, SSH server, remote user, remote process, and returned output.
- Server identity/host-key verification versus user authentication.
- Public/private key roles; private key stays private; recognize key-file permission problems.
- Interactive session versus a single remote command.
- Remote working directory and environment; distinguish local shell interpretation from remote interpretation in simple commands.
- stdout, stderr, exit status, authentication failure, connection failure, and timeout handling.

Tools encountered: `ssh`, the key-generation tools needed by the chosen setup, and remote `hostname`, `whoami`, and `pwd`.

**Experiments:** connect to a second Linux node; identify the machine and user; run one harmless command without an interactive shell; capture a successful result and an unsuccessful result. Verify host identity instead of suppressing host-key checks.

**Exit evidence:** explain which machine executed the command, how authentication differs from reaching the server, and what information returned to the client.

**Recall:** if a response is lost, do you necessarily know that the command never ran? Which machine's filesystem does a remote path refer to?

**Defer:** fleet-wide command execution, arbitrary shell input, automatic retries of changing operations, bastions, and certificate-based SSH infrastructure.

## 10. Module G — Linux observations and one remote metric

**First question:** where did this number come from, and what can it actually tell us?

Learn:

- Kernel versus user-space tools; `/proc` as an interface exposing live system/process information.
- Measurement name, unit, observation time, and target machine.
- A snapshot versus an accumulating value; why some quantities require two observations and elapsed time.
- Choose one initial metric: uptime is a small starting option. Explain its source and units before adding others.
- Missing, stale, and zero are different meanings. A failed read must not silently become a zero value.
- Keep observation separate from diagnosis: one returned number does not prove overall node health.

Tools encountered: `cat`, a small Python parser you write, then SSH to read the same source remotely.

**Experiments:** inspect a raw value locally, predict its change over a short interval, read it again, parse it yourself, then collect it from the second node. Cause one harmless collection failure and preserve the error rather than inventing a measurement.

**Exit evidence:** one real remote observation with source, unit, node identity, collection time, and an explanation of its limits; plus a visible collection-failure result.

**Recall:** is observation time necessarily the exact time the remote value was generated? Does a failed metrics request mean the value is zero? What evidence supports your claim?

**Big recording 3:** local collector → SSH → remote source → returned observation. Show one failure and recovery, and explain what remains unknown.

**Defer until the next project need:** CPU counters and sampling, `MemAvailable` versus `MemFree`, load average versus CPU utilization, disk capacity versus I/O, and detailed process states. Study each metric before displaying or alerting on it; do not require mastery of every metric before building the first collector.

## 11. Supporting skills learned during the experiments

| Skill | Minimum practice | Evidence |
| --- | --- | --- |
| Python | Read/parse output, handle exceptions, inspect subprocess results, use timeouts, keep data separate from shell syntax | Your own small collector; explain both success and failure paths |
| HTTP | Identify request, response status, body, and connection failure | Explain a real `curl` result |
| Git | Inspect status/diff, commit an understood change, recover a practice change without losing unrelated work | A small explainable diff; no daily commit streak |
| Debugging | State observation, propose one hypothesis, change one thing, check outcome | One failing-then-working experiment with the reason |
| Evidence | Record command, context, relevant output, and inference separately | Enough detail to reproduce one result |

No separate Python/backend/database course unless a concrete exercise reveals a gap.

## 12. Recording and recall policy

**Small checkpoint:** 30–60 seconds, notes closed: prediction → observation → explanation → remaining uncertainty. One take, private, no editing. Check the explanation afterward and append a brief correction if needed.

**Big checkpoint:** the three demos identified above, three-to-five minutes each. These replace that session's small recording. Split preparation across sessions if necessary.

**Later recall:** start the next session by answering one old question before opening notes. After a few sessions, revisit an older concept with a changed example. Use the recording to check afterward, not as the first step.

The log remains optional and tiny: last completed step → next action. No transcription, daily score, public-post requirement, or recording backlog. If recording adds friction on a bad day, give a spoken answer and stop.

## 13. When prerequisite mode ends

Begin the first Fleet Manager slice when you can:

1. Identify where a command executes and under which user.
2. Resolve a path and diagnose a basic permission failure.
3. Identify your running process and inspect a practice service's logs.
4. Explain a destination endpoint and investigate a failed connection.
5. Run a harmless command on another Linux node using SSH.
6. Collect and explain one remote observation while representing collection failure honestly.

You may consult command documentation. The gate is explaining and reproducing the behavior, not perfect syntax recall or knowing all Linux internals.

**First project slice:** a small collector you write that retrieves one observation from one remote node and exposes success or failure clearly. Add inventory and more nodes after that works. Short prerequisite patches can continue alongside project work.

Prometheus metric types, scraping, service discovery, Grafana, failure-detector design, command authorization/audit, retries/idempotency, automated tests, and CI belong to the project learning phase. They matter, but they are not all entrance requirements.

Kubernetes, Terraform, cloud architecture, advanced observability internals, and other infrastructure platforms stay out of the core prerequisite syllabus unless the actual project creates a reason for them.

**Next learning step:** [Lab 04: directory permissions](../labs/04-directory-permissions.md). Lab 03 completion was reported; no repeat required. Current progress is maintained in the learning index.
