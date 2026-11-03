---
name: prometheus-grafana
description: Instruments and configures Prometheus metrics collection, storage, and Grafana visualization. Use when designing /metrics endpoints, defining counters/gauges/histograms, writing PromQL queries, configuring scrape jobs, or building Grafana dashboards.
---

# Prometheus & Grafana Observability Skill

Guide for designing, instrumenting, exposing, and visualizing system and fleet metrics using Prometheus and Grafana.

## Core Principles

1. **Missing Metrics Are Not Zero**: An unreachable node or missing scrape observation must be represented as absence of data (`null` / absent metric), never as `0`. Zero is a valid observation (e.g., 0 errors); absence signifies lack of observation.
2. **Cardinality Control**: Never put high-cardinality values into labels (e.g., raw error messages, timestamps, GUIDs, user tokens). Keep label sets small, bounded, and discrete.
3. **OpenMetrics Compliance**: Metric names and text format must strictly adhere to the OpenMetrics / Prometheus exposition standard.
4. **Symptom-Based Alerting**: Alert on symptoms that affect users or operators (error rates, unreachable nodes, latency spikes), not intermediate causes.

---

## Metric Types and Usage Guidelines

| Type | Characteristics | Fleet Manager Use Case | PromQL Functions |
|------|-----------------|------------------------|------------------|
| **Counter** | Monotonically increasing integer or float; resets only on process restart. | Total probes attempted, total commands executed, total HTTP requests. | `rate()`, `increase()`, `irate()` |
| **Gauge** | Value that can arbitrarily rise or fall. | Active connected nodes, registered nodes count, memory/disk usage percentage. | Raw value, `avg_over_time()`, `max_over_time()` |
| **Histogram** | Samples observations into configurable buckets and counts occurrences. | SSH connection latency, HTTP request duration, remote command execution duration. | `histogram_quantile()`, `rate()` |

---

## Metric Naming Conventions

Follow Prometheus official naming standards:

- Prefix with application or domain: `fleet_` or `node_`.
- Unit in the name: suffix with base SI unit (`_seconds`, `_bytes`, `_total`).
- Counters **must** end in `_total` (e.g., `fleet_probes_total`).
- Gauges describe current state (e.g., `fleet_monitored_nodes`).
- Avoid redundant unit names (e.g., `duration_seconds`, NOT `duration_seconds_total` unless it is a counter of elapsed seconds).

### Example Metric Set for Fleet Management

```text
# HELP fleet_probes_total Total number of SSH/network connectivity probes executed.
# TYPE fleet_probes_total counter
fleet_probes_total{outcome="connected"} 42
fleet_probes_total{outcome="connection_refused"} 3
fleet_probes_total{outcome="auth_failed"} 1

# HELP fleet_ssh_probe_duration_seconds Latency of SSH handshakes across nodes.
# TYPE fleet_ssh_probe_duration_seconds histogram
fleet_ssh_probe_duration_seconds_bucket{le="0.1"} 15
fleet_ssh_probe_duration_seconds_bucket{le="0.5"} 35
fleet_ssh_probe_duration_seconds_bucket{le="1.0"} 40
fleet_ssh_probe_duration_seconds_bucket{le="5.0"} 42
fleet_ssh_probe_duration_seconds_bucket{le="+Inf"} 42
fleet_ssh_probe_duration_seconds_sum 12.4
fleet_ssh_probe_duration_seconds_count 42

# HELP fleet_managed_nodes Total number of registered nodes by observation state.
# TYPE fleet_managed_nodes gauge
fleet_managed_nodes{state="not_checked"} 1
fleet_managed_nodes{state="connected"} 2
fleet_managed_nodes{state="unreachable"} 0
```

---

## FastAPI / Python Instrumentation Pattern

When exposing Prometheus metrics in FastAPI without introducing heavy external runtimes:

```python
from fastapi import FastAPI, Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI()

PROBE_COUNTER = Counter(
    "fleet_probes_total",
    "Total node connectivity probes executed",
    ["outcome"]
)
PROBE_DURATION = Histogram(
    "fleet_probe_duration_seconds",
    "Duration of node connectivity probes",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

---

## Prometheus Configuration (`prometheus.yml`)

Configure scraping with explicit timeouts and scrape intervals:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  scrape_timeout: 10s

scrape_configs:
  - job_name: 'fleet-manager'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['localhost:8000']
        labels:
          environment: 'production'
          service: 'fleet-control-plane'

  - job_name: 'node-exporter'
    static_configs:
      - targets:
          - 'node1.internal:9100'
          - 'node2.internal:9100'
          - 'node3.internal:9100'
```

---

## Useful PromQL Queries

1. **Probe Failure Rate (last 5 minutes)**:
   ```promql
   sum(rate(fleet_probes_total{outcome!="connected"}[5m]))
   /
   sum(rate(fleet_probes_total[5m]))
   ```

2. **95th Percentile Probe Latency**:
   ```promql
   histogram_quantile(0.95, sum(rate(fleet_probe_duration_seconds_bucket[5m])) by (le))
   ```

3. **Node Down Detection**:
   ```promql
   up{job="node-exporter"} == 0
   ```

---

## Grafana Dashboard Design Checklist

- [ ] Top row: Single-stat panels showing Total Managed Nodes, Online Nodes, Failed Probes (last 1h).
- [ ] Middle row: Time series showing Scrape & Probe Latency (p50, p95, p99).
- [ ] Bottom row: Table panel displaying current node status, last observation time, and outcome.
- [ ] Explicit Null Value handling: Configure panels to show "Null as null" or "Connected / Gaps", never "Null as zero".
- [ ] Human-readable units applied to all axes (seconds, bytes, percent).

---

## Common Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|--------------|--------------|------------------|
| Storing error messages in labels | Explodes TSDB cardinality; crashes Prometheus memory. | Use a fixed enum of error categories (e.g. `outcome="auth_failed"`). |
| Reporting `0` when a node is down | Hides the difference between a zero metric and an absent host. | Let the metric be absent; use `absent()` or `up == 0` to detect downtime. |
| Using Gauges for cumulative events | Loses data when samples are missed between scrapes. | Use Counters and apply `rate()` or `increase()`. |
| Scrape timeout $\ge$ scrape interval | Causes overlapping scrapes and scrape queue buildup. | Always ensure `scrape_timeout < scrape_interval` (e.g., 10s timeout for 15s interval). |
