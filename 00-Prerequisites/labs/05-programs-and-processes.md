# Lab 05: Program file aur running process mein difference

[All labs](../README.md) | [Previous: directory permissions](04-directory-permissions.md) | [Next: signals](06-signals.md)

**Default: 10 minutes.** Two Linux terminal tabs on the **same Linux machine**, as your normal user. Label them A and B in your head. No installation, Python script, or `sudo` needed.

Lab 04 complete reported hai. Uska Q2 later revisit karenge; aaj usko repeat nahi karna.

## 1. The question

A program is installed on disk. Does that mean it is currently running?

**Program:** instructions stored in a file, ready to be run.

**Process:** a running instance of a program, managed by the operating system. It has an identity, a user, memory, and other resources. It may be waiting rather than actively using the CPU.

The same program can have several processes running at once. A **PID** is a process ID. A **PPID** is its parent's process ID. Your interactive shell is itself a process; it can start another process for a command.

We will use `sleep`, a small program that waits for the requested duration and then exits. No network port is needed for this task.

## 2. Terminal A: locate the program and start it

First run:

```bash
command -v sleep
```

`command -v` asks your shell how it resolves the name `sleep`. In an ordinary Linux setup, it prints an executable path such as `/usr/bin/sleep`. Use your actual result. If it reports an alias/function instead, share that before continuing with the experiment.

This locates the program; it does not start the waiting experiment.

Next:

```bash
echo $$
```

`echo` prints its argument. In the ordinary interactive Bash shell used here, `$$` expands to the shell's PID. Write this number down as **A's shell PID**. The two dollar signs are literal syntax to type, not a placeholder.

Predict: after the next command, will A immediately show another prompt?

```bash
sleep 600
```

`600` is the duration in seconds: ten minutes. Keep A open. Its shell normally waits for this foreground command to finish. No output is expected; a quiet terminal does not mean the computer froze.

## 3. Terminal B: observe A's process

Open another terminal tab into the **same Linux environment**. Another tab does not create another machine. If uncertain, compare `hostname` and `whoami` in the two tabs before starting the experiment.

Run:

```bash
ps -C sleep -o pid,ppid,user,args
```

Every part explained:

| Part | Meaning |
| --- | --- |
| `ps` | Show a snapshot of process information |
| `-C sleep` | Select processes with the executable name `sleep` |
| `-o` | Choose which output columns to show |
| `pid` | This process's ID |
| `ppid` | Its parent's process ID |
| `user` | The user identity under which it runs |
| `args` | Command and arguments reported for that process |

The comma-separated column names are one argument to `-o`; type them without spaces between the names.

Find the row whose PPID matches **A's shell PID**, whose user is yours, and whose command is `sleep 600`. If other sleep processes appear, leave them alone. If no row matches, share the output rather than guessing which process is yours.

Write down **sleep's PID**, separately from the shell's PID. No need to memorize either number.

**Explain before continuing:** why are those two PIDs different? Which process started which?

## 4. Stop your experiment and observe again

Return to **Terminal A**, where your `sleep 600` is still running. Press **Ctrl+C**: hold Ctrl and press C. Don't type the words `Ctrl+C`.

In this ordinary foreground setup, the terminal sends an interrupt signal to the foreground process group. `sleep` normally terminates, and A's shell shows its prompt again. This is a signal, not deletion of the program file. We will investigate signals more in the next lab.

In **B**, rerun:

```bash
ps -C sleep -o pid,ppid,user,args
```

Your previous sleep PID should no longer appear. Other unrelated sleep processes may remain. If there are no matching processes, headers without a process row are expected.

In **A**, run:

```bash
command -v sleep
```

The executable is still available. You stopped one process; you did not uninstall the program.

If ten minutes elapsed before Ctrl+C, `sleep` may already have exited normally. Record that honestly. You can rerun this small experiment if you want to observe interruption specifically.

## 5. Tiny checkpoint and recording

Answer using your actual output:

1. Which result located the program, and which showed its running process?
2. Why did the sleep process have a different PID from A's shell?
3. After the sleep process ended, could you run the program again? What evidence supports that?

Record 30–60 seconds: **program path → shell starts process → PID/PPID → process ends, program remains**. One take. If time is up, leave a bookmark and record later.

Send this back; no long essay needed:

```text
Program location:
A shell PID:
Sleep row from ps:
After stopping: my sleep PID present / absent
Program vs process in my words:
```

Optional [log bookmark](../SESSION-LOG.md): `Lab 05: last step ___ → next ___`.

## Check after trying

- `command -v` identifies how the command resolves; the `ps` row shows a running instance.
- The interactive shell and the sleep process are different processes. In this experiment the shell starts sleep, and sleep's PPID identifies that shell.
- The executable remains after the process exits; you can start another instance. PIDs can be reused over time, so a PID is not a permanent identity for a program.

**Optional two-minute experiment:** run `sleep 600` again in A, inspect it in B, then stop it with Ctrl+C in A. Compare the program name, PID, and PPID with the first run. Predict which relationships should stay the same before checking. Stop after this; no extra lab required today.
