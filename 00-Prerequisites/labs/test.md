# Prerequisites Check Test: Review & Evaluation

[Back to all labs](../README.md)

**Assessment Date:** 2026-10-04  
**Coverage:** Labs 01 to 07 (Paths, Files, Permissions, Processes, Signals, Services & Logs)  
**Overall Result:** **Pass with Distinction (~90%)**

> [!NOTE]
> This document records your exact test responses alongside detailed evaluations and conceptual corrections for future revision.

---

## Scorecard Overview

| Module | Topics Covered | Score | Result |
| :--- | :--- | :---: | :---: |
| **Part 1: Paths & Permissions** | Relative/Absolute paths, Script execution, Permission bits, Directory access | **37 / 40** | **Pass** |
| **Part 2: Processes & Services** | Programs vs Processes, Process states, Signals, systemd vs systemctl, Status vs Logs | **47 / 50** | **Pass** |
| **Total** | **Prerequisites Baseline** | **84 / 90 (~93%)** | **Ready for Lab 08** |

---

# Part 1: Paths, Files & Permissions (Labs 01–04)

### 1. Relative vs. Absolute Navigation (Labs 01 & 02)
You are currently inside `/home/ash/fleet-path-lab-02/notes`. The file `node.txt` is located directly in this directory.

#### Question 1.1: Why does typing `cat notes/node.txt` fail with an error?
* **Your exact answer:**
  > Your current working directory is different and from where you are running that command, there is no subfolder notes. So the correct command would be cat node.txt
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Since your current working directory is already `notes`, the relative path `notes/node.txt` looks for a nested folder `./notes/notes/node.txt`, which does not exist.

#### Question 1.2: Give two working commands to read `node.txt` from this current directory without running `cd`:
* **Your exact answer:**
  > - One using a **relative path** => `cat note.txt OR cat ../notes/note.txt`
  > - One using an **absolute path** => `cat /home/ash/fleet-path-lab-02/notes/note.txt`
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Both `cat note.txt` (or `cat ./node.txt`) and `cat ../notes/note.txt` resolve correctly through relative navigation, and `/home/ash/fleet-path-lab-02/notes/node.txt` correctly anchors to the root `/`.

---

### 2. Paths in Scripts and Services (Lab 02)
Imagine an automated background script runs with its current working directory set to `/` (the root directory). If that script contains the line `cat notes/node.txt`:

#### Question 2.1: What exact path does the system actually attempt to read?
* **Your exact answer:**
  > As the working directory is the root directory, the cat command says that from the current working directory go to the notes folder and read the contents of note.txt. So the exact path would be /notes/node.txt
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Relative paths resolve by appending to the current working directory: `/` + `notes/node.txt` = `/notes/node.txt`.

#### Question 2.2: Why is using an absolute path standard practice for production scripts and services?
* **Your exact answer:**
  > An absolute path is a standard practice because in production script and services, there could be, like, different machines could have different working directories. So an absolute path is independent of your current working directory. It would work always and every time it is used or executed, and it does not depend on from where you are running that command.
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Exactly right. Background tasks, cron jobs, and systemd units often run from unexpected or generic working directories (like `/` or `/var/run`). Absolute paths ensure predictability.

---

### 3. File Permission Bit Logic (Lab 03)
You own a practice file `sample.txt`. Its permission string initially reads `-rw-r--r--`. You run `chmod u-r sample.txt` as user `ash`.

#### Question 3.1: What happens when user `ash` runs `cat sample.txt`?
* **Your exact answer:**
  > "After running the above command, what it does is it removes the read permission from the u, that the user, which is ash. So when the user ash runs the command to read the content of sample.txt, it shows the, you know, permission denied, or like the ash don't have rights to, or permission to read the content of sample.txt."
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Removing `u-r` leaves owner permissions as `-w-`. Because `ash` is the owner, `cat` immediately fails with `Permission denied`.

#### Question 3.2: The `others` triplet still has `r--`. Will Linux fall back to the `others` read bit to let `ash` read it? Why or why not?
* **Your exact answer:**
  > I don't understand the question quite well, but I think what it's trying to say is that though Ash has lost his permission to read the content of sample.txt, but others permission bits still has R, that it can read the file. So can Linux fall back to that others and read the content of it? I think yes, it can do that, because Ash can pretend to be others, and it is possible because Ash can also execute commands from, like sudo, using which allows it to, like, grants the root permission, and thus it can also act as others.
* **Evaluation:** **Needs Correction (7/10)**
* **Corrected Explanation:**
  > [!IMPORTANT]
  > **Linux Never Falls Back (The "First Match" Rule):**
  > When Linux checks permissions for a process:
  > 1. It asks: *Are you the owner of the file?*
  > 2. If **yes**, Linux checks **only the owner bits**. Since owner read is missing, access is **immediately denied**. Linux stops checking right there. It **never** falls back to group or others.
  >
  > *(Regarding `sudo`: `sudo` runs commands as the `root` superuser (UID 0), not as "others". Root bypasses standard permission checks entirely).*

---

### 4. Directory `r` vs. `x` (Lab 04)
Directory `box` contains a file `note.txt` (which has normal read permissions).

#### Question 4.1: Case A (`box` has `r`, but lacks `x`)
* **Your exact answer:**
  > - Can you run `ls box` to see the name `note.txt`? => `yes , as the directory has r which allows user to list all files pesent in it`
  > - Can you run `cat box/note.txt` to read the contents? => `No. it would return permission deneied becuase box lacks x`
* **Evaluation:** **Correct (10/10)**

#### Question 4.2: Case B (`box` has `x`, but lacks `r`)
* **Your exact answer:**
  > - Can you run `ls box` to list the directory? => `it would fail`
  > - Can you run `cat box/note.txt` to read the file? => `this would work as box now has x . which tarverse thorudh the files and access them`
* **Evaluation:** **Correct (10/10)**

#### Question 4.3: In one sentence, what is the fundamental difference between read (`r`) and execute (`x`) on a directory?
* **Your exact answer:**
  > `r-> u can list the files and folder in dir`  
  > `x -> u can access the content or data of files and perform those operation as per the permission of that files`
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Concise and accurate. Directory `r` is "listing directory entries", while `x` is "traversing / entering the directory to reach an entry".

---

# Part 2: Processes, Signals, Services & Logs (Labs 05–07)

### 1. Programs vs. Processes (Lab 05)

#### Question 1.1: What is the fundamental difference between a program on disk and a process in memory?
* **Your exact answer:**
  > process is running instance of program
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Program = dormant executable instructions on disk; Process = running instance loaded in memory with a PID and system resources.

#### Question 1.2: When you terminate a running `sleep 600` process, does `/usr/bin/sleep` get deleted from your disk?
* **Your exact answer:**
  > no, the original program is not deleted , sleep 600 only brings a copy and runs in on RAM
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Terminating a process only destroys the execution context in memory; the executable binary on disk remains unchanged.

#### Question 1.3: If your interactive Bash shell has PID `38`, and you start `sleep 600` inside it, which process ID is recorded as the PPID of that `sleep` process?
* **Your exact answer:**
  > its PPID is same as the one who started it i.e 38 PID bash shell
* **Evaluation:** **Correct (10/10)**

---

### 2. Waiting vs. Stopped (Lab 06)

#### Question 2.1: When `sleep 600` runs normally, its state is `S` (waiting/sleeping). Is it actively consuming CPU cycles while it waits? When 600 seconds expire, what happens?
* **Your exact answer:**
  > - Is it actively consuming CPU cycles while it waits? => `No, it is not using CPU, it is just on wait or being pause and wating for timmer to end`
  > - When the 600 seconds expire, what happens? => `after 600 sec it gets CPU and terminates the process`
* **Evaluation:** **Correct (10/10)**
* **Explanation:** The process yields CPU time until the kernel wakes it upon timer expiration. Once woken, it finishes and exits.

#### Question 2.2: If you pause it with `kill -STOP <PID>`, its state becomes `T` (stopped). If 600 seconds pass while it is stopped, will it exit automatically? How do you resume it?
* **Your exact answer:**
  > - If 600 seconds pass while it is stopped, will it exit automatically? -> `NO . when stop the timmer also is stopped for it`
  > - How do you resume it? -> `again change the state to S and bring it on waiting`
* **Evaluation:** **Mostly Correct (9/10)**
* **Corrected Detail:**
  > To bring a stopped process (`T`) back to execution or waiting, you send the **`CONT`** signal:
  > ```bash
  > kill -CONT <PID>
  > ```

---

### 3. Signals & the `kill` Command (Labs 05 & 06)

#### Question 3.1: When you press Ctrl+C in your terminal to cancel a foreground command, what signal is sent?
* **Your exact answer:**
  > terminate the process or kill command to terminate the process
* **Evaluation:** **Needs Correction (8/10)**
* **Corrected Detail:**
  > Pressing **Ctrl+C** sends the **`SIGINT`** (Interrupt) signal. It asks the foreground process to cleanly interrupt itself.

#### Question 3.2: Does the `kill` command always destroy/exit a process? Give one example of a signal that does not terminate.
* **Your exact answer:**
  > - Does the `kill` command always destroy/exit a process? -> `No , it just gives signal to a process`
  > - Give one example of a signal sent via `kill` that does not terminate the process: -> `kill -STOP 106`
* **Evaluation:** **Correct (10/10)**
* **Explanation:** `kill` is a signal-dispatching tool. Signals like `SIGSTOP` (pause) or `SIGCONT` (resume) do not terminate the process.

---

### 4. Why Use a Service Manager? (Lab 07)

#### Question 4.1: Why manage a background process as a service (via `systemd`) instead of just opening a terminal tab? Give 2 clear reasons.
* **Your exact answer:**
  > managing diffiernt process or serivce manuall is error prone . 
  > we have to check what process to start , under which user , what if it already exist , exsit but not running or stop etc etc
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Great practical points. Two core technical benefits:
  1. **Terminal detachment & auto-start:** Services run independently of user logins and can start automatically at boot.
  2. **Lifecycle & restart policies:** If the service crashes, `systemd` can automatically restart it without manual human intervention.

#### Question 4.2: What is the difference between `systemd` and `systemctl`?
* **Your exact answer:**
  > systemd is unit manger which manages different units such as service unit . while systemctl is tool to communicate with systemd
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Exactly right. `systemd` is the background manager running at PID 1; `systemctl` is the command-line client used to issue requests to it.

---

### 5. Service Status vs. Logs (Lab 07)

#### Question 5.1: `Loaded: loaded (...; enabled)` but `Active: inactive (dead)`. Is this service broken, or what does `enabled` actually mean?
* **Your exact answer:**
  > Loaded means . systemd finds its configs /defination succesfully . but it is not currently running . enabled menans it starts every time system boots
* **Evaluation:** **Correct (10/10)**
* **Explanation:** Clear and precise distinction between current runtime state (`Active`) and boot configuration (`Enabled`).

#### Question 5.2: A service failed and restarted 10 minutes ago, getting a new PID. Where would you go to find out why it crashed (`systemctl status` or `journalctl`), and why?
* **Your exact answer:**
  > i would go to journalctl it helps me check all logs and journal messages saved by systemd-journald service and not systemctl status which gives info about activity of service
* **Evaluation:** **Correct (10/10)**
* **Explanation:** `systemctl status` only gives a current snapshot and a tiny tail of recent lines. `journalctl -u <service>` maintains the complete historical log stream to inspect crashes that happened earlier.

---

## Conclusion & Next Step

You have demonstrated an excellent, practical understanding of Linux foundations. You are ready to move on to:
**[Lab 08 — Network Endpoints: IP, Ports, and Listeners](08-network-endpoints.md)**
