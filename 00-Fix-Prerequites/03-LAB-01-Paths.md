# Lab 01: Where am I, and where will this command go?

**Budget:** 10 minutes. **Goal:** predict `/`, `~`, and `..` without guessing.

This is the first small checkpoint of the paths/files milestone. No installations, file deletion, or project code needed for this experiment.

## 0. Use a Linux terminal

Use an existing Linux VM terminal or your installed WSL Linux distribution. PowerShell is not the terminal for the commands below; similar-looking commands can behave differently.

If you don't know whether Linux is available, run this **in PowerShell**:

```powershell
wsl --list --verbose
```

It lists registered WSL distributions; it does not install anything. Paste its output or error back to me. If you already have a separate Linux VM, tell me that instead. No WSL distribution does not mean a VM is absent.

**If you cannot open Linux, stop here.** Environment discovery counts as today's step. We'll choose the setup using what is actually on your machine.

## 1. The problem: a command needs a location

Fleet Manager will eventually read files on another machine. A correct filename with the wrong location still fails. First learn how a shell identifies a location on one machine.

A filesystem arranges names into directories. A **path** tells the system how to locate something within that structure.

Your shell has a **current working directory**. Relative paths start there. `pwd` displays it; `cd` changes it.

| Symbol | Meaning |
| --- | --- |
| `/` | Root of the Linux filesystem; also the separator between path components |
| `~` | In these shell commands, expands to your user's home directory |
| `.` | Current directory |
| `..` | Parent directory |

An **absolute path** starts with `/`, such as `/etc`. A **relative path** does not, such as `../notes.txt`. The shell expands `~` before the command uses it; your home is not necessarily `/home/adarsh`.

First-principles question: **If I give only `notes.txt`, what starting location must the system use?** Say your answer before continuing.

## 2. Predict, then run one step at a time

Use a normal Linux shell such as Bash. Do not paste the entire exercise as one block.

First run:

```bash
pwd
```

Say the path out loud. Now, before **each row**, predict the next location. Run the navigation command, then `pwd` to check.

| Step | Navigation command | Your prediction before running |
| --- | --- | --- |
| A | `cd /` | What exact path should `pwd` print? |
| B | `cd ..` | What is above the root directory? |
| C | `cd ~` | Which user's home will this select? |
| D | `cd ..` | Based on C's actual output, where should this go? |
| E | `cd .` | Does this change anything? |

End with `cd ~` to return home. No files were moved by this exercise; only your shell's current directory changed.

## 3. Close the notes: tiny checkpoint

Answer aloud:

1. What is the difference between `cd /` and `cd ~`?
2. If your current directory is `/home/sam/projects`, where does `cd ..` take you?
3. Why can `../notes.txt` refer to different files when used from different directories?

Record **30–60 seconds**, one take: one prediction, its observed result, and your explanation. If something is unclear, say so. Check your answers below after attempting them.

Pass this checkpoint when you can explain the three answers and demonstrate the navigation. A corrected mistake counts. This does not yet complete the whole paths/files milestone.

## 4. Check only after attempting

- A: `/`.
- B: still `/`; the root's parent resolves to itself.
- C: your actual user's home directory. Use the observed output; don't assume its name.
- D: the parent of the home path you observed, in the ordinary directory layout used here.
- E: unchanged.
- `/` is the filesystem root; `~` selects your home through shell expansion.
- The parent of `/home/sam/projects` is `/home/sam`.
- `../notes.txt` starts from the current directory, goes to its parent, then looks for `notes.txt`. Different starting directories can give different results.

If your output differs, paste it. We will inspect the environment rather than force it to match the example.

## 5. Stop and leave a small trail

In [the session log](04-SESSION-LOG.md), record what you observed and the next action. You can paste this back into chat:

```text
Linux environment: ...
A / B / C / D / E outputs: ...
One prediction I corrected: ...
Still unclear: ...
```

**Next session starts with recall:** from `/var/log`, predict `cd ..`, `cd /`, and `cd ~` before checking notes. Then we will use a practice file to test absolute versus relative paths.

Timer finished? Stop here even if some steps remain. Resume at the next unchecked step; no catch-up work.
