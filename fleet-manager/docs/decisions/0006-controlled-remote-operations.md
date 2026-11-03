# ADR 0006: Controlled Remote Operations Architecture and Security Guardrails

Date: 2026-10-27
Status: Accepted
Author: executing Antigravity agent; scope approved by student charter

## Decision

To implement the Zoho Requirement 4 (Controlled Remote Command Execution) while enforcing strict defense-in-depth security, process isolation, durable auditability, and failure classification:

1. **Feature-Oriented Module**: All execution logic is encapsulated in `fleet_manager.operations`.
2. **Strict Action Catalog**: Arbitrary shell execution and interactive shells are forbidden. Only pre-vetted, allowlisted read-only actions are permitted:
   - `system.uptime`: validates no extra arguments; compiles to `uptime`.
   - `system.memory`: validates no extra arguments; compiles to `free -m`.
   - `system.disk`: validates absolute POSIX path, disallows whitespace, directory traversal (`..`), and shell metacharacters; compiles to `df -h -P -- <path>`.
   - `service.status`: validates service unit identifier with strict regex `^[a-zA-Z0-9_\\-\\.\\@]{1,64}$`, rejecting leading `-` and metacharacters; compiles to `systemctl --no-pager status -- <service_name>`.
3. **Dedicated Remote SSH Boundary**: Commands are executed strictly across authenticated SSH channels to registered nodes (`ParamikoOperationTransport`). Commands are never executed locally on the control-plane host.
4. **Admission Control & Process Boundary**: `ProcessOperationExecutor` manages child workers (`python -m fleet_manager.operations.worker`) with monotonic deadline enforcement, SIGKILL reaping, and concurrency bounds (`FLEET_MANAGER_OPERATION_MAX_CONCURRENT`, default 4). Excess requests return HTTP 429 (`OperationBusy`), and concurrent operations on the same node return HTTP 409 (`OperationInProgress`) without unbounded queuing.
5. **Durable Schema Evolution (Version 3)**: An append-only `operation_executions` SQLite table records job ID, node ID, allowlisted action, sanitized arguments, timestamps, bounded exit status, output, truncation status, and sanitized audit metadata (`operator_type`, `operator_digest_prefix`). Migrates transactionally via `PRAGMA user_version = 3`.
6. **Failure & Uncertainty Taxonomy**: Distinguishes `SUCCESS`, `FAILURE` (`COMMAND_ERROR`, `AUTH_FAILED`, `HOST_KEY_MISMATCH`, `HOST_KEY_UNKNOWN`, `CONNECTION_REFUSED`, `DNS_ERROR`), `TIMEOUT`, and `UNCERTAIN` (`TRANSPORT_ERROR`, `CONTROL_PLANE_RESTARTED`). If connection drops after command dispatch, the outcome is honestly marked `UNCERTAIN` without claiming exactly-once execution.
7. **Crash Reconciliation**: Leftover `RUNNING` jobs are reconciled to `UNCERTAIN` (`CONTROL_PLANE_RESTARTED`) upon application startup.
8. **Output Bounds**: Bounded output reading (default 64 KiB) prevents control-plane memory exhaustion while recording `output_truncated = true`.
