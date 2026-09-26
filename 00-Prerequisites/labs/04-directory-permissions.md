# Lab 04: File readable hai, directory access rok sakti hai?

[All labs](../README.md) | [Previous: file permissions](03-file-permissions.md) | [Next: programs and processes](05-programs-and-processes.md)

**Day 4 target. Default: 10 minutes.** Lab 03 complete maana hai; repeat nahi karna. Same Linux terminal, ordinary user, no `sudo`.

## 1. Predict first

A file has read permission. Its parent directory has no execute permission. Will knowing the exact filename let you read it? Say your guess; test below.

For a **directory**, permission meanings differ from a regular file:

| Bit | Directory meaning |
| --- | --- |
| `r` | Read the list of names inside |
| `x` | Search/traverse it to access an entry by name |
| `w` | Change its entries; creating/removing entries normally also needs `x` |

To read a file through a path, you need search access through the path's directories as well as read access to the file. Today we isolate directory `r` versus `x`. Entry creation/deletion and special rules can wait.

## 2. Create the experiment

Run one line at a time. `id -u` must not show `0`; root can bypass the restriction we are testing. If it does, stop and tell me.

```bash
id -u
cd ~
mkdir fleet-dir-lab-04
cd fleet-dir-lab-04
mkdir box
printf 'file is still here\n' > box/note.txt
chmod u+r box/note.txt
chmod u+rwx box
cat box/note.txt
```

If the practice directory already exists, inspect and resume your previous attempt rather than overwriting files. Use Linux home, not a Windows-mounted folder. All permission changes below affect only your practice `box` directory. Stay in `fleet-dir-lab-04` throughout.

## 3. Names visible, contents inaccessible

Predict each result, then run:

```bash
chmod u-x box
ls -1 --color=never box
cat box/note.txt
```

Plain name listing should show `note.txt`; reading it should fail. We use `ls -1 --color=never` to avoid requesting extra file details or colored type information. Shell aliases can still add options; unexpected output is something to inspect, not a failed lesson.

Here `-1` is the digit one, not lowercase `-l`. If you instead run `ls -l box`, you may see `note.txt` alongside question marks and Permission denied: directory `r` allows reading the name, but missing directory `x` prevents looking up that entry's metadata. This does not mean the file disappeared or its permission bits turned into question marks.

Before restoring, say: **which permission is missing, on which object?**

```bash
chmod u+x box
cat box/note.txt
```

## 4. Contents accessible by known name, listing denied

Predict, then run:

```bash
chmod u-r box
ls -1 --color=never box
cat box/note.txt
```

Listing should fail, but reading the known `box/note.txt` path should work. Its name is already known, directory search is allowed, and the file is readable.

**Restore before stopping:**

```bash
chmod u+rwx box
ls -ld box
cat box/note.txt
```

If results differ, restore permissions first, then share `id`, `pwd`, `ls -ld box`, and the unexpected command/output. Don't use `sudo` to force the predicted outcome.

## 5. Explain the evidence

After doing both steps 3 and 4, answer in your own words. These questions only need this experiment, not knowledge of the future project:

1. Why did `cat` fail when the file's own read bit stayed unchanged?
2. In step 4, `box` still has `x` but no `r`. Why can `cat box/note.txt` work while listing the names inside `box` fails? Compare with step 3, where `x` was missing.
3. A friend says: "The file has read permission, so `cat` must work." Using your experiment, what else would you check? No Fleet Manager knowledge needed.

Check after attempting: directory search was missing in step 3; directory listing was missing in step 4; inspect the executing user and permissions along the full path, not only the final file.

**Send back:** `Without x: ls ___ / cat ___. Without r: ls ___ / cat ___. Restored: yes/no.` Add one sentence explaining the difference.

## Recording milestone

Before the recording, you can revisit the worked answer below whenever needed. Lab completion and a concept needing another explanation can both be true.

### Q2 worked answer — baad mein revise karne ke liye

**Question in simple words:** directory ke andar ke names list nahi kar sakte, toh already-known file ko kaise read kar sakte hain?

`ls` aur `cat` yahan Linux se do different kaam maang rahe hain:

- `ls -1 --color=never box`: "Mujhe batao `box` ke andar kya-kya names hain." Iske liye directory ka **r** chahiye.
- `cat box/note.txt`: "Mujhe naam already pata hai: `note.txt`. `box` mein us naam ko look up karke file kholo aur contents padho." Iske liye `box` ka **x** aur file ka apna **r** chahiye. Directory ke saare names list karna zaroori nahi.

`cat` pehle `ls` chala kar file nahi dhoondhta. It gives the known path to the operating system, which resolves that path.

| Our experiment | Plain names listing | `cat box/note.txt` | Why |
| --- | --- | --- | --- |
| Step 3: `box` has owner `r`, lacks owner `x` | Works | Permission denied | Names padh sakte ho, but entry ko access karne ka search permission nahi |
| Step 4: `box` has owner `x`, lacks owner `r` | Permission denied | Works | Names ki list nahi mil sakti, but known name ko access kar sakte ho |

This assumes our ordinary-user setup, an existing readable `note.txt`, and access through the earlier directories in its path. Knowing a filename never bypasses permissions: it only avoids needing to discover the name through a directory listing.

**Tumhare words mein answer ho sakta hai:**

> Step 4 mein directory ka read permission hataya tha, isliye uske andar ke names list nahi kar sakta. Lekin `note.txt` ka naam mujhe pehle se pata hai. Directory par x aur file par r hai, isliye exact path se file read kar sakta hoon. Step 3 mein directory ka x nahi tha, isliye naam pata hone ke baad bhi file access nahi hui.

Command reminder: `-1` is digit one (one name per line); `--color=never` disables special output colors; `box` is the directory argument. Lowercase `-l` requests details too, so its question-mark output is different from a plain names listing.

**Later recall, optional:** notes band karke explain karo: "Does `cat box/note.txt` need to list every name inside `box` first?" No need to repeat the entire lab today.

### Recording when ready

This completes the planned paths/permissions block once the results make sense. Make one 3–5 minute demo explaining a relative-path failure and one permission failure with their fixes. It replaces the small recording; no separate audio or written transcript required.

If the experiment used your available time, record at the next session rather than extending today. Log only the resume point if useful. The next topic is **program versus process, PID, and inspecting your own running process**.
