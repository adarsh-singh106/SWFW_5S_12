# ADR 0003: Explicit SSH connectivity observations

Date: 2026-10-27
Status: Accepted for one-node, operator-triggered verification
Author: executing Codex agent; scope approved by the student

## Decision

`POST /api/nodes/{node_id}/connectivity-check` selects one persisted node ID,
attempts one SSH handshake, verifies an explicitly trusted host key, and
authenticates a configured non-root account. It opens no shell or command
channel. `GET /api/nodes/{node_id}/connectivity` returns the latest observation
or `null` before any check. Both routes require the existing bearer token.

Paramiko 5.1.0 is the sole new runtime dependency. Its transport is isolated
behind a small protocol so the use case can be tested with fakes. The client
loads only `FLEET_MANAGER_SSH_KNOWN_HOSTS`, rejects unknown host keys, and
refuses changed keys. It loads only the configured private key path; SSH agent,
home-directory key discovery, passwords, and automatic trust are disabled.
The dedicated account must have no remote privileges beyond SSH login for this
check; enforcing that account's privileges remains a server-side duty.

`FLEET_MANAGER_SSH_USERNAME`, `FLEET_MANAGER_SSH_KNOWN_HOSTS`, and
`FLEET_MANAGER_SSH_PRIVATE_KEY` are supplied through the process environment.
The paths point outside tracked source. Missing configuration produces 503 and
no observation. Before trusting a host, the operator must verify its host-key
fingerprint through an independent trusted channel; `ssh-keyscan` output alone
is not proof of identity. For nonstandard ports, the known_hosts host field is
`[hostname]:port` (or `[address]:port` for a registered IP literal).

Connection, banner, and authentication phase timeouts are each five seconds.
No scheduler or fleet-wide fanout exists.

## Bounded execution amendment (2026-10-27)

The production check now runs in a short-lived child process because Python
cannot safely cancel a thread blocked in OS DNS or SSH code. A process-local
admission gate allows at most four checks by default (configurable from 1 to
16) and excludes a second check of the same node. Capacity rejection is HTTP
429; same-node rejection is HTTP 409. These are not SSH observations. A total
12-second budget by default (configurable from 1 to 60) starts before child
launch, covers DNS, sequential addresses and authentication, and kills and
reaps the child when exceeded. A timeout observation records what the control
plane observed, not proof that the host is down. Graceful app shutdown kills
and reaps active children; interrupted checks return 503 without an SSH result.

The worker receives only a structured node endpoint and credential file paths.
It inherits a minimal process environment that excludes the API bearer token,
uses the existing pinned-host-key Paramiko adapter, and opens no command
channel. Its stderr is not returned to callers. Tests that inject an in-process
fake transport bypass process isolation intentionally; production does not.
The gate is per application process, so deploy with one Uvicorn worker until
cross-process coordination is designed. Abrupt parent-process termination and
OS process creation behavior are outside the graceful-shutdown guarantee.

## Phase-aware TCP amendment (2026-11-06)

The transport now resolves the registered endpoint with `getaddrinfo()`, tries
each IPv4 or IPv6 stream address in resolver order, and gives every TCP connect
attempt the configured connect timeout. Failed candidate sockets are closed
before the next candidate. A successful socket is passed to Paramiko with the
original normalized endpoint and SSH port, so the existing strict `known_hosts`
lookup, unknown-key rejection, key-mismatch rejection, and authentication
policy remain in force.

If every candidate fails, a timeout on any candidate produces
`CONNECTION_TIMEOUT`; only an all-refused set produces `CONNECTION_REFUSED`.
Mixed failures containing another socket error remain `UNKNOWN_ERROR` unless a
timeout occurred. This policy tries every candidate while avoiding the false
claim that every operating-system socket error proves unreachability. DNS and
sequential attempts are still bounded by the executor's total child-process
deadline; no resolver thread or retry loop was added. A timeout after a TCP
socket connects remains `TIMEOUT`, and the parent deadline remains
`EXECUTION_TIMEOUT`, both interpreted as check errors.

## Storage and interpretation

The existing `nodes` table and `/api/nodes` responses remain unchanged. App
startup migrates SQLite user_version 1 to 2 in one transaction, adding an
append-only `connectivity_observations` table. Each row has UTC observation
time, outcome, and separate nullable error category. A successful record has
`CONNECTED` with no error; failures retain their own category. The latest row
is selected by insertion ID. Registration stays `NOT_CHECKED`; an SSH failure
does not imply host failure, and an SSH success does not establish overall
node health.

## Limits

The shared API token is not operator identity or RBAC. An operator holding it
can trigger a bounded SSH authentication attempt to any registered endpoint;
future deployment needs egress policy, per-operator authorization, rate limits,
and audit attribution. Encrypted private keys are not supported without an
explicit passphrase mechanism. Key rotation requires an out-of-band trust
decision. No remote command execution, metrics, or automatic recovery is added.
