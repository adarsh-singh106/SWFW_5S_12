# Lab 02: One file, different paths

[All labs](../README.md) | [Previous: paths](01-paths.md) | [Next: file permissions](03-file-permissions.md)

**Default: 10 minutes.** Feeling good? Optional 15-minute extension at the end. Stop at any step and resume there. Use the same **Linux terminal** as Lab 01.

## 1. Recall first — 60 seconds, notes closed

Imagine you are in `/var/log`. Treat each question as a fresh start there:

1. Where does `cd ..` take you?
2. Where does `cd /` take you?
3. Can I know your exact `cd ~` destination without knowing your user's home?

Say your answers, then check: `/var`; `/`; no. If one was wrong, explain the correction and continue.

## 2. Why this matters

Later, a collector might run correctly from your terminal but fail when started elsewhere. A relative filename can be one reason. Today you will create that failure yourself and fix it without moving the file.

A text file contains bytes. Its path tells a program where to find it. Changing your current directory changes how **relative** paths resolve; it does not move the file.

Four tools for this experiment:

| Tool | What it does here |
| --- | --- |
| `mkdir` | Creates a directory |
| `printf` | Produces the text we supply |
| `ls` | Lists directory entries |
| `cat` | Reads the named file and prints its contents |

The shell's `>` redirects output into a file. **It creates the file if absent and overwrites its contents if present.** We use it only for a new practice file below. `\n` in the `printf` format produces a newline.

## 3. Make a tiny practice area

Run one line at a time. Predict what each line changes or displays before pressing Enter.

```bash
cd ~
mkdir fleet-path-lab-02
cd fleet-path-lab-02
mkdir notes
printf 'hello fleet\n' > notes/node.txt
ls
ls notes
cat notes/node.txt
pwd
```


If `mkdir fleet-path-lab-02` says it already exists, pause: if resuming this lab, inspect it with `ls ~/fleet-path-lab-02` and resume your last step. Otherwise pick a fresh practice-folder name and use that name throughout. Do not overwrite unrelated files.

Before continuing, explain:

- Why does `ls` show `notes`, while `ls notes` shows `node.txt`?
- Did `cat` create the file, or only read it?
- Write down the exact path printed by `pwd`. That is your practice directory's absolute path.

## 4. Cause one harmless failure

You are currently in your practice directory. Predict success or failure for each `cat` before running it:

```bash
cd notes
cat node.txt
cat notes/node.txt
```

The last command should fail in this new practice layout. **Do not fix it by creating another file.**

Answer first: from your current directory, what full path did the failing command try to read?

Now test these alternatives:

```bash
cat ./node.txt
cat ../notes/node.txt
cat ~/fleet-path-lab-02/notes/node.txt
```

All three should read the same file in this layout. Explain the route each takes. `~` is expanded by the shell to your home; it is not a directory literally named `~` here.

## 5. Use an absolute path

Take the exact `pwd` output you wrote down in step 3 and append `/notes/node.txt`. That gives the file's absolute path.

For example, **only if** that output was `/home/sam/fleet-path-lab-02`, the file path would be `/home/sam/fleet-path-lab-02/notes/node.txt`. Use your actual path.

Run `cd /tmp`. Then type `cat` followed by your full absolute file path, enclosing the path in double quotes. Predict the result before running it.

Explain: why does this work even though your current directory changed?

## 6. Small recording checkpoint

Notes closed, record 30–60 seconds:

> File wahi thi. Ek command fail hui because ___. Relative path ___ se start hota hai. Absolute path ___ se start hota hai. Maine file move kiye bina ___ change karke read ki.

Checkpoint: read the same file from two directories and explain the deliberate failure. If the output surprises you, paste the command plus `pwd` output into chat; that is enough to debug together.

Optional [log bookmark](../SESSION-LOG.md): `Lab 02: last completed step ___ → next ___`. No transcript needed.

## Check after trying

- `ls` lists the practice directory, containing `notes`; `ls notes` lists that subdirectory.
- `printf` plus shell redirection wrote the file. `cat` read it.
- Once inside `notes`, `notes/node.txt` tries to find another `notes` directory underneath your current one. In this layout that nested directory does not exist.
- `./node.txt` starts in the current directory.
- `../notes/node.txt` goes to the parent, then back into `notes`, then to the file.
- The absolute path starts at `/` and does not depend on the current working directory. The file still has to exist and be accessible.

## Optional good-energy challenge — up to 15 minutes

Use only the practice file you made. No new tools needed.

1. Go to your home directory. Read the file using a relative path, without `~` or a leading `/`.
2. Go to the practice directory. Read the file again using a relative path.
3. Explain why the two command arguments differ even though the file is unchanged.
4. Imagine a collector uses `notes/node.txt`. What must you know before deciding which file it will read?

Try before checking: from home, the relative path is `fleet-path-lab-02/notes/node.txt`; from the practice directory it is `notes/node.txt`. You need the collector process's current working directory.

Stop after this challenge. Tomorrow's minimum remains unchanged. Next topic: users and permissions—why an existing file might still refuse access.
