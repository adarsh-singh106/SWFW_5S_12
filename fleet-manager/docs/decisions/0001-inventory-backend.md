# ADR 0001: First production inventory backend

Date: 2026-10-27  
Status: Accepted for the register/list slice  
Author: executing Codex agent, Windows PowerShell; approved scope supplied by the student

Authentication was added later in [ADR 0002](0002-local-inventory-authentication.md).
References below to missing authentication describe the original inventory slice.
The package was later organized into `main.py`, `config.py`, `inventory/`, and
`security/`; the SQLite schema and HTTP contract were retained.

## Context

The official application source and tests were placeholders. Practice code under
`docs/learn/` demonstrates concepts but does not establish an authenticated remote
fleet product. The first production slice needs to register and list node endpoints,
reject invalid and duplicate records, and retain them across application restarts.
It must not probe, connect to, or execute commands on those endpoints.

## Decision

- Use CPython 3.12 for this slice. It is installed locally, is an explicit project
  target, and avoids accidentally using the machine's default Python 3.14.
- Use FastAPI and Pydantic for a small typed HTTP boundary and generated OpenAPI
  contract. Run synchronous SQLite operations in normal synchronous route handlers;
  no async database layer or background worker is needed for two short operations.
- Use SQLite in a project-local `.local/inventory.db` by default. Inventory is a
  small relational record set, not monitoring time-series data. Tests inject a
  temporary path. Schema version 1 is initialized before serving; an unversioned
  existing `nodes` table is refused instead of silently migrated.
- Keep API, domain validation/use case, and repository in separate small modules.
  The API handles HTTP representation and errors; the domain normalizes records;
  the repository owns SQL and transactions. This permits independent testing and
  prevents HTTP or SQLite details from becoming the validation contract.
- Validate names, literal IP addresses or ASCII hostnames, and ports in application
  logic for clear errors. Normalize hostnames to lowercase and IP literals to
  canonical form. SQLite adds NOT NULL, CHECK, and UNIQUE constraints so other
  writers cannot bypass core data-integrity rules.
- The first observation state is `NOT_CHECKED`. Registration stores a contact
  record; it says nothing about reachability or host identity.

## Duplicate concurrent requests

Both requests may pass application validation. SQLite's unique constraint on
`(address, ssh_port)` decides the winner at insertion: one transaction commits,
the other receives a unique-constraint error. The repository maps that specific
error to `DuplicateNode`; the API returns HTTP 409. There is no separate
read-before-write availability check because it cannot make the write atomic.

## Alternatives considered

- PostgreSQL adds a service and operational setup before inventory scale needs it.
- SQLAlchemy adds a second abstraction for one table and two operations.
- Reusing practice modules would carry local shell execution, SSH-banner status
  claims, and unreviewed exception handling into the production package.
- An async SQLite wrapper adds scheduling complexity without a measured benefit.

## Consequences and limits

SQLite remains a single-file, single-writer database. Every request uses a short
connection with a bounded busy timeout; a lock or storage failure is reported as
unavailable rather than a duplicate. Schema changes need an explicit versioned
migration and backup plan. This slice has no authentication, authorization, SSH
host identity, metrics, node health, remote action, pagination, or multi-host
deployment proof. The local launch must bind to loopback until an auth and
deployment design is approved. Prometheus remains the planned time-series store.

## Evidence

See the current `docs/LEARNING-STATE.md` for executed checks and their limits;
the existence of this ADR alone is not verification.
