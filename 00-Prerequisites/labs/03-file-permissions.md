# Lab 03: File hai, phir bhi read kyun nahi ho rahi?

[All labs](../README.md) | [Previous: files and paths](02-files-and-paths.md) | [Next: directory permissions](04-directory-permissions.md)

**10 minutes.** Same Linux terminal. Today: one user's read permission on one practice file. Directory permissions and execution come later.

## 1. Recall — 30 seconds

You are inside `~/fleet-path-lab-02/notes`. Say why `cat notes/node.txt` fails and give a working relative path. Then continue.

## 2. The problem and the model

A correct path tells Linux **which file**. It does not automatically grant access. Different users may have different access to that file.

Your command runs as a process with a user identity. For ordinary Linux permission checks, the file has an **owner**, a **group**, and three sets of permission bits:

```text
-rw-r--r--
│└┬┘└┬┘└┬┘
│ │  │  └─ others
│ │  └──── group
│ └─────── owner
└───────── file type: - means regular file
```

For a regular file: `r` allows reading contents, `w` allows writing contents, `x` allows execution (other requirements also apply). A dash in a permission slot means that permission is absent.

For these basic checks, Linux uses the owner bits when your user owns the file. Otherwise it checks group membership to select group or others bits. **An owner denied read access does not fall back to the others' read bit.** Privileged processes and additional access-control mechanisms are outside this small experiment.

Project connection: a collector can find a file yet lack permission to read it. That is a different failure from a missing path.

## 3. Check your identity

Run these individually:

```bash
whoami
id
```

`whoami` shows the effective username. `id` shows user and group IDs and memberships. You do not need to memorize the numbers.

**If your user ID is 0 (root), stop and share the output.** This experiment needs an ordinary user because root can normally bypass the read restriction we are testing. Don't add `sudo` to the commands below.

## 4. Create a practice file

Use your Linux home directory, rather than a Windows-mounted directory such as `/mnt/c`, for normal Linux permission behavior.

Run one line at a time:

```bash
cd ~
mkdir fleet-permissions-lab-03
cd fleet-permissions-lab-03
printf 'node observation\n' > sample.txt
ls -l sample.txt
cat sample.txt
```

If the practice directory already exists, pause before writing: inspect it and resume if it is your earlier attempt; otherwise choose a fresh name. `>` overwrites existing contents.

`ls -l` shows permissions, link count, owner, group, size, modification time, and name. Identify the **owner** and compare it with `whoami`. Your default permission bits may differ from the example above.

## 5. Predict → remove read → observe → restore

`chmod` changes permission bits. Here `u` means the file's owner, `-r` removes read, and `+r` adds read. It does not change file ownership.

Before each line, predict its effect:

```bash
chmod u-r sample.txt
ls -l sample.txt
cat sample.txt
```

Expected for this ordinary-user setup: `cat` reports **Permission denied**. The file still exists. Look at the owner's permission triplet before trying to fix anything.

Now restore and verify:

```bash
chmod u+r sample.txt
cat sample.txt
```

**Restore before stopping**, even if the timer ends. You should see the original text. No need to delete or recreate the file.

If reading unexpectedly succeeds after removing read permission, restore it anyway and share `id` and `ls -l sample.txt` output. We'll inspect the environment instead of assuming the expected result occurred.

## 6. Recall and tiny recording

Notes closed, answer:

1. What changed: contents, path, ownership, or permission bits?
2. Why could `ls -l sample.txt` still show the file while `cat` failed?
3. Why is automatically retrying every failure with `sudo` a poor way to diagnose this collector?

Record 30–60 seconds explaining the failure and fix. This is a small checkpoint; the bigger permissions demo comes after directory permissions, not today.

Send back just:

```text
Permission string before / after removing read:
cat result after removal:
Why it failed (my words):
Read restored: yes / no
```

Optional [log bookmark](../SESSION-LOG.md): `Lab 03: last step ___ → next ___`.

## Check after your attempt

1. Permission bits changed. The content, path, and owner stayed the same.
2. Inspecting file metadata does not require reading the file's contents; access through its parent directories still matters.
3. A privileged retry can hide which permission the intended user actually lacks. Inspect the user, path, and permissions first; grant only the access the task needs.

Next: directory `r`, `w`, and `x` have different meanings from regular-file permissions. We will test those separately.
