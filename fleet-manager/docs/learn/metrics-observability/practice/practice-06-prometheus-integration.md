# Practice 06: Prometheus Dynamic Service Discovery & Target Exporter

**Series:** Fleet Manager Hands-on Practice\
**Topic:** Feature 3 — Prometheus & Grafana Metrics Pipeline\
**Parent Lesson:** [⬅️ Document 11: The Prometheus Scrape Pipeline & Grafana Dashboards](../11-prometheus-and-grafana-pipeline.md)\
**Associated Code:** [`targets_generator.py`](targets_generator.py), [`prometheus.yml`](prometheus.yml), [`test_targets_generator.py`](test_targets_generator.py)

---

## 1. Objective

Is practice exercise mein hum Fleet Manager aur Prometheus ke beech ka **dynamic bridge** build karenge:

1. **`targets_generator.py`:** Ek Python module jo SQLite `inventory.db` se active nodes read karke Prometheus-compliant `targets.json` file generate karega.
2. **Atomic File Writing (`os.replace`):** Race conditions prevent karne ke liye temp-file write + rename pattern use karenge (taaki Prometheus kabhi aadha-adhura JSON na padhe).
3. **`prometheus.yml` Configuration:** Prometheus server ko `file_sd_configs` se configure karenge taaki bina restart ke naye nodes automatically discover ho sakein.
4. **Integration Hook:** Node registration workflow me targets export hook karenge taaki web dashboard se node add hote hi Prometheus targets sync ho jayein.
5. **Automated Verification:** `test_targets_generator.py` se format validation, schema compliance, aur file persistence verify karenge.

---

## 2. First Principles & Mechanics

### Kyun chahiye Dynamic File Service Discovery (`file_sd_configs`)?
Agar hum `prometheus.yml` ke andar static targets likhte:
```yaml
# ❌ STATIC CONFIG - BAD FOR DYNAMIC FLEETS
static_configs:
  - targets: ['192.168.1.50:9100', '192.168.1.51:9100']
```
Toh har baar naya node register hone par admin ko:
1. `prometheus.yml` edit karni padti.
2. Prometheus process ko `kill -HUP <pid>` ya `systemctl reload prometheus` bhejna padta.
3. Production environment me manual edits error-prone hoti hain.

**Solution:** Prometheus ka built-in `file_sd_configs`!
```yaml
# ✅ DYNAMIC CONFIG - PRODUCTION READY
file_sd_configs:
  - files:
      - 'targets.json'
    refresh_interval: 10s
```
Prometheus har 10 seconds me `targets.json` file ki modification check karta hai. Jaise hi content badalta hai, bina kisi packet drop ya process restart ke new targets scrape list me jud jaate hain!

---

### The Atomic Write Trap (Race Condition)
Prometheus har kuch second me `targets.json` ko read karta hai.
Agar Python script normal `open("targets.json", "w")` use kare aur us waqt Prometheus file read karne ki koshish kare jab aadha JSON likha gaya ho:
* **Prometheus error:** `Error parsing target file ... unexpected end of JSON input`.
* **Consequence:** Prometheus us cycle me targets discard kar dega!

**The Production Fix: Atomic Rename (`os.replace`)**
1. Data ko pehle ek temporary file me likho (`targets.json.tmp`).
2. Temp file ko flush aur close karo.
3. OS-level atomic operation `os.replace("targets.json.tmp", "targets.json")` se rename karo.
File system level par swap instantaneous hota hai — Prometheus ko ya toh pura puraana data milega ya pura naya data, kbhi corrupted aadha data nahi milega.

---

## 3. Prometheus Target JSON Format

Prometheus `file_sd` ka exact schema yeh hota hai:
```json
[
  {
    "targets": ["192.168.1.50:9100"],
    "labels": {
      "node_id": "1",
      "node_name": "ubuntu-lab-node1",
      "job": "node_exporter",
      "fleet": "production"
    }
  },
  {
    "targets": ["192.168.1.51:9100"],
    "labels": {
      "node_id": "2",
      "node_name": "centos-db-node2",
      "job": "node_exporter",
      "fleet": "production"
    }
  }
]
```
Har entry me:
* `targets`: Array of strings `["<ip>:<port>"]` (Node Exporter port `9100` hota hai).
* `labels`: Key-value metadata labels jo har metric time-series ke sath Prometheus me attach ho jaate hain.

---

## 4. Deep-Dive: Code Architecture & Explanations

### A. Target Structure: Single Block vs Per-Node Blocks
Prometheus `file_sd` format me array of dictionaries allow karta hai:
* **Option A (Shared Labels):** Sabhi IPs ek array me: `[{"targets": ["ip1:9100", "ip2:9100"], "labels": {"fleet": "prod"}}]`. Yahan sabhi metrics par exact same labels lagenge.
* **Option B (Our Architecture — Per-Node Labels):** Har node ka alag target block:
  ```json
  [
    {"targets": ["192.168.1.50:9100"], "labels": {"node_id": "1", "node_name": "ubuntu-lab"}},
    {"targets": ["192.168.1.51:9100"], "labels": {"node_id": "2", "node_name": "centos-db"}}
  ]
  ```
  Is pattern se Prometheus me time-series par `node_name` aur `node_id` labels automatically bind ho jaate hain, jisse Grafana dashboard par drop-down filter aur node-wise alerting extremely simple ho jaati hai!

---

### B. The Storage Guarantee: `f.flush()` vs `os.fsync()`
1. `f.write()`: Data ko Python ke user-space buffer me rakhta hai (OS ko abhi pata bhi nahi hota).
2. `f.flush()`: Python buffer se data push karta hai **Linux kernel ke page cache (RAM)** me. Agar power fail ho jaye ya kernel panic ho, data gayab ho sakta hai.
3. `os.fsync(f.fileno())`: Low-level POSIX/Windows syscall (`FlushFileBuffers` / `fsync`) trigger karta hai, jo disk controller ko order deta hai: *"RAM cache ko turant physical SSD/HDD persistent storage me commit karo!"*
4. `os.replace()`: Jab bits disk par surakshit ho jayein, tab atomic pointer swap hota hai. Prometheus ko kabhi aadha-adhura JSON nahi milega.

---

### C. `prometheus.yml`: Scrape vs Evaluation Interval
* `scrape_interval: 10s`: Prometheus remote Node Exporter endpoints (`http://<ip>:9100/metrics`) se kitni frequency par metrics pull karega.
* `evaluation_interval: 10s`: Prometheus ka internal alerting rules engine har 10s me PromQL condition expressions (e.g., `MemAvailable < 10%`) ko check karega.
* `job_name: "prometheus"` (`localhost:9090`): Prometheus server khud apne metrics expose karta hai (memory usage, ingestion rate). Yeh config Prometheus ko khud ko monitor karne ke liye scrape karti hai.

---

### D. Automated Test Coverage (`test_targets_generator.py`)
1. `test_generate_targets_empty`: Khaali nodes list par empty `[]` return hona chahiye (Zero division / crash prevention).
2. `test_generate_targets_formatting`: Node records schema-compliant Prometheus target dictionaries me convert hone chahiye.
3. `test_generate_targets_custom_port`: Default 9100 ke alawa custom port (e.g., 9200) specify karne par target me bind hona chahiye.
4. `test_atomic_write`: Temporary file (`.tmp`) generate ho, swap ho, aur process ke baad koi temporary file disk par na bache.
5. `test_export_inventory_e2e`: Isolated SQLite database create karke end-to-end read $\to$ format $\to$ atomic write verify karta hai.

---

## 5. Verification Commands

Practice code verify karne ke liye terminal me run karo:
```bash
python test_targets_generator.py
```
Expected output:
```text
PASS: test_generate_targets_empty
PASS: test_generate_targets_formatting
PASS: test_generate_targets_custom_port
PASS: test_atomic_write
PASS: test_export_inventory_e2e

ALL TARGETS GENERATOR TESTS PASSED!
```

