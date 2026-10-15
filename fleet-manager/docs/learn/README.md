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

---

## 🛠️ Hands-on Practice Series

* 💻 **[Practice 01: SSH Port Validator & Code Review](node-inventory/practice/practice-01-port-review.md)**\
  *Student-written validator in [`validate_port.py`](node-inventory/practice/validate_port.py), 5 tricky Python edge cases, `{value!r}` explanation, and `isinstance()` vs `type()` history.*
* 💻 **[Practice 02: SQLite Storage & Create/Read Operations](node-inventory/practice/practice-02-sqlite-storage.md)**\
  *Hands-on SQLite table creation, parameterized insertion, duplicate prevention, and disk persistence verification.*
* 💻 **[Practice 03: Service Layer Integration](node-inventory/practice/practice-03-service-layer.md)**\
  *Writing `node_service.py` to combine input validation and persistence into a single unified onboarding workflow.*
