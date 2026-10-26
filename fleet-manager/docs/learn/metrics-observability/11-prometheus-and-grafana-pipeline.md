# Document 11: The Prometheus Scrape Pipeline & Grafana Dashboards

> **Curriculum Navigation:**
> * **Phase 1: Foundation & Architecture:** [Documents 01–02](../foundation/01-vision-and-first-principles.md)
> * **Phase 2: Milestone 1 — Node Inventory & Onboarding:** [Documents 03–07](../node-inventory/03-registration-flow.md)
> * **Phase 3: Milestone 2 — Availability Detection & Probing:** [Documents 08–09](../connectivity-probing/08-linux-probing-and-handshakes.md)
> * **Phase 4: Milestone 3 — Metrics & Observability (This Phase):**
>   * [Document 10: Linux System Metrics Architecture & Node Exporter](10-linux-metrics-and-node-exporter.md)
>   * **Document 11 (This Document): Prometheus Scrape Pipeline & Grafana Dashboards**

---

## 1. The Big Picture: The 3-Tier Observability Pipeline

In Document 10, we learned that Linux generates raw performance counters in `/proc` and that **Node Exporter** exposes those numbers over HTTP port `9100`.

Now we connect the complete industry-standard pipeline required by **Official Requirement 2**:

```
[ Remote Linux Node ]               [ Prometheus Server ]               [ Grafana Server ]
─────────────────────               ─────────────────────               ──────────────────
Runs: node_exporter (Port 9100)      Runs: Prometheus (Port 9090)        Runs: Grafana (Port 3000)
Exposes: /proc metrics              Scrapes: HTTP GET /metrics          Queries: PromQL
Output: Plain text metrics          Stores: Compressed TSDB Chunks      Renders: Real-time UI Charts
```

Each tier has a single, well-defined responsibility:
1. **Producer (Node Exporter):** Reads the Linux kernel and exposes raw facts.
2. **Collector & Storage (Prometheus):** Pulls the data on a schedule, timestamps it, and stores it in an append-only TSDB.
3. **Visualizer (Grafana):** Translates time-series queries into human-understandable graphs, gauges, and alerts.

---

## 2. Prometheus Configuration: `prometheus.yml`

Prometheus is configured using a declarative YAML file called `prometheus.yml`.

Here is the exact production configuration for Fleet Manager:

```yaml
global:
  scrape_interval: 15s     # How often to scrape targets (every 15 seconds)
  evaluation_interval: 15s # How often to evaluate alerting rules

scrape_configs:
  # Job 1: Monitor Prometheus itself
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # Job 2: Monitor Fleet Manager Linux Nodes
  - job_name: 'fleet_nodes'
    file_sd_configs:
      - files:
          - 'targets.json'  # Dynamic Service Discovery!
        refresh_interval: 10s
```

### 💡 The First-Principles Genius: Dynamic Service Discovery (`file_sd_configs`)
Notice how we avoid restarting Prometheus every time an operator registers a new node!
* Instead of hardcoding IPs in `prometheus.yml`, we use **File-Based Service Discovery (`file_sd_configs`)**.
* Whenever an operator registers a node in Fleet Manager, our backend writes a simple JSON file:
  ```json
  [
    {
      "targets": ["192.168.1.50:9100", "192.168.1.51:9100"],
      "labels": {
        "fleet": "production"
      }
    }
  ]
  ```
* Prometheus automatically detects changes to `targets.json` every 10 seconds and begins scraping new machines **with zero downtime and zero server restarts!**

---

## 3. PromQL: The Language of Observability

Relational SQL queries tables and columns (`SELECT cpu FROM metrics WHERE id = 1`).  
Observability needs **Time Windows, Rates of Change, and Math over Vectors**.

Prometheus uses **PromQL (Prometheus Query Language)**.

Here are the 3 essential queries every fleet management engineer must know:

### A. Real-Time CPU Usage Percentage
Remember from Document 10: `node_cpu_seconds_total` is a counter of ticks that only goes up.  
To find the CPU percentage over the last 1 minute:

```promql
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)
```

**Deconstruction:**
1. `node_cpu_seconds_total{mode="idle"}[1m]`: Takes all idle tick readings over the past 60-second window.
2. `rate(...)`: Calculates the per-second rate of idle time.
3. `avg by (instance)`: Averages across all CPU cores for that specific machine.
4. `100 - (Idle * 100)`: If the CPU was 90% idle, actual usage is $100 - 90 = 10\%$.

---

### B. Real-Time Memory Usage Percentage
Using the true metric `MemAvailable` from Document 10:

```promql
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

**Deconstruction:**
1. `node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes`: The fraction of RAM currently available.
2. `1 - available`: The fraction of RAM actively consumed by applications.
3. `* 100`: Converts to a clean 0%–100% percentage for Grafana gauges!

---

### C. Live Host Up / Down State
Prometheus automatically generates an internal metric for every target during each scrape:

```promql
up{job="fleet_nodes"}
```

* Returns **`1`**: Scrape succeeded (Host & Node Exporter are UP).
* Returns **`0`**: Scrape failed (Host is down, network partitioned, or port blocked).

---

## 4. Grafana Dashboards: Turning Math into Visuals

Grafana connects to Prometheus as a **Data Source**:
* URL: `http://localhost:9090`
* Access: Server (direct HTTP queries)

Once connected, Grafana lets you create reusable dashboard panels:
1. **CPU Usage Gauge:** Visualizes CPU load with color thresholds (Green < 70%, Yellow 70–85%, Red > 85%).
2. **Memory Utilization Graph:** Displays time-series trends over the last 1h / 6h / 24h.
3. **Fleet Status Table:** Lists all registered instances with their `up` status and RTT latency.

---

## 5. Integrating Prometheus Telemetry into Fleet Manager

Our web dashboard (`static/index.html`) can display live Prometheus numbers directly beside the node cards!

How? Prometheus exposes a simple HTTP REST API:
```http
GET http://localhost:9090/api/v1/query?query=up
```

Response JSON:
```json
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [
      {
        "metric": { "instance": "192.168.1.50:9100", "job": "fleet_nodes" },
        "value": [1729240000.123, "1"]
      }
    ]
  }
}
```

Our Fleet Manager backend can query this API and show real-time CPU & Memory usage badges right inside our dashboard!

---

## 6. Check Understanding

Before we wire up the practice configuration, test your understanding on this architecture scenario:

### The Scenario
You deploy Fleet Manager, Prometheus, and Grafana.
You have 3 nodes registered in the fleet:
* `Node 1`: `192.168.1.50:9100` (Online)
* `Node 2`: `192.168.1.51:9100` (Online)
* `Node 3`: `192.168.1.52:9100` (Powered OFF)

### Questions:
1. When Prometheus scrapes `Node 3`, what value does Prometheus store for `up{instance="192.168.1.52:9100"}`?
2. What value does Prometheus store for `node_cpu_seconds_total` on `Node 3`?
3. If an operator adds `Node 4` through the Fleet Manager dashboard, how does Prometheus know about `Node 4` without restarting the Prometheus daemon?

<details>
<summary><b>Click to check the worked answer</b></summary>

**Answer:**
1. **`0`**. The synthetic metric `up` is explicitly set to `0` when a scrape fails.
2. **Nothing! (Missing data / NaN).** Prometheus does NOT record `0` for CPU or RAM metrics when a scrape fails. It simply records no sample for that timestamp, leaving a clean gap in the time series.
3. **Via Dynamic File Service Discovery (`file_sd_configs`).** Fleet Manager appends Node 4 to `targets.json`. Prometheus monitors `targets.json` and reloads its target list within 10 seconds automatically without restarting.

</details>

---

## 🛠️ What Comes Next?

Now that we understand the Prometheus architecture and PromQL queries:
👉 **[Practice 06: Prometheus Targets Generator & Live Telemetry Integration](practice/practice-06-prometheus-integration.md)**\
*(We will write the dynamic targets exporter in Python, set up Prometheus scraping, and query live metrics!)*
