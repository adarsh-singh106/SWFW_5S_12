# Lab 06: Is the process waiting, paused, or finished?

[All labs](../README.md) | [Previous: programs and processes](05-programs-and-processes.md) | [Next: services and logs](07-services-and-logs.md)

Take your time. Understand the explanation, then try the experiment. On a low-energy day, you can finish one section and continue later. Use two Linux Bash terminals, A and B, on the same machine and under the same ordinary user. You do not need `sudo`.

## 1. Starting a process and using the CPU are different things

You ran `sleep 60` in Lab 05. Here is what happens:

1. You type the command.
2. The shell starts a process for the sleep program. That process gets a PID.
3. The process runs some instructions on the CPU. It asks Linux to let it wait for 60 seconds.
4. The process now waits for the timer. It still exists, but its instructions are not using the CPU while it waits.
5. The timer finishes. When the process gets CPU time, it continues and normally exits.

**Waiting does not mean the process has not started. Our sleep process started first, then began waiting.**

The **kernel** is the core part of Linux. It manages processes and decides which ready process gets time on the CPU. A process does not need to use the CPU every moment that it exists.

### Four situations to keep separate

| Situation | What it means | What happens next? |
| --- | --- | --- |
| Running / ready (`R`) | The process is using the CPU, or is ready to use it | Its instructions run when it gets CPU time |
| Waiting (`S` in our sleep example) | The process has started and is waiting for a timer or event | Once its wait is over, it can continue when it gets CPU time |
| Stopped (`T`) | The process still exists, but its execution has been paused | In this experiment, we resume it with CONT |
| Exited | The process has finished executing | We cannot resume it; we must start another process to run the program again |

These are not all possible Linux process states. For now, learn these differences. Not every kind of waiting uses S; here we are observing sleep's timer wait.

**Waiting versus stopped:** a waiting process can continue after its timer finishes. A stopped process stays stopped even if its timer finishes, until it is resumed.

Think of a video: buffering waits for data, so playback can continue when data arrives. Pressing Pause keeps playback paused even when data is available. This is just an analogy to help explain the difference.

**Quick recall:** you can see a PID for `sleep 60`, and its state is S. Has the process started? Say your answer first.

Answer: yes. It started, then began waiting for its timer.

## 2. How do we ask Linux to pause a process?

We can send the process a **signal**: a notification that has a particular meaning. The signal we choose determines the action requested.

The `kill` command sends signals. Its name can be confusing: not every use of `kill` ends a process.

| Signal | Meaning in our experiment |
| --- | --- |
| STOP | Pause this process's execution |
| CONT | Resume this stopped process |
| TERM | Ask this process to terminate; ordinary sleep exits in response |
| INT | Interrupt; you sent this with Ctrl+C in Lab 05 |

STOP is a short name for SIGSTOP. You do not need to memorize signal numbers.

The steps are:

```text
You choose a signal name and a process PID
    -> kill asks the kernel to send that signal
    -> the kernel checks the target and your permission
    -> the signal takes effect
    -> you inspect the result with ps
```

After STOP, the process keeps its PID, memory, and other state. CONT can therefore resume that same process. Once the process exits, this is no longer possible.

In Lab 05, B could terminate the sleep process started by A. Both ran under user ash, which allowed this in your normal setup. A process does not need to be the target's parent to send it a signal.

**This is a good place for a break. You have not started the practice process yet.**

## 3. Start a fresh process in A

Do not reuse the old PID 52. Start a new process and find its actual PID.

In terminal A, run one line at a time:

```bash
echo $$
sleep 1800
```

- `echo` prints text.
- `$$` expands to this Bash shell's PID. Write that number down as A's shell PID.
- `sleep 1800` means wait for 1800 seconds, or 30 minutes. This gives you time for the experiment. You will end the process yourself; you do not need to wait 30 minutes.

A will not immediately show another prompt. The shell is waiting for the sleep command to finish.

## 4. Find the process in B

```bash
ps -C sleep -o pid,ppid,user,stat,args
```

| Part | Meaning |
| --- | --- |
| `ps` | Show process information at this moment |
| `-C sleep` | Select processes named sleep |
| `-o` | Show the columns listed next |
| `pid` | The process's ID |
| `ppid` | Its parent's ID |
| `user` | The user identity under which it runs |
| `stat` | Its state |
| `args` | Its command and arguments |

Use commas without spaces between the column names. `ps` shows a snapshot, not a live view. Run it again after each change.

Find your row: the user is yours, the command is `sleep 1800`, and PPID matches A's shell PID. That row's PID is **sleep's PID**. Do not use the shell's PID as the target.

Look at the first letter of STAT. It will normally be S. Extra characters such as `+` may follow it; focus on the first letter today. S means our sleep process is waiting for its timer, not paused by STOP.

If you cannot identify the row, share the output rather than guess.

## 5. Save the PID in a variable

In B:

```bash
read -r -p 'Your new sleep PID: ' lab_pid
```

A prompt appears. Type the fresh sleep PID you just found, then press Enter.

- `read` reads what you type.
- `-r` treats backslashes as ordinary characters. You only need to enter PID digits here.
- `-p '...'` shows the quoted message as a prompt.
- `lab_pid` is the variable name we chose for storing your input.

**A variable is a value saved under a name.** If your actual PID were 87, using `"$lab_pid"` would make the shell supply 87 to the command. That number is only an example: enter your own observed PID.

The double quotes keep the value as one argument. The variable is saved in B's shell, so continue using B for these commands. Saving the number does not do anything to the process itself.

First, check the saved PID:

```bash
ps -p "$lab_pid" -o pid,ppid,user,stat,args
```

`-p` selects that particular PID. The row must be your `sleep 1800` process. If it is wrong, run the read command again and enter the correct PID.

## 6. STOP: pause the process

**Predict:** will the row disappear, or stay with the same PID?

In B, one line at a time:

```bash
kill -STOP "$lab_pid"
ps -p "$lab_pid" -o pid,ppid,user,stat,args
```

`-STOP` chooses the signal. `"$lab_pid"` chooses the target process.

Expected: **same PID, state T**. The process still exists; its execution is paused.

A may show `Stopped` and another prompt. Its shell is ready to accept a command, but sleep has not exited. The process row in B is your evidence that it still exists.

`kill` usually prints nothing when it succeeds. We use `ps` to check the effect.

## 7. CONT: resume the same process

**Predict:** will it get a new PID or keep the old one?

```bash
kill -CONT "$lab_pid"
ps -p "$lab_pid" -o pid,ppid,user,stat,args
```

Expected, if some of the original wait remains: **same PID, usually S**.

CONT removed the pause. Sleep still has a timer to wait for, so S makes sense. Resuming does not mean a process must use the CPU continuously.

A may keep showing its prompt. CONT resumes execution; it does not automatically make the command the terminal's foreground job again. The **foreground job** is the job that receives terminal signals such as Ctrl+C. Here, we send signals from B to an explicit PID instead.

**Timer note:** STOP and CONT do not restart sleep's duration from zero. If you take a long break and the original time passes, sleep may exit after CONT. Record what actually happens.

## 8. TERM: end the process

After confirming that the row still identifies your practice process:

```bash
kill -TERM "$lab_pid"
ps -p "$lab_pid" -o pid,ppid,user,stat,args
```

Expected: sleep exits and its row disappears. A may show `Terminated`.

It is normal to see only the column headings when no process matches the PID. If you check immediately, exiting may take a moment; inspect once more.

Plain `kill PID` also sends TERM by default. We write `-TERM` to make the signal name clear.

**If you stop the lesson early:** resume your paused practice process with CONT, then send TERM and check the result. If the process has already exited, do not keep signaling the saved number: Linux can later reuse that number for another process.

## 9. Explain it in your own words

Close the notes:

1. Had our sleep process already started when it showed state S?
2. What evidence showed that the process still existed after STOP?
3. Why did CONT keep the same PID?
4. Can CONT bring back a process that has exited?

Record 30–60 seconds explaining **waiting versus stopped versus exited**, using your experiment. One take is enough. If you are out of time or energy, record next session.

Send the ps outputs after STOP, CONT, and TERM, plus one sentence explaining pause versus exit. Optional [log](../SESSION-LOG.md): last completed step -> next action.

### Answers: check after trying

1. Yes. It started, then began waiting for its timer.
2. Its row was still present with the same PID and state T.
3. We resumed an existing process instead of starting a new one.
4. No. We must run the program again to create another process.

## Extra details: read when needed

- **TERM does not end every program immediately.** Some programs clean up first; some can ignore it. Code that responds to a signal is called a handler. Our ordinary sleep exits on TERM.
- **A program cannot catch or ignore STOP.** The kernel pauses its execution.
- **KILL also cannot be caught or ignored**, and does not give the program a chance to clean up. We do not need it for this experiment.
- **If you see Z:** the process has finished executing, but its parent has not yet collected its exit result. Collecting that result allows the remaining process record to be removed; this is called reaping. CONT cannot resume a Z process. Bash normally collects the result of its child process.
- **No such process:** no process matched that PID when the command ran. This does not mean the executable file was deleted.

**Next:** services and logs. First, we will check whether your Linux environment has the service manager needed for that lab.

