"""Fixed, bounded Prometheus queries for inventory node health."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from typing import Any

import httpx

METRICS = {
    "cpu_percent": (
        '100 * (1 - avg(rate(node_cpu_seconds_total{job="node_exporter",'
        'node_id="%s",mode="idle"}[5m])))'
    ),
    "memory_total_bytes": 'node_memory_MemTotal_bytes{job="node_exporter",node_id="%s"}',
    "memory_available_bytes": 'node_memory_MemAvailable_bytes{job="node_exporter",node_id="%s"}',
    "root_total_bytes": (
        'node_filesystem_size_bytes{job="node_exporter",node_id="%s",mountpoint="/"}'
    ),
    "root_available_bytes": (
        'node_filesystem_avail_bytes{job="node_exporter",node_id="%s",mountpoint="/"}'
    ),
    "uptime_seconds": 'time() - node_boot_time_seconds{job="node_exporter",node_id="%s"}',
    "load_one": 'node_load1{job="node_exporter",node_id="%s"}',
    "receive_bytes_per_second": (
        'sum(rate(node_network_receive_bytes_total{job="node_exporter",node_id="%s",'
        'device!~"lo|veth.*|docker.*|br-.*"}[5m]))'
    ),
    "transmit_bytes_per_second": (
        'sum(rate(node_network_transmit_bytes_total{job="node_exporter",node_id="%s",'
        'device!~"lo|veth.*|docker.*|br-.*"}[5m]))'
    ),
}
UP = 'up{job="node_exporter",node_id="%s"}'
STALE_AFTER_SECONDS = 90


def _sample(raw: Any) -> tuple[float, float] | None:
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    try:
        stamp, value = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(stamp) or not math.isfinite(value):
        return None
    return stamp, value


def _vector(payload: Any, result_type: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError("Prometheus query failed")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != result_type:
        raise ValueError("Unexpected Prometheus response")
    result = data.get("result")
    if not isinstance(result, list) or len(result) > 20:
        raise ValueError("Unexpected Prometheus series count")
    return [row for row in result if isinstance(row, dict)]


class PrometheusHealth:
    """Queries only predefined expressions. The server URL is operator configuration."""

    def __init__(
        self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None
    ):
        configured_url = (
            base_url or os.getenv("FLEET_MANAGER_PROMETHEUS_URL") or "http://127.0.0.1:9090"
        ).rstrip("/")
        try:
            parsed = httpx.URL(configured_url)
            valid = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.host)
                and not parsed.userinfo
                and not parsed.query
                and not parsed.fragment
            )
        except httpx.InvalidURL:
            valid = False
        self.base_url = configured_url if valid else None
        self.transport = transport

    async def _query(
        self, client: httpx.AsyncClient, expression: str, range_query: bool = False
    ) -> list[dict[str, Any]]:
        path = "/api/v1/query_range" if range_query else "/api/v1/query"
        params: dict[str, str | int] = {"query": expression}
        if range_query:
            end = int(time.time())
            params.update({"start": end - 3600, "end": end, "step": 150})
        response = await client.get(path, params=params)
        response.raise_for_status()
        if len(response.content) > 262144:
            raise ValueError("Prometheus response too large")
        return _vector(response.json(), "matrix" if range_query else "vector")

    async def node(self, node_id: int, address: str, name: str) -> dict[str, Any]:
        if self.base_url is None:
            return {"status": "unavailable", "observed_at": None, "metrics": {}, "trends": {}}
        timeout = httpx.Timeout(2.5)
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=timeout, transport=self.transport, trust_env=False
            ) as client:
                target_rows = await self._query(client, UP % node_id)
                matching = [
                    row
                    for row in target_rows
                    if isinstance(row.get("metric"), dict)
                    and row["metric"].get("node_id") == str(node_id)
                ]
                if not matching:
                    for label, value in (("node_name", name), ("instance", f"{address}:9100")):
                        rows = await self._query(
                            client, f'up{{job="node_exporter",{label}={json.dumps(value)}}}'
                        )
                        matching = [
                            row
                            for row in rows
                            if isinstance(row.get("metric"), dict)
                            and row["metric"].get(label) == value
                            and row["metric"].get("node_id") in (None, str(node_id))
                        ]
                        if matching:
                            break
                if len(matching) != 1:
                    return {
                        "status": "unavailable",
                        "observed_at": None,
                        "metrics": {},
                        "trends": {},
                    }
                labels = matching[0]["metric"]
                instance = labels.get("instance")
                if not isinstance(instance, str) or not 1 <= len(instance) <= 255:
                    return {
                        "status": "unavailable",
                        "observed_at": None,
                        "metrics": {},
                        "trends": {},
                    }
                quoted_instance = json.dumps(instance)
                expressions = {
                    key: template.replace('node_id="%s"', f"instance={quoted_instance}")
                    for key, template in METRICS.items()
                }
                target_sample = _sample(matching[0].get("value"))
                if target_sample is None:
                    return {
                        "status": "unavailable",
                        "observed_at": None,
                        "metrics": {},
                        "trends": {},
                    }
                stamp, up = target_sample
                if not 0 <= time.time() - stamp <= STALE_AFTER_SECONDS:
                    status = "stale"
                else:
                    status = "up" if up == 1 else "down"
                if status != "up":
                    return {"status": status, "observed_at": stamp, "metrics": {}, "trends": {}}
                keys = list(METRICS)
                results = await asyncio.wait_for(
                    asyncio.gather(
                        *(self._query(client, expressions[key]) for key in keys),
                        return_exceptions=True,
                    ),
                    timeout=3.0,
                )
                metrics: dict[str, float | None] = {}
                for key, result_rows in zip(keys, results, strict=True):
                    sample = (
                        _sample(result_rows[0].get("value"))
                        if isinstance(result_rows, list) and len(result_rows) == 1
                        else None
                    )
                    metrics[key] = (
                        sample[1]
                        if sample and 0 <= time.time() - sample[0] <= STALE_AFTER_SECONDS
                        else None
                    )
                    metric_value = metrics[key]
                    if metric_value is not None and (
                        metric_value < 0 or (key == "cpu_percent" and metric_value > 100)
                    ):
                        metrics[key] = None
                if (
                    metrics["memory_total_bytes"]
                    and metrics["memory_available_bytes"] is not None
                    and metrics["memory_available_bytes"] <= metrics["memory_total_bytes"]
                ):
                    metrics["memory_used_bytes"] = max(
                        0.0, metrics["memory_total_bytes"] - metrics["memory_available_bytes"]
                    )
                else:
                    metrics["memory_used_bytes"] = None
                if (
                    metrics["root_total_bytes"]
                    and metrics["root_available_bytes"] is not None
                    and metrics["root_available_bytes"] <= metrics["root_total_bytes"]
                ):
                    metrics["root_percent"] = 100 * (
                        1 - metrics["root_available_bytes"] / metrics["root_total_bytes"]
                    )
                else:
                    metrics["root_percent"] = None
                trends: dict[str, list[list[float]]] = {}
                if status == "up":
                    for key in ("cpu_percent", "memory_available_bytes"):
                        try:
                            rows = await self._query(client, expressions[key], range_query=True)
                            points = rows[0].get("values") if len(rows) == 1 else None
                            trends[key] = (
                                [
                                    list(sample)
                                    for raw in points
                                    if (sample := _sample(raw)) and time.time() - sample[0] <= 3600
                                ]
                                if isinstance(points, list)
                                else []
                            )
                        except (httpx.HTTPError, ValueError, TimeoutError):
                            trends[key] = []
                return {
                    "status": status,
                    "observed_at": stamp,
                    "metrics": metrics,
                    "trends": trends,
                }
        except (httpx.HTTPError, ValueError, TimeoutError):
            return {"status": "unavailable", "observed_at": None, "metrics": {}, "trends": {}}
