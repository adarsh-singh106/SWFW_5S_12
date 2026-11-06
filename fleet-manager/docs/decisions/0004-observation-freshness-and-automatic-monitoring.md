# ADR 0004: Observation Freshness and Automatic Connectivity Monitoring

Date: 2026-10-27
Status: Accepted
Author: executing Codex agent; scope approved by student charter

## Decision

To make SSH connectivity observations meaningful over time without conflating network observations
with node health or administrative inventory state, the Linux Fleet Manager introduces:
1. Pure, time-dependent derived display status via `GET /api/nodes/status`.
2. Configurable observation time-to-live (TTL).
3. A bounded in-process periodic scheduler (`ConnectivityScheduler`) executing automatic checks.

## Freshness and Derived Display Status

Observation outcomes stored in `connectivity_observations` remain immutable UTC event records.
The inventory table (`nodes`) retains its administrative `observation_state = 'NOT_CHECKED'`;
it is never overwritten by connectivity checks.

At query time, `GET /api/nodes/status` evaluates each node's latest observation against the current clock
and observation TTL (`DEFAULT_OBSERVATION_TTL_SECONDS = 180`, configurable via `FLEET_MANAGER_OBSERVATION_TTL_SECONDS`):
- `NOT_CHECKED`: Node has no recorded observation.
- `REACHABLE`: Latest observation is `CONNECTED` and age <= TTL.
- `UNREACHABLE`: Latest observation is `CONNECTION_REFUSED` or `CONNECTION_TIMEOUT` and age <= TTL.
- `STALE`: Latest observation age > TTL (reason `TTL_EXPIRED`). Stale observations are never reported healthy or reachable.
- `CHECK_ERROR`: Latest observation was `TIMEOUT`, `EXECUTION_TIMEOUT`, `AUTH_FAILED`, `HOST_KEY_MISMATCH`, `HOST_KEY_UNKNOWN`, `DNS_ERROR`, `UNKNOWN_ERROR`, or has an invalid/future timestamp. Detailed failure reasons are strictly preserved in `reason` and `observation.outcome`.

## Automatic Monitoring Scheduler

Periodic automatic monitoring is implemented by `ConnectivityScheduler`:
- **Same Security Controls**: Automatic checks call `ConnectivityService.check(node_id)`, which utilizes the identical `ProcessSSHExecutor` child-process isolation, pinned host keys, non-root private key credentials, and total timeout budgets.
- **Configurable Polling and Modest Jitter**: Default polling interval is 60.0s (`FLEET_MANAGER_MONITORING_INTERVAL_SECONDS`), with a default 10% uniform jitter (`FLEET_MANAGER_MONITORING_JITTER_RATIO = 0.1`) applied to prevent synchronized traffic spikes.
- **Bounded Concurrency**: Concurrency is throttled by `asyncio.Semaphore(max_concurrent)` matching admission limits (default 4).
- **Backpressure Without Retry Storms**: If the executor is saturated, `ConnectivityBusy` is caught, logged with structured fields (`node_id`, `event="check_skipped"`, `reason="capacity_busy"`), and skipped for that cycle. No unbounded queues or tight retry loops are used.
- **Same-Node Mutual Exclusion**: Checks currently in-flight in the scheduler or executor (`ConnectivityInProgress`) are skipped to avoid overlapping checks per node.
- **Structured Error Logging**: All exceptions (configuration errors, storage errors, unexpected exceptions) are logged with structured contextual fields rather than swallowed silently.
- **Clean Lifecycle Shutdown**: Fast graceful shutdown (`stop()`) cancels pending and sleeping scheduler tasks, ensuring no dangling child processes or asyncio tasks remain.

## Process and Multi-Worker Restriction

`ConnectivityScheduler` is an in-process asyncio background task tied to FastAPI application lifespan.
Multi-worker deployment (e.g. `uvicorn --workers N`) would instantiate independent uncoordinated schedulers
within each worker process, duplicating network traffic and triggering concurrent lock contention.
Until distributed coordination (leader election or an external job queue) is implemented, the application
must be deployed with exactly one worker process per node/instance.
Duplicate scheduler invocations within the same application instance fail fast with `RuntimeError`.
