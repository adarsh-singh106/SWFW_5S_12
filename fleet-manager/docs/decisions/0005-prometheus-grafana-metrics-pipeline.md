# ADR 0005: Prometheus and Grafana Telemetry Pipeline

Date: 2026-10-27
Status: Accepted
Author: executing Antigravity agent; scope approved by student charter

## Decision

To provide production-grade, standardized observability for the Linux Fleet Manager without compromising security or architectural modularity, the following monitoring pipeline has been implemented and verified on Debian Linux WSL2:
1. Fleet Manager exposes a loopback/internal Prometheus-compatible `GET /metrics` text exposition endpoint.
2. Official Prometheus Node Exporter collects real Linux host metrics (CPU, memory, disk, network).
3. Prometheus scrapes both control-plane metrics and Node Exporter targets using file service discovery (`targets.json`).
4. Grafana provisions the Prometheus datasource and an operational dashboard with real time-series panels.

## 1. Fleet Manager Metrics Architecture

- **Format & Standards**: Implemented a lightweight, zero-dependency OpenMetrics / Prometheus text format serializer supporting standard `counter`, `gauge`, and `histogram` representations with `# HELP` and `# TYPE` headers.
- **Strict Bounded Cardinality**: Metric labels are strictly bounded to finite enum-derived values (`outcome`, `status`, `reason`, `le`). Arbitrary node identifiers, IP addresses, usernames, and raw error messages are completely excluded from label sets to prevent memory leaks and TSDB cardinality explosion.
- **Control-Plane Telemetry**:
  - `fleet_connectivity_checks_total{outcome=...}`: SSH verification outcomes by category.
  - `fleet_connectivity_check_duration_seconds{outcome=...}`: SSH probe latency histogram with bounded buckets (0.05s to 12.0s).
  - `fleet_connectivity_active_checks`: Currently executing concurrent SSH probes.
  - `fleet_connectivity_max_concurrent`: Configured executor capacity limit (default 4).
  - `fleet_nodes_by_status{status=...}`: Dynamic fleet breakdown by derived display status (`NOT_CHECKED`, `REACHABLE`, `UNREACHABLE`, `STALE`, `CHECK_ERROR`).
  - `fleet_scheduler_cycles_total`: Completed monitoring cycles.
  - `fleet_scheduler_checks_skipped_total{reason=...}`: Throttled/in-flight skipped checks.
  - `fleet_scheduler_errors_total{reason=...}`: Structured scheduler error occurrences.
  - `fleet_scheduler_running`: Boolean gauge tracking scheduler execution state.
- **Security Boundary**: `/metrics` is unauthenticated to comply with Prometheus pull conventions, and is intended to bind to loopback (`127.0.0.1`) or a restricted internal operations network. The API operator bearer token is reserved for administrative REST endpoints and not exposed to scrape pollers.

## 2. Scraping vs. SSH Probe Semantics

The pipeline distinguishes between transport/scrape availability and node reachability:
- A Prometheus target failure (`up == 0`) specifically indicates that the HTTP exposition endpoint (Fleet Manager or Node Exporter) could not be scraped or timed out.
- SSH connectivity failures (such as `CONNECTION_REFUSED`, `AUTH_FAILED`, `HOST_KEY_MISMATCH`) do not cause Prometheus scrapes to fail; instead, the scrape succeeds (`up == 1`), and the SSH failure is cleanly captured within `fleet_connectivity_checks_total` and `fleet_nodes_by_status`.

## 3. Host Exporter and Visualization

- **Prometheus Node Exporter**: Deployed via official distribution package `prometheus-node-exporter` (v1.5.0) exposing kernel metrics from `/proc` and `/sys`. Homegrown metrics scrapers were intentionally rejected.
- **Prometheus Server**: Official package `prometheus` (v2.42.0) with local file-based service discovery.
- **Grafana Provisioning**: Automated provisioning via `/etc/grafana/provisioning/datasources/prometheus.yaml` and dashboards provider pointing to `/etc/grafana/dashboards/fleet-monitoring.json`, displaying real CPU, memory, disk, network, scrape health, and fleet status queries.
