# Distributed Linux Fleet Management

SETU 2026 · Project Submission Report · SWFW_5S_12

### 1. Student Details

| Field | Value |
| --- | --- |
| Student Name | Adarsh Singh |
| Course / Program | B.Tech in Computer Science and Engineering |
| Semester / Year | Fifth semester / third year |
| Domain | Software / Firmware |
| Email ID | bt24f05f057@geca.ac.in |
| Institution | Government College of Engineering, Aurangabad |

### 2. Project Details

| Field | Value |
| --- | --- |
| Problem Statement No. | SWFW_5S_12 |
| Project Title | Distributed Linux Fleet Management |
| Report Revision | 11 November 2026 |

## 3. Work Done

Implemented persistent node inventory, guided SSH identity enrollment, availability observations, bounded diagnostic operations, Prometheus collection and Grafana provisioning. The following sections explain workflows, engineering decisions, measured results and outstanding live verification. Source-inspected implementation is not blanket deployed acceptance.


### Implementation-depth edition
This separate edition adds twelve technical sections (D1-D12) and ten detailed vector views. It preserves the overview, measured-results qualifiers and required report sections. Read D1-D10 for runtime/failure mechanisms and D11 for evidence reconciliation.

### Reading map and evidence vocabulary

This edition expands the engineering explanation without changing the application. Its overview and implementation-depth diagrams describe inspected mechanisms, not new deployment experiments. Read the system from intent to runtime, then from failures to evidence.

| Topic | Sections | Question answered |
| --- | --- | --- |
| Scope and architecture | 3.1–3.3 | What is in the system, and where do trust and execution boundaries lie? |
| Runtime workflows | 3.4–3.8 | How do onboarding, checks, commands and metrics behave, including failures? |
| Data and recovery | 3.9–3.10 | What persists, and what is safe to restore? |
| Security and interface design | 3.11–3.13 | What can the operator do safely, and how is uncertainty communicated? |
| Verification and results | 3.14–3.17; 4 | What was actually measured, and what remains unsupported? |
| Build and traceability | Appendices A–B | How can another engineer reproduce and audit the report? |

**Implemented / source-inspected** means the mechanism exists in code. **Verified locally** means a retained or explicitly dated local execution supports it. **Historical live observation** means a retained remote response supports only its time and context. **Mocked QA** means SSH/Prometheus were fixtures. **Proposed / unverified** is not an achieved feature.

Diagram grammar: blue = controller/control records; teal = telemetry or confirmed workflow result; amber = decision, limit or operator gate; red = error/uncertainty. Text labels carry the meaning without relying on color. Each figure is a separate view, not a claim that all boxes are independent services. Architecture views are C4-inspired, not formal C4 certification.

## 3.1. Requirements, scope and acceptance contracts

The official problem is web-based management of multiple remote Linux machines. The controller supports a small fleet and one administrative identity; Prometheus and Grafana are mandatory. A three-node reference demonstration is not a measured fleet-size ceiling.

| Requirement | Implemented mechanism | Acceptance evidence still needed |
| --- | --- | --- |
| Onboard/manage nodes | Validated persistent inventory; guided fingerprint enrollment; connectivity checks | Independent fingerprint comparison and authenticated results for deployed nodes |
| Collect/store/visualize metrics | Node Exporter → Prometheus TSDB → Grafana; native fixed-query health views | Genuine rendered Grafana panels and retained time-range queries |
| Availability/failure handling | Periodic bounded SSH checks; timestamped observations; freshness interpretation | Isolated independent-host outage with healthy peers and recovery timeline |
| Controlled commands | Four-action catalog; pinned SSH; deadlines; persisted outcomes | Raw request/output/audit correlation on each deployed host |

**Non-goals of the implemented baseline:** unrestricted shell, service repair, automatic remote replay, multi-administrator RBAC, distributed worker coordination and an HA controller. Node inventory registration does not automatically authorize SSH or prove that the exporter is scraping.

**Quality attributes:** correctness means truthful state and output; safety means explicit identity and bounded actions; reliability means bounded resource use and restart reconciliation; maintainability means routes/services/adapters/repositories; operability means classified failures and audit lookup. These are design goals whose achieved extent must be assessed separately.

The implementation uses Python 3.12, FastAPI, Paramiko, SQLite WAL and browser ES modules. Managed hosts require sshd, an authorized non-root user and Node Exporter; no custom fleet agent is installed. Source: AGENTS.md; docs/PROJECT-CHARTER.md; source routes and operation catalog. Acceptance contracts above are evaluation criteria, not a declaration of live completion.

## 3.2. System context and responsibility separation

![Figure 1. System context: operator, controller, managed hosts and independent telemetry.](diagrams/engineering-context.svg)

The controller owns inventory, host identity enrollment, SSH observations and diagnostic execution records. Prometheus owns metrics collection and time-series storage. Grafana queries Prometheus rather than reading the inventory database. The browser also receives a bounded native health projection through the controller.

Separating SSH and exporter paths prevents a misleading single healthy/unhealthy verdict: one can succeed while the other fails. A collector outage is not automatically a Linux host outage. A registered inventory node is also not proof that a Prometheus target is configured correctly.

The design chooses a modular monolith for the controller instead of distributing small use cases across services. This keeps deployment and transactions understandable, at the cost of a controller failure domain and process-local coordination. Prometheus and Grafana remain separate required services. Source: src/fleet_manager/main.py; inventory, connectivity, operations and health modules; monitoring/ configuration.

## 3.3. Deployment, process ownership and trust boundaries

![Figure 2. Reference runtime boundaries, endpoint roles and single-worker constraint.](diagrams/engineering-deployment.svg)

The supplied systemd unit launches Uvicorn at 127.0.0.1:8000 with exactly one worker. The service runs as fleet-manager with no new privileges, an empty capability set, read-only configuration and writable state under /var/lib/fleet-manager. These are configured hardening controls; their presence is not proof that the unit is deployed or that all exposure paths are safe.

Process-local admission locks, in-memory sessions and restart reconciliation make multiple application workers unsafe without a separately engineered coordination design. A newly started worker can otherwise mark another worker's active operation UNCERTAIN. Scaling therefore cannot be reduced to increasing --workers.

The UI's Grafana link currently points to browser loopback 127.0.0.1:3000. A remote evaluator needs a matching tunnel or corrected deployment configuration; do not assume that clicking it reaches controller-host Grafana. Verify actual listeners, tunnels, firewall rules and credentials before external exposure. Source: deploy/fleet-manager.service; main.py lifespan; ui/templates/dashboard.html.

## 3.4. Detailed onboarding and host identity workflow

![Figure 3. Onboarding sequence with explicit operator trust decision and authentication boundary.](diagrams/engineering-onboarding.svg)

POST /api/nodes returns 201 for inventory creation; duplicate endpoints return 409. The onboarding read can return HTTP 200 with CONFIGURATION_ERROR: transport success does not mean setup success. Host-key scanning performs key exchange without authenticating or enrolling trust.

The confirmation binds node ID, address, port, configuration revision and fingerprint, with a 300-second lifetime. Enrollment re-fetches the presented key, rejects a changed or conflicting identity, then atomically replaces known_hosts. The administrator must compare the fingerprint through an independent trusted channel before enrollment. Manual public-key authorization remains a separate target-side step.

**Important implementation limitation:** confirmation validation currently uses Python assert statements (connectivity/service.py, validate_confirmation). Optimized Python execution can remove them. The report therefore does not claim unconditional enforcement; replace assertions with explicit checks in a separately approved security change and add optimized-mode regressions. No such application edit is made here.

Source: inventory/router.py; connectivity/router.py, service.py, trust.py and readiness.py. READY means successful setup history for a current revision, not continuous reachability.

## 3.5. Availability states and honest interpretation

![Figure 4. Ordered display interpretation: missing, invalid, stale and fresh outcomes; setup is separate.](diagrams/engineering-availability.svg)

derive_status evaluates missing observations first, then invalid/future timestamps, then expiration, then the observed outcome. The default TTL is 180 seconds; age greater than TTL becomes STALE. CONNECTED becomes REACHABLE; connection refusal/timeout becomes UNREACHABLE; other fresh failures become CHECK_ERROR.

Setup uses configuration revision, pinned identity, credential configuration and successful authentication history. PENDING_SETUP, HOST_KEY_REQUIRED, AUTHENTICATION_REQUIRED, CONFIGURATION_ERROR and READY explain onboarding progress. These are not mutually interchangeable with reachability. A correctly configured node can later be unreachable; a fresh SSH response says nothing by itself about CPU saturation.

Every observation should be interpreted with its timestamp, outcome and current revision. Retaining the last observation when stale is useful context, but presenting it as current would hide uncertainty. Source: connectivity/freshness.py, readiness.py, models.py and service.py.

## 3.6. Scheduler, bounded capacity and failure isolation

### A monitoring cycle, step by step
- Startup initializes repositories, reconciles interrupted operations and starts the in-process scheduler when enabled.
- The first sweep waits a jittered interval unless an explicit initial delay is configured. Defaults: 60-second interval, ±10% jitter, 180-second observation TTL.
- Each cycle enumerates inventory and schedules bounded checks. The scheduler prevents its own overlapping work for a node; the shared executor enforces connectivity capacity.
- A check records the configuration revision before execution and rechecks afterward. A changed configuration removes the revision association rather than validating the new setup with an old check.
- The result is appended with a completion timestamp. Individual failures are handled without declaring all peers failed.
- After the sweep finishes, the scheduler sleeps again. This is interval-after-work scheduling, not an exact fixed-rate guarantee.

| Boundary | Current mechanism | Engineering consequence |
| --- | --- | --- |
| SSH observation worker | Default connectivity capacity 4; 12-second total worker deadline | Bounds controller waiting; does not prove any fleet-size throughput |
| Same node contention | Conflicting check admission can return 409 | Operator should inspect current work, not launch overlapping checks |
| Global contention | Exhausted admission can return 429 | Reject rather than accumulate unbounded work |
| Freshness | Default TTL 180 seconds | Slow cycles can age data even if polling is nominally 60 seconds |
| Browser refresh | Authenticated fleet refresh every 10 seconds | Refreshes display; does not trigger a new SSH observation each time |
| Recovery | Later automatic sweep re-observes a returning endpoint | Observation recovery, not automatic host repair or command replay |

For N nodes, concurrency C and slow-check duration T, a rough batch lower-bound intuition is ceil(N/C) × T plus interval and overhead; this is not a measured SLA. Actual scheduling/admission behavior must be benchmarked. No availability SLO, fleet capacity or detection percentile is established here. Source: config.py; connectivity/scheduler.py, executor.py and service.py; ui/static/js/app.js.

## 3.7. Controlled operation and audit lifecycle

![Figure 5. Operation workflow, rejection boundaries, uncertain completion and restart handling.](diagrams/engineering-operations.svg)

Only system.uptime, system.memory, system.disk and service.status are accepted. Typed arguments are validated before compilation; disk paths reject traversal/whitespace and service names use a restricted pattern. The catalog uses fixed command templates and quoting, not a browser-supplied shell program.

The executor reserves per-node/global capacity and spawns a dedicated worker. The on_start callback persists RUNNING before the request is sent to the worker. A rejected request creates no operation row. A successfully returned record uses HTTP 200 even when its outcome is FAILURE or TIMEOUT; inspect the outcome and failure category.

If an admitted operation has no confirmed response, HTTP 503 includes its operation ID and lookup URL with a do-not-replay message. Local completion writes may be retried; those retries are not remote execution retries. On startup, orphaned RUNNING records become UNCERTAIN / CONTROL_PLANE_RESTARTED. Source: operations/catalog.py, executor.py, service.py, router.py, transport.py and repository.py; main.py.

## 3.8. Observability architecture and missing-data semantics

![Figure 6. Resource telemetry and controller telemetry, separated from SSH observations.](diagrams/engineering-metrics.svg)

The checked-in Prometheus configuration uses a 5-second scrape interval, 4-second scrape timeout, self-monitoring, controller /metrics and Node Exporter file discovery. Five historical healthy targets are supported by the retained response; the diagram does not turn that snapshot into a time-range retention test.

The native health path restricts queries to registered nodes and predefined expressions, bounds upstream requests and response size, and reports unavailable/stale series rather than false zero values. It is not an arbitrary PromQL proxy. Grafana is a different visualization client; native charts are not a substitute for rendered Grafana acceptance evidence.

For diagnostic monitoring, review latency, traffic, errors and saturation (external design reference R3). Existing counters/histograms can support investigation, but no complete alerting/SLO deployment is claimed. Preserve sample timestamps, target identity and query context when capturing evidence. Source: monitoring/prometheus/prometheus.yml; src/fleet_manager/metrics/health.py and health_router.py; metrics/telemetry.py; monitoring/grafana/.

## 3.9. Data model, consistency and audit limitations

![Figure 7. SQLite control entities and cardinalities; metric time series stay in Prometheus.](diagrams/engineering-data.svg)

Inventory owns endpoint identity; observations are append-only history associated with nodes, with optional configuration validation. Operation records preserve requested/started/completed times, action, sanitized arguments, outcome, exit code, bounded output, truncation and audit metadata. Credential storage is a separate singleton; sessions are not persisted in this database.

SQLite WAL supports the compact controller, but writes remain a serialized resource. Per-repository connections enable foreign-key enforcement. Schema/integrity validation and short control transactions matter more than adding a second metrics store. There is no database-level tamper-evident or immutable audit guarantee: privileged file access can change records. Shared-token/session-admin metadata does not establish named-user nonrepudiation.

Source: inventory/repository.py; connectivity/repository.py; operations/repository.py; security/repository.py; main.py. The diagram omits nonessential columns but preserves entity relationships; it is not a new schema proposal.

## 3.10. Backup, restore and recovery boundaries

![Figure 8. Online backup and explicitly offline restore; verification gates remain operator responsibilities.](diagrams/engineering-recovery.svg)

The backup utility uses sqlite3.Connection.backup(), validates integrity/foreign keys/schema, creates a digest/count/timestamp manifest, and publishes the database via replacement. Scheduled retention is one latest baseline, not multi-generation disaster recovery. A digest detects mismatch against the manifest; it does not authenticate an attacker-controlled manifest.

The runbook requires stopping database users and backup timers/services, checking handles, validating the snapshot, retaining a pre-restore safety copy, then restoring offline. A colliding safety snapshot aborts instead of silently overwriting it. After startup, compare inventory and history, inspect reconciliation outcomes and re-observe nodes.

Restoring the control database does not restore private keys, known_hosts, Prometheus TSDB, Grafana data, systemd configuration or remote hosts. Protect and recover those assets separately with authorized procedures. Do not infer measured RPO/RTO or deployed restore success from local utility tests. Source: scripts/backup_restore.py; deploy/fleet-manager-backup.*; docs/DEPLOYMENT-RUNBOOK.md sections 8–9.

## 3.11. Security model, threats and residual risks

| Threat / failure | Existing mechanism | Residual risk or limit |
| --- | --- | --- |
| Unauthorized API access | Bearer-token or authenticated browser-session gate | Single administrative identity; no RBAC or per-person attribution |
| Cross-site write request | Cookie-authenticated writes require CSRF validation | Transport, origin and deployment configuration still need verification |
| Host impersonation | Explicit fingerprint comparison and pinned known_hosts | Operator must use an independent trusted channel; confirmation assert caveat remains |
| Shell injection | Four fixed actions, typed/restricted arguments, quoted compilation | Target executable behavior and account privileges remain relevant |
| Resource exhaustion | Bounded admission, deadlines, bounded output and child workers | Not a distributed rate limit or established Internet-facing abuse defense |
| Unknown remote completion | UNCERTAIN outcome, operation lookup, no automatic remote replay | Cannot guarantee exactly-once effects or termination of remote processes |
| Database modification | File permissions / systemd isolation / persisted audit fields | Audit is not cryptographically immutable |
| Controller crash | Startup RUNNING reconciliation; systemd on-failure restart | Single controller remains a failure domain; sessions are lost |

**Authentication precedence:** an explicit Authorization header takes precedence; an invalid bearer does not fall back to a valid cookie. Mandatory password change blocks ordinary node workflows until resolved. Avoid describing shared token digest prefixes as human operator identity.

**Deployment boundary:** use non-root target credentials; keep secrets out of reports/source control. Do not expose the loopback-oriented reference deployment without a separate access/transport review. No security certification or penetration-test completion is claimed.

Prioritized follow-up, not implemented by this report: explicit confirmation checks with optimized-mode tests; endpoint/access review; named operator identities if required; coordinated worker ownership before horizontal scaling; authenticated off-host audit/backup only if justified. Source: security/auth.py and sessions; connectivity/service.py and trust.py; operation catalog/executor; systemd unit.

## 3.12. Information architecture and operator workflow

![Figure 9. Task hierarchy and progressive disclosure based on the existing dashboard.](diagrams/engineering-information.svg)

The intended journey is orient → investigate → act → verify. Fleet summaries show where attention is needed; selected-node detail preserves endpoint, setup, observation and measurement context; operations expose fixed action selection, preview and results/history rather than a terminal.

Progressive disclosure keeps raw output and detailed history available without forcing them into every overview card. Related information should stay together: setup state beside trust/auth guidance, freshness beside observed status, and operation result beside its ID and timestamps. This is an explanation of the current information model, not a claim that every improvement below is already implemented.

One dashboard plus registration drawer and dialogs avoids a large navigation hierarchy. A 10-second UI refresh and separately scheduled observations are intentionally explained as different clocks. Preserve selected-node context and avoid presenting a refresh timestamp as the actual measurement time. Source: ui/templates/dashboard.html; ui/static/js/app.js, fleet.js, node-onboarding.js, operations.js and history modules (see source index for exact files).

## 3.13. Design principles and usability review

| Principle | Concrete application / source mechanism | Verification or limitation |
| --- | --- | --- |
| Visibility of system status | Separate setup, observation outcome, freshness and operation result | Existing state models; not a single misleading green badge |
| Recognition over recall | Fixed action choices, labeled fields, command preview and guidance | Interface screenshots are mocked QA, not live action evidence |
| Error prevention | Input validation, explicit identity enrollment, no unrestricted shell | Server-side rules remain authoritative |
| Progressive disclosure | Overview → node detail → history/output | Source-inspected IA; no usability-study result claimed |
| Feedback without interruption | Live status/alerts, compact toasts and inline configuration guidance | Manual assistive-tech behavior not freshly audited |
| Focus and keyboard ownership | Named dialogs, background inert state and focus restoration | Source mechanisms, not WCAG conformance certification |
| Non-color meaning | Text status/reason plus visual differentiation | Report diagram labels preserve meaning in grayscale |
| Evidence context | Keep target/time/outcome/source beside values | Report requirement; live traces still incomplete |

W3C references R2 identify use of color, visible focus and status messages as relevant accessibility criteria. The existing modal ownership module and labeled/live interface elements provide implementation hooks, but claiming conformance requires contrast, keyboard, zoom/reflow and assistive-technology testing. Do not infer that browser assertion counts cover all accessibility criteria.

**Visual system used in this report:** consistent typography, restrained semantic colors, numbered views, labeled arrows, generous spacing and one main question per diagram. Tables compare mechanisms with consequences rather than decorating pages. Captions state whether a figure is source-derived or mocked.

**Focused usability review still needed:** can a new operator distinguish STALE from UNREACHABLE, recover from host-key mismatch without blindly trusting, and find an UNCERTAIN operation without re-running it? These are proposed evaluation tasks, not completed student or user studies. Source: dashboard.html; dialog-ownership.js; node-onboarding.js; CSS focus styles; references R1–R2.

## 3.14. Design decisions and explicit trade-offs

| Choice | Why it fits this project | Cost / rejected simplification |
| --- | --- | --- |
| Python / FastAPI / Paramiko | Existing stack keeps HTTP contracts, SSH and tests inspectable | Packaging/process overhead; not a claim of superior fleet throughput |
| Modular controller | Routes at boundary, use cases in services, SQL in repositories | Module boundaries need discipline; fewer deployment pieces than microservices |
| SQLite control store | Small-fleet persistence with simple deployment and transactions | Single writer/controller and backup operational constraints |
| Prometheus + Grafana | Required collection/storage/visualization responsibilities | Separate configuration, target identity and access paths to manage |
| Separate observation/setup/resource signals | Prevents unsupported health conclusions | More states to explain in the UI |
| Strict SSH identity enrollment | Avoids implicit trust-on-first-use during diagnostics | Requires independent fingerprint comparison and operator action |
| Process-bounded operations | Local deadline enforcement and worker cleanup | Child process cost; remote stop cannot be proven |
| No automatic remote replay | Preserves safety under unknown completion | Operator investigation required; not exactly-once semantics |
| Vanilla browser modules | Matches current code, keeps dependencies low | Manual state/focus discipline and regression coverage remain necessary |

These are reconstructed explanations tied to inspected implementation and existing ADRs, not newly accepted architecture decisions. Existing ADRs remain authoritative for historical rationale; where an original decision record is absent, the consequence above is analysis rather than invented author intent.

**Scaling path, proposed only:** first measure representative HTTP/SSH workloads and sweep durations; tune within the single-worker contract; only then introduce durable work ownership/leases, identity and storage changes if measurements justify them. Adding queues, Kubernetes or microservices without a demonstrated bottleneck is not evidence of engineering maturity.

Source: docs/decisions/0001–0007; main.py; repositories; operation executor; browser modules. See the source index for hashed paths inspected during this edition.

## 3.15. Verification strategy and failure matrix

![Figure 10. Evidence pipeline with distinct implementation, local, mocked and live evidence classes.](diagrams/engineering-verification.svg)

| Failure scenario | Expected behavior | Evidence class / limit |
| --- | --- | --- |
| Unknown host key / changed identity | Do not silently enroll; explain blocked trust | Code and local tests; independent deployed comparisons still needed |
| Authentication or DNS failure | Classified observation; do not call host dead | Local contracts; real failure topology unestablished |
| Capacity saturation | Bounded rejection; cleanup after work release | Controlled in-process benchmark, not HTTP/SSH load |
| Deadline / transport loss | TIMEOUT or UNCERTAIN; no blind replay | Code and operation tests; remote termination unproven |
| Controller restart mid-operation | Orphan RUNNING → UNCERTAIN | Source/test boundary, not a complete deployed interruption trace |
| Missing metric / collector outage | Unavailable/stale, never fabricated zero | Mock browser/local contracts; genuine Grafana gaps remain |

Every live capture needs target/build/time, raw requests and results, operation IDs, unaffected peer behavior and cleanup/recovery evidence. No new cloud experiment is authorized or performed in this edition.

## 3.16. Measured results and interpretation

### Historical monitoring snapshot — 8 November 2026

The retained controller-validation response contains Prometheus target health, last-scrape timestamps and durations. The table below transcribes the observed response, not a newly executed cloud query. Every listed target has an empty lastError and a five-second scrape interval.

| Target | Instance | Last scrape, UTC | Duration, ms | Health |
| --- | --- | --- | --- | --- |
| Fleet Manager | 127.0.0.1:8000 | 09:49:11.291883189 | 8.998 | up |
| Node A exporter | 10.160.0.5:9100 | 09:49:10.058377576 | 132.629 | up |
| Node B exporter | 10.160.0.3:9100 | 09:49:12.432012612 | 126.651 | up |
| Node C exporter | 10.160.0.4:9100 | 09:49:11.935733210 | 119.757 | up |
| Prometheus | localhost:9090 | 09:49:12.296315070 | 6.118 | up |

This establishes successful scrape observations in the retained response. It does not establish continuous availability, the deployed application build, rendered Grafana panels or a later failure/recovery experiment. Source: controller-validation.txt, historical run 20261108T1515; the accompanying evidence manifest records its hash.

### Capacity behavior — controlled local experiment, 9 November

The admission benchmark filled four operation slots, held them open, attempted twelve further requests, then released admitted work. It measured OperationService entry to rejection using time.perf_counter_ns. There was one measurement round, no warmup, and controlled in-process transport—not HTTP, SSH or remote hosts.

| Observation | Result |
| --- | --- |
| Requests / admitted / rejected | 16 / 4 / 12 |
| Peak active operations | 4 |
| Rejection latency p50 / p95 | 0.716 / 0.958 ms |
| Active operations / threads remaining after release | 0 / 0 |

The result supports bounded admission and cleanup for this controlled workload. It does not measure production throughput, network latency or independent-node isolation. Percentiles describe only twelve rejections in one round, not a fleet-capacity estimate. Source: admission-baef7aca7ebf4b3b80383bf99aa722b1/results.json.

## 3.17. Testing, chronology and unresolved verification

| Layer / date | Recorded execution | What it demonstrates |
| --- | --- | --- |
| Python, 9 November | 535 passed; seven warnings; 150.55 s | Covered local backend/security/persistence contracts |
| Frontend, 9 November | 74 pass executions / 37 unique tests | Module behavior, repeated through compatibility entry points |
| Normal browser QA, 9 November | Successful retry; 126 assertions; cleanup true | Mocked workflow and interface behavior |
| Automated acceptance, retained run | 2 local passes / 6 skipped / 6 simulated | Local contracts only; live gates remain unmet in that run |
| Authentication, 11 November | 25 passed; seven warnings; 4.70 s | Focused local authentication regressions |
| Operation units, 11 November | 33 passed; one warning; 1.65 s | Focused local operation behavior |

The browser's first normal-flow attempt failed with a Windows PermissionError before the driver launched; the subsequent run succeeded. Retaining that distinction is more useful than describing every invocation as successful. Existing warnings remain visible rather than being presented as a warning-free run.

### Chronology without overclaiming

The November 8 raw response supports historical monitoring. November 9 cloud safety records did not perform fresh SSH or application acceptance. November 10 checkpoint and execution summaries report a later deployment and four successful operation examples. The older blocked run does not disprove those later activities, but the newer summary alone does not establish every fault-injection and recovery scenario. This revision therefore separates those records instead of declaring all live gates closed.

### Required next live evidence

| Scenario | Evidence needed | Status in this report |
| --- | --- | --- |
| Three-node onboarding | Independently verified fingerprints plus authenticated results | Not fully embedded |
| Grafana | Actual rendered panels, time range and Prometheus datasource | Not established |
| Peer isolation | Before/during/after one independent VM outage, peers and controller measured | Not established |
| Automatic recovery | Timestamped scheduler observations and exporter recovery | Not established |
| Remote operations | Real response/output linked to target, build and audit UUID | Later summary only |
| Deployed restore | Restore real rows into separate destination and verify integrity/counts | Not established |


## D1. Runtime architecture: modules are not microservices

![Figure D1. Runtime ownership and communication boundaries; separate workers do not imply separate application services.](diagrams/depth-runtime.svg)

The application is a modular controller, not a distributed control-plane cluster. FastAPI routers form the HTTP boundary; services coordinate use cases; repositories own SQL. The connectivity scheduler and browser session store live inside one application process. Diagnostic child processes provide a killable local execution boundary, not a durable queue or another independently deployed service.

### One request across the boundaries
- The authenticated operator selects a registered node and a catalog action. The router accepts structured input rather than a shell command.
- The service resolves inventory and validates the action. The executor admits bounded work and starts a local worker waiting on standard input.
- A callback commits the RUNNING audit record before the parent sends the execution request to the worker. The worker then uses SSH to execute on the remote machine.
- The service persists the classified result; the browser displays the returned operation record and can inspect history.

The single-worker restriction is functional: adding Uvicorn workers would duplicate schedulers and split in-memory sessions and admission tracking. Horizontal scaling needs shared coordination and a redesigned ownership boundary; it is not achieved by changing a worker-count flag.

**Why this design:** a small-fleet controller can keep deployment simple while isolating blocking transport work. Its cost is a single control-plane failure domain. A child-process deadline bounds local work but cannot prove termination of a remote command.

**Source anchors:** src/fleet_manager/main.py lifespan; connectivity/scheduler.py::ConnectivityScheduler; operations/executor.py::ProcessOperationExecutor; security/session.py::SessionStore; deploy/fleet-manager.service.

## D2. Host identity: a scan is not a trust decision

![Figure D2. Explicit enrollment with rejection branches; confirmation assertion caveat applies to the validation gate.](diagrams/depth-onboarding.svg)

Registration validates and stores an endpoint without proving DNS resolution, host identity, credentials or reachability. The scan performs key exchange without authenticating and returns the presented fingerprint. An independent trusted console or equivalent channel must supply the fingerprint against which the operator compares it. Merely comparing two values delivered by the same potentially impersonated endpoint does not establish identity.

### What binds the confirmation
ConnectivityService.confirmation serializes node ID, address, SSH port, configuration revision, fingerprint and issue time, signs the payload with HMAC-SHA256, and returns encoded payload plus signature. The signing secret is service-instance-local. In ordinary Python execution, validation checks signature, binding and an age between zero and 300 seconds. Restart invalidates outstanding confirmations; confirmations are not consumed after use.

**Known implementation defect:** validate_confirmation uses assert for these three security checks. Python optimization can remove them. This is an authenticated enrollment weakness, not an unauthenticated login bypass. Re-fetching the key, matching the expected fingerprint and rejecting replacement of an existing different pin remain separate checks. The report does not claim the confirmation gate is unconditionally enforced; correcting it is outside this documentation-only increment.

### Persistence and concurrency
Enrollment takes a cross-process sidecar lock, re-fetches the presented identity, rejects a changed fingerprint, and reads the existing trust store fail-closed. Multiple matching entries are ambiguous even when duplicate keys are identical. An identical existing pin succeeds without replacement; a different existing pin cannot be rotated through this workflow. New enrollment preserves existing content and publishes through temporary-file replacement with fsync and POSIX metadata handling.

Controller public-key authorization on the node is a separate manual bootstrap action. Trusting the server does not grant the client access, and authorizing a client key does not identify the server.

**Source anchors:** connectivity/service.py::confirmation, validate_confirmation; connectivity/router.py::scan_host_key, trust_host_key; connectivity/trust.py::endpoint_identity, _read_store, _unique_key, enroll_host_key; connectivity/transport.py::ParamikoSSHTransport.verify.

## D3. Monitoring: scheduling is not the same as freshness

![Figure D3. Periodic observation flow, capacity skips, revision association and an independent read-time freshness decision.](diagrams/depth-monitoring.svg)

The scheduler uses an in-process asyncio task. Its default interval is 60 seconds with ten-percent jitter; the first cycle also waits unless explicitly configured otherwise. Each cycle reads inventory, creates bounded node-check tasks, gathers outcomes independently, and sleeps after the cycle. Therefore the interval is not a guaranteed maximum time between observations: check duration, contention and failures contribute additional delay.

The scheduler has a semaphore and an in-flight set; the shared connectivity executor has its own admission boundary. A busy node or exhausted capacity produces a skip/error path rather than an invented failed probe. One node's exception is handled without claiming all peers failed. Existing observations remain available and can expire naturally.

### Configuration changes during a check
The service captures the configuration revision before checking and compares it afterward. If configuration changed, the observation loses its revision association. A result from old credentials or a former trust configuration must not validate the new setup. The revision includes endpoint and credential/trust identity, so setup history is not an unconditional lifetime approval.

### A concrete interpretation example
Suppose a successful observation is stored at 12:00:00 UTC and no later check completes. With the default 180-second TTL, it remains fresh at 12:03:00; at 12:03:01 it is STALE because the code uses age greater than TTL. That does not prove the host went down at 12:03:01. It means the controller no longer has sufficiently recent evidence.

Reconnection is observed by a subsequent scheduled check. This is automatic observation recovery, not automatic host repair or remote-operation replay. Recovery latency has not been measured by the report's documentation build.

**Source anchors:** connectivity/scheduler.py::calculate_delay, run_cycle, _loop, stop; connectivity/service.py::check; connectivity/freshness.py::derive_status; config.py.

## D4. Three independent questions about a node

![Figure D4. Ordered SSH display interpretation. Setup readiness and Prometheus resource status are separate dimensions, not extra transitions in this classifier.](diagrams/depth-status.svg)

| Question | Inputs and interpretation | What it does not prove |
| --- | --- | --- |
| Is setup validated? | Current configuration revision, unique host pin, credential configuration and decisive authentication history | Current reachability or healthy resource use |
| What does the latest SSH observation support? | Observation existence, timestamp validity, age and outcome | Overall host/service health or exporter reachability |
| What resource data is available? | Prometheus target ownership, up sample, source timestamps and metric validity | SSH credentials, host pin validity or diagnostic success |

derive_status first handles a missing observation, then naive/future timestamps, then expiry, then the fresh outcome. CONNECTED maps to REACHABLE. CONNECTION_REFUSED and CONNECTION_TIMEOUT map to UNREACHABLE; other fresh failures map to CHECK_ERROR. The UI should not compress these into a single green/red claim about the entire machine.

The distinction matters operationally. A machine with a changed SSH host key may still export metrics. A host with valid setup history may be temporarily unreachable. A reachable host can have stale metrics if the exporter or scraper fails. Diagnosing these as different failures preserves useful information and avoids unsafe remediation based on a guessed cause.

**Boundary case:** no observation yields NOT_CHECKED. It is neither a successful check nor an unreachable result. A future timestamp yields CHECK_ERROR rather than silently extending freshness.

**Source anchors:** connectivity/freshness.py::derive_status; connectivity/readiness.py::derive_setup, configuration_revision; connectivity/service.py::fleet_status, setup; metrics/health.py::PrometheusHealth.node.

## D5. Remote operation: admission, dispatch and the audit barrier

![Figure D5. Detailed operation execution: a spawned worker waits for input until the initial audit commit succeeds.](diagrams/depth-operation.svg)

### Before dispatch
Action validation produces a sanitized argument record and a catalog-generated command. Per-node exclusion prevents simultaneous admitted operations on that node; the default global capacity is four. Same-node contention returns 409 and global saturation returns 429. These are admission outcomes, not evidence of remote execution failure.

The process executor serializes the request, prepares an allowlisted environment, takes its lock, checks shutdown/node/global admission and spawns a child with piped stdin/stdout and discarded stderr. It records the child as active. The on_start callback then persists RUNNING. Only after that callback returns does communicate send the request to the worker. Thus a local child may already exist before the audit commit, but the remote command has not yet been supplied to it.

If the initial database write fails, the executor's finally block attempts to kill/reap the local child. It does not proceed with command dispatch. If the worker cannot be spawned, no on_start callback occurs. These distinctions are stronger and more precise than saying merely 'audit logging is supported'.

### After dispatch
The remaining deadline subtracts elapsed monotonic time since executor startup. A timeout returns TIMEOUT and finally attempts local termination/reaping. A nonzero worker exit or malformed JSON is an infrastructure failure, not a remote exit code. Worker exit code 2 maps to configuration failure. Transport results separately carry outcome, failure category, exit code, bounded stdout/stderr and output_truncated.

When a terminal operation record is returned, HTTP 200 means the request produced a result record; the record may still say FAILURE or TIMEOUT. An admitted infrastructure exception can carry an operation ID and uncertain audit state. The operator should inspect that ID instead of pressing 'run again' blindly.

**Source anchors:** operations/catalog.py::validate_action; operations/executor.py::ProcessOperationExecutor.run, _terminate_and_reap; operations/service.py::OperationService.execute; operations/router.py; operations/transport.py.

## D6. The difficult case: command result exists, audit write fails

![Figure D6. Completion persistence recovery retries local writes only; controller restart reconciles remaining RUNNING rows without redispatch.](diagrams/depth-persistence.svg)

OperationService._complete attempts update_completion twice. If both writes fail, it retains a process-local pending completion with UNCERTAIN / UNAVAILABLE, preserves returned output fields, and raises StorageError carrying operation ID and persisted_outcome RUNNING. The durable database may still say RUNNING even though a worker result was received. That is a control-plane persistence problem, not permission to execute the remote action again.

recover_completions retries only the local completion write. It does not reopen SSH or resubmit the catalog command. Pending data is not a durable queue; a controller crash can lose it. Startup reconciliation then converts leftover RUNNING records to UNCERTAIN / CONTROL_PLANE_RESTARTED with a completion timestamp.

### Why not automatically retry every error?
A connection loss after dispatch cannot establish whether a command ran. Even though the current catalog is read-only, replaying work can still duplicate load and confuse the audit trail. Future actions could have side effects. The controller therefore preserves uncertainty instead of pretending to offer exactly-once execution.

| Failure location | Durable state or response | Safe interpretation |
| --- | --- | --- |
| Before worker admission | Rejection/configuration exception; no admitted record | No command dispatched by this attempt |
| Initial RUNNING write | Write error; local worker cleanup attempted | Request was not supplied to worker |
| Worker after dispatch | Terminal result or infrastructure exception | Inspect record/category; do not infer no execution |
| Completion write | RUNNING can remain; pending local repair | Retry persistence, not the command |
| Controller restart | RUNNING reconciled to UNCERTAIN | Historical result cannot be reconstructed as success |

Audit rows are mutable through completion updates and privileged database access. 'Durable audit' is not cryptographic immutability or named-user nonrepudiation.

**Source anchors:** operations/service.py::_complete, recover_completions; operations/repository.py::create, update_completion, reconcile_running; main.py startup lifecycle.

## D7. Telemetry: ownership, source time and missing samples

![Figure D7. Independent telemetry producers, target resolution and fixed-query health interpretation; application metrics are not the node-resource store.](diagrams/depth-telemetry.svg)

Prometheus scrapes Node Exporter directly for node resources and Fleet Manager /metrics for controller instrumentation. The checked configuration uses a five-second scrape/evaluation interval and four-second scrape timeout. File discovery refreshes target configuration. These configured values do not establish scrape success or long-term retention.

The native health endpoint does not accept arbitrary PromQL. It resolves a registered inventory node to an exporter target, checks ownership/ambiguity, and queries a fixed catalog. Queries include CPU idle rate converted to utilization, available/total memory, root-filesystem capacity, uptime, load and network rates excluding loopback/selected virtual interfaces. CPU and network rates use five-minute windows, not instantaneous measurements.

### Source time is not query time
_observation requests both a value expression and a companion source-timestamp expression. It joins by evaluation time, then emits the source timestamp. For multi-selector expressions, _source chooses the oldest current contributing source sample. This does not describe every sample in a five-minute rate window; it is a conservative freshness indicator for the current source selectors.

The source freshness threshold is 90 seconds, independently of the SSH observation TTL. A fresh up=0 target returns down without fabricated resource values. A stale target returns stale; invalid/ambiguous data returns unavailable. Histories span one hour at 150-second query steps and deduplicate repeated source timestamps. Displayed observation count is not exporter scrape count.

Nonfinite/negative measurements, percentages above 100, future sample timestamps and inconsistent capacity pairs are rejected. Invalid history measurements retain a null gap when their source position is valid. The chart must leave a disconnected segment rather than replacing missing values with zero or interpolating across an outage.

**Source anchors:** metrics/health.py::METRICS, _source, _sample, PrometheusHealth._observation, PrometheusHealth._node; metrics/health_router.py; metrics/telemetry.py::_collect_fleet_status; monitoring/prometheus/prometheus.yml; ui/static/js health/chart modules.

## D8. Data architecture: persistence is intentionally split

![Figure D8. Selected real columns, primary/foreign-key relationships, uniqueness and non-database stores. No invented database relationship connects administrator credentials to operation attribution.](diagrams/depth-data.svg)

Inventory nodes are unique by case-insensitive address plus SSH port. SQLite constrains nonempty names/addresses and valid integer ports. Connectivity observations reference nodes. A separate connectivity_validation row associates an observation with a 64-character configuration revision; that auxiliary relationship prevents old setup evidence from being applied blindly to new configuration.

Operation records reference nodes and contain action, JSON arguments, request/start/completion timestamps, outcome/category, exit code, stdout/stderr, truncation flag and JSON audit metadata. Database checks constrain outcomes and truncation. RUNNING is updated to completion, so operation rows are not append-only in the immutable-log sense.

administrator_credentials is a singleton constrained to id=1 with password hash, mandatory-change flag and timestamps. It has no SQL foreign key to operations. The reported metadata identifies session-admin or shared-token context, not a uniquely identified human.

### Separate durability boundaries
| Asset | Store | Recovery implication |
| --- | --- | --- |
| Inventory, observations, operations, administrator hash | SQLite, repository-owned SQL | Database backup covers these records |
| Host identity pins | known_hosts file | Recover separately; do not trust a restored database to recreate pins |
| SSH client private key | Protected filesystem | Secret, excluded from report/archive; separate authorized backup |
| Browser sessions, admission maps, pending completions | Process memory | Lost on restart; not restored from SQLite |
| Resource time series | Prometheus TSDB | Not stored in the controller inventory database |
| Grafana configuration/data | Provisioning files and Grafana store | Restore/verify separately |

Repositories use parameterized SQL, foreign-key enforcement and short transactions. Initialization checks schema version and uses explicit migration steps; schema validity is not inferred from a filename. This report inspected schema definitions, not a live production database.

**Source anchors:** inventory/repository.py::_SCHEMA; connectivity/repository.py::_SCHEMA, _VALIDATION_SCHEMA; operations/repository.py::_SCHEMA; security/repository.py::_SCHEMA; scripts/backup_restore.py.

## D9. Browser and API security are different paths

![Figure D9. Protected-route authentication precedence; setup/login have their own lifecycle and are not covered by this gate.](diagrams/depth-auth.svg)

If any Authorization header exists, the gate validates exactly one well-formed Bearer credential and compares digests in constant time. Invalid explicit bearer authentication does not fall back to a valid browser cookie. A valid bearer returns before the cookie-specific password-change/CSRF branches.

Without that header, a valid server-managed session is required. Session defaults are 30-minute idle and 12-hour absolute expiry, tracked with monotonic time. The store retains a session-token verifier; session CSRF material remains server-side. Session lookup refreshes activity before later route authorization checks. Sessions and login throttling are process-local, not a distributed identity service.

Cookie-authenticated protected mutations require a matching synchronizer token plus matching Origin, or Referer when Origin is absent. Missing origin information rejects. This is not a claim that every POST endpoint—including setup/login—passes through this gate. Password-change state restricts ordinary browser workflows until the lifecycle completes.

The browser cookie is HttpOnly and SameSite=Lax; Secure is conditional on an HTTPS request. This does not make a plain-HTTP deployment encrypted. Proxy address/scheme handling and external exposure require deployment review. Password hashes use Argon2, but that alone does not establish penetration-test completion or Internet-facing readiness.

The frontend uses same-origin credentials and attaches CSRF on mutations. On authentication failure it prompts for login without automatically replaying a remote operation. This preserves the distinction between restoring operator access and repeating work with unknown completion.

**Source anchors:** security/auth.py::require_operator_token; security/session.py::SessionStore, validate_csrf; security/router.py; security/passwords.py; ui/static/js/api.js.

## D10. Recovery is a set of boundaries, not one green tick

![Figure D10. Separate observation recovery, process reconciliation and offline database restore. None proves remote host repair.](diagrams/depth-recovery.svg)

| Recovery type | Actual mechanism | Remaining responsibility |
| --- | --- | --- |
| Observation after network returns | Subsequent scheduled SSH check persists a fresh observation | Independently measure outage, unaffected peers and recovery timing |
| Controller service crash | systemd restart policy plus startup initialization | Verify deployed configuration and restart behavior |
| Interrupted operation record | RUNNING to UNCERTAIN reconciliation | Inspect remote state; never silently replay |
| Failed completion write | Process-local retry of local persistence | Pending completion is lost on process crash |
| Database corruption/loss | Verified backup and explicitly offline restore | Protect credentials, pins, telemetry and service configuration separately |
| Failed remote host/service | Not automatic host repair | Operator diagnosis and authorized repair procedure |

The backup script uses SQLite online backup and validates integrity, foreign keys and schema. Restore is an offline procedure: stop database users and backup jobs, validate the snapshot, retain a non-overwriting safety copy, restore, restart, compare records and re-observe. A checksum detects changes relative to its manifest; it does not authenticate an attacker-controlled manifest.

The report does not invent recovery-point or recovery-time objectives. A local utility test does not establish deployed restore, and service startup alone does not establish that all four project requirements recovered.

**Source anchors:** scripts/backup_restore.py; docs/DEPLOYMENT-RUNBOOK.md; operations/repository.py::reconcile_running; connectivity/scheduler.py; deploy/fleet-manager.service and backup units.

## D11. Evidence reconciliation and acceptance map

This edition separates implementation depth from demonstration completeness. A confidently written checklist cannot substitute for the request, response, timestamps, environment and build identity supporting it.

| Claim | Inspected artifact | Defensible status |
| --- | --- | --- |
| Historical Python test gate | submission/evidence/final_python.txt | 535 passed, seven warnings, exit 0 on 9 November; historical local result |
| Automated acceptance completed | submission/evidence/acceptance-final.json and .txt | Explicit --mock run, exit 2; not live acceptance |
| Exporter scraping worked | .local/live-gcp-verification/20261108T1515/controller-validation.txt | Historical five-target up snapshot, including three exporters; not current health |
| November 10 deployed operations and complete sign-off | November 10 learning/checklist entries | Reported; matching full raw traces not established by this inspection |
| Genuine Grafana visualization | Provisioned dashboard/configuration exists | Live rendered panels remain an evidence gap |
| Independent-host outage and recovery | Required manual acceptance procedure | Matching complete fault/recovery capture remains a gap |

### What would close the four official requirements
- Onboarding: deployed build identity, registered independent nodes, independently compared fingerprints, explicit enrollment and successful authenticated checks.
- Metrics: target list, stored time-range samples and actual rendered Grafana panels with node/time context.
- Availability: a bounded isolated-host interruption, healthy peers, timestamped failure/freshness behavior and observed automatic reconnection.
- Operations: request/action/node, raw returned output, operation ID and matching persisted history, including catalog rejection and meaningful failure behavior.

No new live experiment is performed by this edition. Existing reported successes are not asserted to be false; they remain uncorroborated where underlying captures have not been located. Mocked screenshots retain their labels. Source hashes identify inspected bytes, not a deployed build unless deployment identity is separately established.

## D12. Evaluator walkthrough and reproducibility

### A five-minute reading path
- Start with requirements and architecture. Identify controller, remote machines and the independent telemetry path.
- Follow onboarding and distinguish server identity from client authorization.
- Follow one diagnostic through admission, the audit barrier and SSH dispatch.
- Explain a lost-result scenario: why UNCERTAIN is more accurate than success/failure and why persistence retry must not replay the command.
- Read the freshness classifier and metric-source timestamps. Explain why stale or missing is not zero.
- Finish with measured results, evidence gaps and the selected recovery boundaries.

### Technical review checklist
Every detailed view names its source anchors. Arrows represent control/data flow; branch labels identify rejection/uncertainty instead of hiding it. Overview views stay separate from detailed runtime views so module boundaries, processes and machines are not confused. The depth diagrams are embedded as SVG resources in the self-contained HTML and rendered into the PDF, preserving selectable vector text rather than screenshots of diagrams.

### Rebuilding this edition
From the existing Windows repository environment, execute the local builder with the repository Python: C:\Users\adars\Desktop\ZOHO\SWFW-12-Sem5\.local\build_depth_report.py. The build creates a separate edition, not a replacement release ZIP. Its manifest records source/report/image hashes and output bytes. Validation renders every page, checks resource completeness, text boundaries, diagram font size and the conservative 20,000,000-byte ceiling.

The PDF is the upload candidate. Markdown, HTML, diagrams, manifest and validation receipt are review/reproduction companions. Student identity, selected project/account and portal timezone must still be checked by the student. This documentation increment does not demonstrate independent student understanding or video completion.

## 4. Output / Screenshots

### 4.1. Onboarding and diagnostics

These are retained browser-QA captures with mocked SSH/Prometheus, not live GCP screenshots. Labels such as alpha-ready and loopback endpoints identify the demonstration environment. They show interface implementation, not genuine remote command success.

![Figure 11. Inventory browser-QA view: endpoints, setup and observation states, and node actions. Source: inventory.png; mocked environment.](screenshots/inventory.png)

![Figure 12. Controlled-operations browser-QA view: fixed action selection, command preview and result inspector. The isolated output is a fixture, not a live node measurement. Source: operations-workbench.png.](screenshots/operations-workbench.png)

## 4.2. Metrics and missing data

![Figure 13. Native Fleet Health browser-QA trends for CPU, memory and network. This demonstrates chart presentation; it is not a Grafana screenshot or live Prometheus dataset. Source: health-1440x900.png.](screenshots/health-1440x900.png)

![Figure 14. Missing-data browser-QA view. Disconnected series preserve absent measurements instead of displaying false zeros. Source: health-missing.png.](screenshots/health-missing.png)

The interface makes independent signals visible: a machine can be SSH-reachable while exporter data is missing. Real operating measurements must retain their target, source timestamp and query context; screenshots alone do not establish long-term correctness.


## Appendix A. Build, deployment and reproduction

### Local test environment
Use the existing fleet-manager project root, locked Python 3.12 environment and Node.js. These commands are reproduction instructions, not executions performed by this report page. uv sync may access package sources; deployment commands are not executed here.

```text
uv sync --locked
uv run --no-sync python -m pytest -q
node --experimental-vm-modules --test tests/dashboard_modules.cjs tests/dashboard_regression.cjs
uv run --no-sync python -m ruff check src tests scripts
uv run --no-sync python -m mypy src
```

### Reference deployment order
- Prepare independently isolated Linux nodes, sshd, restricted login accounts and Node Exporter. Record target identities and network boundaries.
- Install locked controller dependencies and service configuration; create private configuration/state paths with correct permissions.
- Configure Prometheus target discovery and Grafana provisioning; verify actual listeners and operator access paths.
- Start the single-worker controller through the documented runbook. Independently compare host fingerprints before enrollment; authorize the public key on targets.
- Verify inventory, authenticated observations, exporter scrapes, time-range samples and rendered Grafana panels as distinct checks.
- Execute authorized diagnostics; preserve request/result/audit IDs. Only then run an explicitly authorized bounded fault/recovery experiment.

Use docs/DEPLOYMENT-RUNBOOK.md and deploy/gce/ as the operational authority. This report is not an instruction to create cloud resources, alter firewall rules, or inject failures without authorization.

### Earlier engineering-edition rebuild
From the repository root, run the existing Python environment against .local/build_engineering_report.py. It produces the separate editable Markdown, self-contained HTML, vector-diagram PDF and evidence manifest under docsSX. It does not invoke the release ZIP compiler. Source code, old reports and archives remain untouched.

## Appendix B. Traceability, references and final assessment

### Source-to-claim map
| Report concern | Primary local source |
| --- | --- |
| Requirement boundary | AGENTS.md; docs/PROJECT-CHARTER.md |
| Lifecycle / one worker / reconciliation | src/fleet_manager/main.py; deploy/fleet-manager.service |
| Enrollment / trust / setup | connectivity/router.py, service.py, trust.py, readiness.py |
| Observation semantics / scheduler | connectivity/freshness.py, scheduler.py; config.py |
| Controlled actions / uncertain outcomes | operations/catalog.py, executor.py, service.py, transport.py, repository.py |
| Control schema / auth boundary | inventory and security repositories; security/auth.py |
| Telemetry and native health | monitoring/; src/fleet_manager/metrics/health.py, health_router.py and telemetry.py |
| Operator interface / focus | ui/templates/dashboard.html; ui/static/js/dialog-ownership.js and app modules |
| Backup and restore | scripts/backup_restore.py; docs/DEPLOYMENT-RUNBOOK.md |
| Measured historical values | Companion manifest's retained raw logs and benchmark JSON |

Paths in module-family rows are relative to src/fleet_manager unless stated otherwise. The companion manifest records exact existing source paths and SHA-256 digests; a source digest identifies inspected bytes, not successful runtime behavior.

### Assessment and next evidence
The controller has concrete trust, admission, persistence, recovery-interpretation and operator-feedback mechanisms. This edition explains them through overview and detailed source-derived diagrams, explicit failure paths and trade-offs. Historical local tests, controlled admission measurements and a five-target scrape snapshot remain distinct evidence classes. Genuine rendered Grafana, complete deployed operation traces, independent-host outage/recovery and deployed restore verification remain open. A source-inspected confirmation-validation weakness is now explicit; fixing it is a separate application change.

The next useful step is to review the detailed workflows and D11 evidence map against the student's understanding, then locate existing genuine artifacts before authorizing new live capture. Student explanation, live acceptance and report completeness are separate outcomes.

## Appendix C. Submission files and guideline check

| File | Role / description |
| --- | --- |
| ADARSH-SINGH_SWFW_5S_12.pdf | Single-file report upload candidate; embeds student/project details, work done, twenty diagrams, four captioned screenshots and build/reproduction instructions. |
| ADARSH-SINGH_SWFW_5S_12.docx | Editable review companion; not an allowed standalone submission format. |
| No external project archive prepared for this revision | The supplied SWFW_5S_12 row requires a Flow Diagram, not a complete code folder. Use a single ZIP only if additional external files are actually required. Existing ZIPs have not been refreshed with this report. |

The prescribed Student Details, Project Details, Work Done and Output / Screenshots sections are present. Onboarding and operation flow diagrams are embedded directly in this PDF, satisfying the stated PS-specific diagram inclusion requirement. Screenshots retain their mocked-QA labels; genuine Grafana, full deployed-operation and independent-node outage/recovery evidence remain incomplete, not silently certified by this formatting check.

The supplied window closes on 12 November 2026 at 5 PM (timezone unspecified). Before upload, the student must confirm these identity details, that SWFW_5S_12 is the project selected through the Project Selection Form, eligibility and use of the same account. Only one PDF or ZIP may be uploaded. Do not upload DOCX or upload PDF and ZIP separately.
