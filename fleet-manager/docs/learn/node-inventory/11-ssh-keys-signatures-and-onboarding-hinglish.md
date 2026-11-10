# Microscopic Guide: SSH Keys, Digital Signatures, MITM Defense & Fleet Manager Onboarding (Hinglish)

*Target Audience: Developer / Student / Evaluator*  
*Topic: Distributed Linux Fleet Management (SWFW-12 Sem 5)*  
*Language: Hinglish (Intuitive, Real-World & Mathematical Breakdown)*

---

## 1. MITM (Man-In-The-Middle) Attack Kya Hai?

### Real-Life Analogy
Maan lo tum (Fleet Controller - FC) apne dost (Remote Node - VM) ko secret letter bhej rahe ho. Beech mein ek postman (Attacker / Hacker - Mallory) baitha hai.
* Jab tumne letter bheja, usne raste mein letter pakad liya, khol ke padha, modify kiya, aur dost ko de diya.
* Jab dost ne reply kiya, tab bhi usne beech mein pakad ke padha aur tumhe de diya.
* **Nateeja:** Tumhe lagta hai tum dost se direct baat kar rahe ho, dost ko lagta hai wo tumse direct baat kar raha hai—lekin beech mein attacker tumhara saara data, commands aur secrets padh raha hai aur badal bhi sakta hai!

### Network Level Par
Jab Fleet Controller (`10.160.0.2`) kisi remote node (`10.160.0.5:22`) par connect karta hai, network (Wi-Fi, router, DNS, ARP) untrusted hota hai. Koi bhi attacker bol sakta hai: *"Haan, main hi 10.160.0.5 hoon!"* Agar controller bina verification ke connect kar lega, toh pura system compromise ho jayega.

---

## 2. Host Identity vs User Identity (Kiski Pehchaan?)

Linux SSH mein do alag-alag identities hoti hain:

| Term | Kiski Pehchaan Hai? | Kahan Save Hoti Hai? | Kaam Kya Hai? |
| :--- | :--- | :--- | :--- |
| **Host Identity** *(Node)* | **Puri Machine / OS ki identity** (kisi ek user ki nahi) | `/etc/ssh/ssh_host_ed25519_key.pub` | Fleet Controller ko prove karna ki: *"Main sach mein wahi VM hoon jisse tum connect karna chahte ho, koi nakli machine nahi."* |
| **User Identity** *(Fleet Controller)* | **Login karne wale Controller ki identity** | Node ke `~/.ssh/authorized_keys` mein | Node ko prove karna ki: *"Main tumhara authorized Fleet Controller hoon, mujhe bina password ke login karne do."* |

---

## 3. Step 2 vs Step 3: Key Ka Direction Aur Kaam

Fleet Manager onboarding mein keys ka aana-jaana do alag directions mein hota hai:

```text
[ STEP 2: Host Identity ]
Remote Node  ================ (Public Host Key) ================>  Fleet Controller
(Node proves who it is; FC verifies fingerprint & saves in known_hosts)

[ STEP 3: Controller Authorization ]
Fleet Controller  ============ (Public Controller Key) ============>  Remote Node (~/.ssh/authorized_keys)
(FC places its public key on the Node so Node allows passwordless login)
```

---

## 4. Bina Step 3 ke Password Kyun Lagta Hai? Aur Fleet Manager Password Kyun Nahi Use Karta?

### Normal SSH Fallback
Agar tumne Step 3 nahi kiya (yaani FC ki public key node ke `authorized_keys` mein nahi daali), aur terminal se connect karoge:
```bash
ssh ubuntu@10.160.0.5
```
SSH dekhega ki client ke paas koi authorized key nahi hai, toh wo turant fallback karega aur password maangega:
```text
ubuntu@10.160.0.5's password:
```

### Fleet Manager Password Kyun Use Nahi Karta?
1. **Background Automation:** Fleet Manager har 30–60 second mein background mein CPU, RAM, disk aur availability check karta hai. Agar password hota, toh kya har 30 second mein screen par popup aake password maangta? Automation fail ho jata!
2. **Security Risk (Password Leak):** Agar password use hota, toh Fleet Manager ko saare nodes ke passwords apne database mein store karne padte. Database chori hua toh saare servers hack! SSH key se Fleet Manager ko kisi node ka password store hi nahi karna padta.
3. **Brute Force Protection:** Production Linux servers par password authentication disable karke sirf SSH Key allow ki jaati hai taaki internet ke bots password guess na kar sakein.

---

## 5. "Digital Signature" / "Sign Karna" Asal Mein Kya Hota Hai?

### Bank Check Analogy
* **Private Key:** Tumhara secret pen (sirf tumhare paas hai).
* **Public Key:** Bank ke paas tumhara specimen signature sample (`authorized_keys`).
* **Challenge:** Bank ka clerk ek naya random check deta hai.
* **Signature:** Tum apne secret pen se us check par sign karte ho.
* **Verification:** Clerk apne system mein rakhe public sample se match karta hai aur paisa (access) de deta hai.

---

## 6. Trapdoor Math: Sign Aur Verify Ka Microscopic Example

Chalo simple numbers se dekhte hain ki computer andar math kaise karta hai:

### Step A: Setup (Pehele se tay)
* **Global Constant ($G$):** $2$ (Ye ek universal constant number hai jo sabko pehle se pata hai).
* **Private Key ($d$):** $7$ (Secret number, sirf Fleet Controller ko pata hai).
* **Public Key ($Q$):** $7 \times 2 = \mathbf{14}$ (Ye Node ke `authorized_keys` mein rakha hai).

### Step B: The Challenge
Node ek random challenge number bhejta hai:
$$\text{Challenge} = \mathbf{10}$$

### Step C: Fleet Controller "Sign" Karta Hai
Fleet Controller apne secret number ($7$) aur challenge ($10$) ko formula mein daalta hai:
$$\text{Signature} = 10 + 7 = \mathbf{17}$$
FC ye number ($17$) Node ko bhejta hai. Isi ko **Digital Signature** bolte hain!

### Step D: Node "Verify" Karta Hai (Bina Secret Jane!)
Node ke paas secret $7$ **nahi hai**. Node ke paas sirf:
* Constant $G = 2$
* Public Key $= 14$
* Challenge $= 10$
* Signature $= 17$

Node ye formula check karta hai:
$$\text{Signature} \times G \stackrel{?}{=} (\text{Challenge} \times G) + \text{Public Key}$$
$$17 \times 2 \stackrel{?}{=} (10 \times 2) + 14$$
$$34 = 20 + 14 = \mathbf{34}$$

**Both sides are EQUAL (34 == 34)!**  
Node bolta hai: *"Aha! Equation balance ho gayi! Iska matlab jisne 17 banaya tha, usko secret number 7 pata tha. ACCESS GRANTED!"*

---

## 7. Wo "2" Kahan Se Aaya? Aur Kya Formula Hamesha Same Rahega?

### Wo "2" Kya Hai?
* Isko cryptography mein bolte hain **Generator Point ($G$)** ya **Base Point**.
* Ye koi secret number nahi hai. Ye RFC standard (RFC 8032 - Ed25519) mein likha ek fixed global number hai.
* Duniya ke har Linux OS, OpenSSH, aur Fleet Manager ke code mein ye number hardcoded hota hai.

### Kya Formula Aur $G$ Hamesha Same Rahenge?
* **HAAN!** Formula (Schnorr Signature Scheme) aur Base Point $G$ (wo "2") **hamesha 100% same rehte hain**. Ye mathematical law hain.
* **Badalta kya hai?**
  1. **Private Key:** Har user/controller ka apna secret number hota hai.
  2. **Public Key:** Private key se calculate hoti hai.
  3. **Challenge Message:** Har login session mein naya random number generate hota hai taaki koi purana signature copy-paste (replay attack) na kar sake!

---

## 8. Fleet Manager Project Mein Ye Sab Kaise Fit Hota Hai?

| UI Step / Button | Backend Mein Kya Hota Hai | Abhi Padha Hua Concept |
| :--- | :--- | :--- |
| **"Register Node"** | `POST /api/nodes` $\rightarrow$ SQLite mein insert hota hai (`NOT_CHECKED`, `PENDING_SETUP`). | Inventory record create hua. |
| **"Scan Host Key"** | `POST /api/nodes/{id}/scan-host-key` $\rightarrow$ Controller target node ke port 22 se public key mangwata hai aur SHA-256 hash nikaalta hai. | Node ki **Host Identity** scan hui. |
| **Independent Check** | Operator terminal par `ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub` run karta hai. | **MITM Attack se bachav**: Out-of-band SHA-256 fingerprint matching. |
| **"Trust Host Key"** | `POST /api/nodes/{id}/trust-host-key` $\rightarrow$ Fingerprint ko `/var/lib/fleet-manager/known_hosts` mein write kar deta hai. | Host Identity **cryptographically PIN** ho gayi. |
| **Bootstrap Command** | Operator `echo '<PUBLIC_KEY>' >> ~/.ssh/authorized_keys` chalata hai. | Controller ki Public Key lock ban kar node par set ho gayi (**Step 3**). |
| **"Validate SSH Connectivity"** | `POST /api/nodes/{id}/connectivity-check` $\rightarrow$ Paramiko challenge-response sign karta hai aur check karta hai. | **Signature Verification** pass hua $\rightarrow$ Status **`READY`** aur **`REACHABLE`**! |
