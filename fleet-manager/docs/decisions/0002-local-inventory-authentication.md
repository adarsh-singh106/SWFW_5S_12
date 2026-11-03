# ADR 0002: Local inventory authentication boundary

Date: 2026-10-27
Status: Accepted for the single-operator loopback API slice
Author: executing Codex agent; scope approved by the student

## Problem and threat model

The inventory API previously accepted requests from any local client. A browser
page, another local process, or an accidentally exposed port could read or add
records. This slice needs one small access gate before inventory operations.
The intended deployment is a single operator using a loopback-only development
server. The token reduces accidental or unauthorized requests by local clients
that do not possess it. It does not defend against a compromised operator account,
an administrator, process-environment inspection, or unencrypted traffic on a
network. The server must remain bound to `127.0.0.1`.

## Decision and HTTP contract

- Require one opaque, high-entropy bearer token in `Authorization: Bearer <token>`
  for every `/api/nodes` operation. The token comes from the process environment
  variable `FLEET_MANAGER_API_TOKEN`; it is never stored in source, SQLite, or
  project configuration. A test-only app factory argument allows isolated tests.
- Accept URL-safe ASCII tokens of 32 to 128 characters. Generate at least 32
  cryptographically random bytes for a real token. Reject missing, short, or
  malformed configuration during application startup, before opening inventory
  storage. String format cannot prove that a token was generated randomly.
- Reject missing, malformed, duplicated, and incorrect Authorization headers
  with HTTP 401, a generic `unauthorized` error body, and `WWW-Authenticate:
  Bearer`. Do not include submitted credentials in errors. Compare SHA-256 digests
  with `secrets.compare_digest` so verification time does not depend on a matching
  prefix. The digest is held in application memory; the original environment
  variable remains visible to processes with sufficient local privilege.
- Attach authentication to the inventory router, so later endpoints on that
  router inherit the boundary. OpenAPI advertises an HTTP bearer security scheme.
  Keep documentation endpoints accessible locally; they reveal the contract but
  cannot read or mutate inventory.

## Alternatives and tradeoffs

- HTTP Basic would encourage an operator password on every request and require
  password hashing and password-management rules that this slice cannot support.
- Session cookies and login pages add browser state, CSRF protection, session
  storage, and logout/rotation behavior before a browser UI exists.
- OAuth/OIDC adds an identity provider and operational dependencies before there
  are multiple users. It is a credible later route once user identity is needed.

The shared token is a development access secret, **not** a user identity, RBAC,
or an audit principal. Anyone holding it has the same inventory permissions.
Rotation requires updating the environment and restarting the process. It must
not be sent over plain HTTP beyond loopback; a future remote deployment needs TLS,
proper operator identity, authorization checks, and audit attribution.

## Impact on later SSH operations

API authentication alone cannot authorize a remote operation. Before adding
SSH actions, introduce identifiable operators, per-operation permissions, an
auditable request identity, explicit command allowlists, and separate SSH host
identity and credential handling. Never reuse this bearer token as an SSH secret.

## Verification

The checkpoint records executed tests and live HTTP evidence. This ADR defines
the intended behavior; it is not itself proof that a deployment is secure.
