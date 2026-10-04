# Lab 07: Who keeps a service running, and where do its logs go?

[All labs](../README.md) | [Previous: signals](06-signals.md)

Use your Linux terminal on DeathNode. Take the time you need; you can split this lesson into sections. This lesson only inspects your system. The first check will tell us which later commands apply to your setup.

## Optional video support

If the written lesson feels abstract, start with a visual explanation. The purpose of this lesson is to answer: who starts a background program, who manages it after it starts, and where do we look when it fails?

1. [Learn Linux TV: Linux Crash Course — systemd: Using the systemctl command](https://www.youtube.com/watch?v=5JVBpXiYMKo). Start here. The creator's description covers an introduction to systemd and using systemctl to start, stop, restart, and enable units.
2. [Learn Linux TV: journalctl Basics — How to Easily Check Your Linux Logs](https://www.youtube.com/watch?v=0dG3vUYt7Uk). Save this for the logs part. The creator's lesson covers reading journal output and narrowing it to a service.

Watch a few minutes, pause, and explain one idea in your own words. You can replay it if needed. Watching an explanation is useful input; the active part is predicting, explaining, and later trying the relevant step yourself.

For the first video, keep only this question in mind: "In the earlier lab I started sleep myself. What job would a service manager do for me?" You do not need to memorize all commands or finish both videos today.

Then inspect one actual service using this lab's status command. Connect its service name to its Main PID if shown. Installing the video's example applications is not required for this inspection lesson.

These links were selected from the creators' published descriptions and lesson pages, not from a full viewing of the videos. No exact timestamps or durations are assumed.

## 1. Start with the problem

In Lab 05, you started sleep from your shell. In Lab 06, you paused, resumed, and ended a process yourself.

Now imagine a program that should be available without you opening a terminal and starting it every morning. For example, an SSH server must already be listening when another machine tries to connect.

Someone needs to decide:

- Which program should start?
- Under which user should it run?
- Should it start when the machine boots?
- What should happen if it exits?
- Where can we inspect its status and messages?

A **service manager** helps manage these tasks. On many Linux systems, that manager is **systemd**. Your environment may use something else, so we will check first.

A service manager does not guarantee that a program will always work. It follows configuration. Restarting after failure, for example, is a policy that must be configured; it is not automatic for every service.

## 2. Keep these words separate

| Word | Simple meaning |
| --- | --- |
| Program | Instructions stored in a file, such as an executable |
| Process | A running instance of a program, with a PID |
| Service | A task managed as a named unit; it may use one process, several processes, or a short task that exits |
| systemd | The service manager we will use if it is available in this environment |
| Unit | Something systemd manages; a service unit is one kind of unit |
| systemctl | A command you use to ask systemd for information or actions |
| Log | A recorded message about something that happened |
| journalctl | A command for reading messages stored in the systemd journal |

You already know how to inspect a process with ps. A service gives us another useful name to manage, such as `example.service`. That service name can stay the same even when its program restarts with a different PID.

```text
You run systemctl
    -> it asks the service manager for information or an action
    -> the manager tracks the named service
    -> the service may have one or more processes
```

`systemctl` is the tool you talk through. It is not the program doing the service's work.

A system service managed by the system manager does not need your interactive shell to stay open. This is about how the process is managed, not whether it has a network port. Not every service uses networking.

**Quick prediction:** if a service restarts and gets a new process, must the service's name change too? Say your answer before continuing.

Answer: no. Its process can change while the managed service name stays the same.

## 3. Check your actual environment first

Run these one at a time:

```bash
ps -p 1 -o pid,comm,args
command -v systemctl
```

Command details:

- `ps`: show process information.
- `-p 1`: select PID 1, the first process in this Linux process environment.
- `-o`: choose the columns to display.
- `pid`: process ID.
- `comm`: its executable name.
- `args`: its command and arguments.
- `command -v systemctl`: ask the shell where it would find systemctl. This does not start a service.

### Choose the next step from the result

**If PID 1 is systemd and systemctl resolves to a command:** continue to section 4.

**If PID 1 is something else, such as init, or systemctl is missing:** send me both outputs and stop the practical part here. Some WSL and container setups differ from a full Linux system. The name init alone does not tell us exactly which setup you have. We will identify it before changing settings or installing anything.

Finding a systemctl executable is not proof that systemd is running as the system manager. That is why we checked PID 1 as well.

This check counts as useful progress. You do not need to force commands from the next section to work. Sections 4 onward describe the systemd path.

## 3A. Your confirmed setup: Debian on WSL 2

Your shared output shows:

- Distribution: Debian, running under WSL 2.
- WSL version: 2.7.11.0.
- PID 1: `init(Debian)`, command `/init`.
- systemctl exists at `/usr/bin/systemctl`, but systemd is not currently PID 1.

The command is installed; the system manager it talks to has not been started as PID 1. Those are separate facts.

Your WSL version supports systemd. Microsoft documents enabling it through `/etc/wsl.conf` and restarting WSL. For Debian, both `systemd` and `systemd-sysv` packages should be installed. See [Microsoft's systemd setup instructions](https://learn.microsoft.com/en-us/windows/wsl/systemd).

### First inspect, then change

Run these in your Debian terminal:

```bash
cat /etc/wsl.conf
dpkg -l systemd systemd-sysv
```

- `cat` reads the current file. `/etc/wsl.conf` holds settings for this WSL distribution. If it does not exist, share the error; an absent file is useful information too.
- `dpkg` is Debian's package-management tool. Here `-l` lists the status of the two named packages; it installs nothing. A row beginning with `ii` means the package is installed. Share the full output if the codes differ.

### Your results and the setup steps

Your output confirmed that `/etc/wsl.conf` does not exist and both packages have `ii` status. No package installation is needed for this step.

The `(END)` screen is a text viewer called a pager. Press **q** to return to your shell. It is not an error.

We will create a small configuration file, restart WSL, then check whether the change worked. These are instructions for you to run; the assistant has not changed your Linux setup.

**1. In Debian**, create the file:

```bash
printf '[boot]\nsystemd=true\n' | sudo tee /etc/wsl.conf
```

Every part explained:

- `printf` produces the text inside the single quotes. Each `\n` makes a new line.
- `|` is a pipe: it passes that output to the next command as input.
- `sudo` runs the next command with elevated privileges, usually as root. We need that access to create this system configuration file.
- `tee` reads its input, writes it to the named file, and also displays it in the terminal.
- `[boot]` starts the boot-settings section. `systemd=true` asks WSL to use systemd when starting this distribution.

If sudo asks for a password, enter your Linux user's password. No characters normally appear while you type it. Stop and share any error rather than continuing to the restart.

This command would overwrite an existing file. It is appropriate here because your check showed that the file is absent. If you created settings after that check, inspect the file and merge the setting instead of overwriting it.

Read the file back:

```bash
cat /etc/wsl.conf
```

Expected:

```ini
[boot]
systemd=true
```

**2. Save any work in WSL. In Windows PowerShell**, run one line at a time:

```powershell
wsl --shutdown
wsl -d Debian
```

`--shutdown` stops all running WSL distributions and their Linux processes. Your Debian terminal sessions will end. It does not delete your Linux files. `-d Debian` selects and opens Debian again. See [Microsoft's WSL command reference](https://learn.microsoft.com/en-us/windows/wsl/basic-commands).

Opening another terminal tab alone is not this restart. The next Debian start is what loads the boot setting.

**3. In the reopened Debian shell**, verify:

```bash
ps -p 1 -o pid,comm,args
systemctl list-units --type=service --state=running --no-pager
```

Expected: PID 1 is now systemd, and the second command returns running services instead of a manager-connection error. Send both outputs. If the expected result does not appear, share the exact output; do not assume that writing the file alone completed the setup.

When verified, continue at section 4. The service-list command there is the same one you just used, so you can reuse its output.

## 4. Find a running service

Run only on the systemd path:

```bash
systemctl list-units --type=service --state=running --no-pager
```

| Part | Meaning |
| --- | --- |
| `list-units` | List units currently known to the manager |
| `--type=service` | Show service units |
| `--state=running` | Show units whose state matches running |
| `--no-pager` | Print directly in the terminal instead of opening a scrolling viewer |

This is a filtered list, not a list of every installed service. A service missing from this view could simply be stopped.

Look for `systemd-journald.service`. This service collects messages for the journal on a typical systemd setup. We will inspect it, not stop or restart it.

If that name is absent, or the command reports that it cannot connect to the manager, share the output. We will choose an available service based on your system rather than guess a name.

## 5. Read its status

If that service is present:

```bash
systemctl status systemd-journald.service --no-pager
```

`status` asks about the named service. The service name is an argument, like box was a directory argument in the file labs.

Find these fields; exact wording and layout can vary:

| Field | What to ask yourself |
| --- | --- |
| Loaded | Did systemd find this unit's definition? |
| Active | What state does the manager currently report? |
| Main PID | Which process is identified as the main process, if there is one? |

A **unit definition** describes how the manager should handle a unit. Later, you will write a small one for your own practice program.

If the output includes enabled, that relates to configured activation links, commonly for starting during boot. It does not mean the service is running right now. Active describes current state. A unit marked static is not automatically broken; we will learn that detail when we need it.

Also, active does not prove that every feature of an application works. It is one observation from the manager. Some service types can be active after their initial task has exited, so do not assume every active service must have a live Main PID.

**Small task:** copy the Active line and Main PID, if shown. Explain which is a service state and which identifies a process.

## 6. Read a few logs

First predict: does a status line tell us everything that happened earlier?

Now run:

```bash
journalctl -u systemd-journald.service -b -n 10 --no-pager
```

| Part | Meaning |
| --- | --- |
| `journalctl` | Read messages from the journal |
| `-u systemd-journald.service` | Select entries associated with this unit |
| `-b` | Select entries from the current boot |
| `-n 10` | Show up to ten of the most recent matching entries |
| `--no-pager` | Print directly in the terminal |

The unit filter shows entries about this service. It does not show every message from every other application that journald has collected.

Choose one understandable line. Identify its time, the event it describes, and anything you cannot yet explain. A line reporting that something started is evidence of that event; it is not proof that the service remained healthy forever afterward.

If you see No entries, that means no matching entries were shown. Possible reasons include no records for that filter, removed older records, or limited access. It does not prove that nothing happened.

If the command says you cannot see some messages, share that notice. We will explain the access requirement before changing permissions or adding sudo. If a message is unclear, paste it; you are not expected to know every system message already.

## 7. What you should understand from this lesson

Try these without notes:

1. How is systemctl different from the service manager?
2. Why can a service keep its name while its PID changes?
3. Does enabled mean running right now?
4. Why might logs tell us something that a current status line does not?

### Answers: check after trying

1. systemctl is a tool that sends requests. The manager handles the units and their processes.
2. The name identifies the managed service. A PID identifies a particular process, which may be replaced on restart.
3. No. Enabled concerns configured activation; current activity is a separate question.
4. Logs record events over time. A status line mainly summarizes the state observed now.

If you completed the systemd path, record 30–60 seconds explaining one actual status field and one log observation. No need to record a separate video if you only reached the environment check today.

Send back:

```text
PID 1 output:
Location of systemctl:
If the systemd path worked:
  Active line:
  Main PID, if shown:
  One log line, or the exact no-entries/access message:
```

Optional [log bookmark](../SESSION-LOG.md): last step -> next action.

**Next practical step:** create our own small practice service, introduce one harmless startup failure, and use status plus logs to fix it. This inspection lesson alone does not complete that failure-and-recovery milestone. We will use your environment check to make the next instructions fit your machine.



