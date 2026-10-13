# Document 04: Networking Reality Check & The Input Validation Contract

**Series:** Fleet Manager Learning Series\
**Topic:** Feature 1 — Node Inventory (Validation)\
**Status:** Reading completed through Document 04, reported by student on 2026-10-13; independent application pending.\

AI-drafted in the previous agent session (Antigravity per the inherited checkpoint; original draft date unverified). Reviewed by Codex on 2026-10-13. Examples are proposed learning material, not verified product behavior.

---

## 1. Networking Reality Check: Public IP vs. Private IP (The College Wi-Fi Doubt)

### The Problem
*"College Wi-Fi mein sabhi computers ka IP same dikhta hai kya? Agar sabka IP same hai aur port 22 hai, toh Fleet Manager unhe pehchanega kaise?"*

### First Principles Breakdown

```
        Internet (Duniya)
               │
               ▼
   [ College Main Router / NAT ]  <-- Public IP (e.g. 203.0.113.5)
        │            │
   ┌────┴────────────┴────┐ (Local Area Network - LAN)
   ▼                      ▼
[ Lab PC 1 ]          [ Lab PC 2 ]
Private IP:           Private IP:
192.168.1.10          192.168.1.11
Port: 22              Port: 22
```

1. **Private (Local) IP:**
   * Jab tum college Wi-Fi se connect hote ho, router har device ko ek unique local address deta hai (usually `192.168.x.x` ya `10.x.x.x`).
   * **Lab PC 1:** `192.168.1.10`
   * **Lab PC 2:** `192.168.1.11`
   * Local network ke andar **dono ka IP alag-alag hota hai**!
2. **Public IP & NAT (Network Address Translation):**
   * Jab tum dono Google open karte ho, Google ko sirf router ka ek hi **Public IP** dikhta hai.
   * Agar Fleet Manager **usi local Wi-Fi** ke andar chal raha hai, toh wo private endpoints use kar sakta hai, provided routing, firewall rules, and Wi-Fi client isolation allow access. Same Wi-Fi does not guarantee connectivity. This diagram is a common IPv4 NAT example, not every network topology.
3. **The Golden Engineering Insight: Endpoint $\neq$ Unique Identity!**
   * Kal agar router restart ho gaya, toh DHCP Lab PC 1 ka IP kisi aur ko de sakta hai!
   * Isliye IP + Port sirf ek **Endpoint (raasta)** hai, wo machine ka permanent aadhar card (Identity) nahi hai.
   * Real production systems baad mein a trusted **SSH host key** verify karke server authenticate karte hain. Pehli baar key ko trusted channel se establish karna zaroori hai. A reported machine-ID is inventory metadata, not cryptographic proof of server identity.

---

## 2. Why Backend Validation Is Mandatory

Frontend HTML/JS validation sirf **user experience (UX)** ke liye hota hai:
* User galat port dale toh form laal ho jaye, user ko jaldi pata chale.
* **Lekin:** Koi bhi banda Chrome DevTools, `curl`, ya Postman se frontend ko bypass karke direct backend API pe request bhej sakta hai:
  Illustrative Bash request; no backend is running yet.
  ```bash
  curl -X POST http://localhost:8000/nodes -H 'Content-Type: application/json' -d '{"name":"Hacker","address":"1.1.1.1","ssh_port": -9999}'
  ```
* Agar backend pe validation nahi hua, toh invalid/corrupt data seedha database mein chala jayega aur downstream failures ya incorrect behavior cause kar sakta hai; a crash is not inevitable.

> **Rule of Web Engineering:**\
> *"Never trust the client. Always validate at the backend gate."*

---

## 3. The SSH Port Validation Contract

Before writing code, ek engineer hamesha **Function Contract** (Specifications) tay karta hai:

### Rules for SSH Port:
1. **Type:** Value integer honi chahiye (ya aisi string jo valid integer ban sake, jaise `"22"`).
2. **Range:** Is application ke SSH destination ke liye allowed range **1 se 65535** hai.
   * `0` is reserved.
   * Negative numbers (`-22`) are invalid.
   * Numbers $> 65535$ are invalid.
3. **Behavior:**
   * Valid hone par: Clean integer return kare (e.g. `22`).
   * Invalid hone par: Clear error / exception raise kare jisme exact wajeh likhi ho.

---

## 4. Contract gaps to settle before coding

The broad rules above leave edge cases undefined. Proposed exercise policy (awaiting student agreement):

| Input | Proposed result |
| --- | --- |
| `22`, `1`, `65535` | Return the integer |
| `"22"`, `"0022"` | Accept ASCII decimal digits; return `22` |
| `True`, `False`, `22.0`, `22.5`, `None` | Reject with `ValueError` |
| `" 22 "`, `"+22"`, `"2_2"`, non-ASCII digits, `"22.0"`, `""` | Reject with `ValueError` under this strict text policy |
| `0`, `-22`, `65536`, `"0"` | Reject with `ValueError` |

Use a helpful error explaining type/format or range. No network, database, or file side effects. Python conversion alone is not validation: `int()` accepts more forms than this policy, and booleans are a subclass of integers. See [primary references](references.md).

**Next action:** Agree or adjust this table, then write `validate_ssh_port(value)` yourself and check these examples. This table is a proposal, not a previously approved decision; no solution is supplied here.

## 📝 Document 04 Revision Notes

> 1. **LAN vs Internet:** Local Wi-Fi pe har machine ka Private IP unique hota hai (`192.168.x.x`), jabki bahar ke liye Public IP shared hota hai.
> 2. **Endpoint vs Identity:** IP badal sakta hai; trusted SSH host-key verification authenticates the server; an unverified key is not enough.
> 3. **Validation Rule:** Frontend check = UX; Backend check = Security & Data Integrity.
> 4. **Port Boundaries:** 1 to 65535 for our SSH destination contract.

---

## 🛠️ Hands-on Practice & Review

👉 **[Go to Practice 01: SSH Port Validator & Code Review](practice/practice-01-port-review.md)**\
*(Student practice code and step-by-step code review reside in the `practice/` subfolder)*
