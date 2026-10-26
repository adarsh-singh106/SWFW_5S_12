# Fleet Manager Learning Curriculum

A first-principles, zero-burnout guide to building an industry-grade Linux Fleet Management platform.

---

## 🗺️ Master Curriculum Index

### Phase 1: Foundation & Architecture
* 📄 **[Document 01: Project Vision, First Principles & The 9-Step Engineering Loop](foundation/01-vision-and-first-principles.md)**\
  *Core problem, toy projects vs production systems, understand-to-improve loop.*
* 📄 **[Document 02: The 8 Engineering Pillars & Portfolio Strategy](foundation/02-engineering-pillars-and-portfolio.md)**\
  *Distributed systems, observability, Linux internals, security, and the 3-tier interview strategy.*

---

### Phase 2: Feature 1 — Node Inventory
* 📄 **[Document 03: Node Inventory & The Registration Flow](node-inventory/03-registration-flow.md)**\
  *Why inventory exists, saving a contact vs calling a contact, 3 actors, HTTP contract.*
* 📄 **[Document 04: Networking Reality Check & The Input Validation Contract](node-inventory/04-input-validation-contract.md)**\
  *Public vs Private IP (college Wi-Fi doubt), why frontend validation is bypassable, TCP port boundaries.*
* 📄 **[Document 05: Database Persistence & The Storage Engine](node-inventory/05-database-persistence.md)**\
  *RAM vs Disk, SQLite trade-offs, schema design, transactions, commit durability, SQL injection defense.*
* 📄 **[Document 06: Service Layer Integration & Unified Registration Flow](node-inventory/06-service-layer-integration.md)**\
  *Logical layers, validation + storage coordination, domain logic, and HTTP error mapping.*
* 📄 **[Document 07: The HTTP API Layer — Connecting the Web to the Service](node-inventory/07-http-api-layer.md)**\
  *Why browsers cannot call Python RAM, TCP socket listeners, HTTP request/response raw bytes, status codes (201/400/409/500), and FastAPI integration.*

---

### Phase 3: Feature 2 — Node Availability & Probing
* 📄 **[Document 08: Linux Connectivity Probing & The SSH Handshake](connectivity-probing/08-linux-probing-and-handshakes.md)**\
  *The 4 levels of probing (ICMP vs TCP vs SSH Banner vs Full Auth), RFC 4253 banner exchange, network failure taxonomy (ECONNREFUSED vs ETIMEDOUT), socket timeout traps, and the state transition machine.*
* 📄 **[Document 09: Background Health Probing & The Real-Time Dashboard](connectivity-probing/09-periodic-probing-and-dashboard.md)**\
  *Continuous autonomous health monitoring, offloading blocking socket I/O via `asyncio.to_thread`, the FastAPI lifespan context manager, and the single-page HTML operator dashboard.*

---

### Phase 4: Feature 3 — Metrics & Observability (Prometheus & Grafana)
* 📄 **[Document 10: Linux System Metrics Architecture & Node Exporter](metrics-observability/10-linux-metrics-and-node-exporter.md)**\
  *The `/proc` virtual filesystem, raw CPU ticks (jiffies), `MemFree` vs `MemAvailable`, why relational SQLite explodes under telemetry load, TSDB compression, Node Exporter, and the Pull vs Push model.*
* 📄 **[Document 11: The Prometheus Scrape Pipeline & Grafana Dashboards](metrics-observability/11-prometheus-and-grafana-pipeline.md)**\
  *The 3-tier metrics pipeline, `prometheus.yml` configuration, dynamic service discovery (`file_sd_configs`), PromQL queries (CPU%, RAM%, up), and Grafana visualization.*

---

## 🛠️ Hands-on Practice Series

* 💻 **[Practice 01: SSH Port Validator & Code Review](node-inventory/practice/practice-01-port-review.md)**\
  *Student-written validator in [`validate_port.py`](node-inventory/practice/validate_port.py), 5 tricky Python edge cases, `{value!r}` explanation, and `isinstance()` vs `type()` history.*
* 💻 **[Practice 02: SQLite Storage & Create/Read Operations](node-inventory/practice/practice-02-sqlite-storage.md)**\
  *Hands-on SQLite table creation, parameterized insertion, duplicate prevention, and disk persistence verification.*
* 💻 **[Practice 03: Service Layer Integration](node-inventory/practice/practice-03-service-layer.md)**\
  *Writing `node_service.py` to combine input validation and persistence into a single unified onboarding workflow.*
* 💻 **[Practice 04: HTTP API Layer & Endpoint Verification](node-inventory/practice/practice-04-http-api.md)**\
  *Building `app.py`, launching FastAPI on port 8000, and testing live HTTP requests with `curl` and interactive docs.*
* 💻 **[Practice 05: The SSH Banner Probe Engine](connectivity-probing/practice/practice-05-probe-engine.md)**\
  *Building a non-blocking network socket probe, extracting RFC 4253 SSH banners, and differentiating connection refusal from timeouts.*
