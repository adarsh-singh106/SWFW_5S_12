"""Thread-safe Prometheus-compatible metrics registry and exposition formatter."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final


def _escape_label_value(val: str) -> str:
    return val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    pairs = [f'{k}="{_escape_label_value(str(v))}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(pairs) + "}"


@dataclass(frozen=True, slots=True)
class MetricSample:
    name: str
    labels: dict[str, str]
    value: float


class Counter:
    """Monotonically increasing cumulative counter."""

    def __init__(self, name: str, description: str, label_names: Sequence[str] = ()) -> None:
        self.name: Final = name
        self.description: Final = description
        self.label_names: Final = tuple(label_names)
        self._values: dict[tuple[tuple[str, str], ...], float] = {}
        self._lock = threading.Lock()

    def _normalize_labels(self, labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        labels = labels or {}
        return tuple(sorted((k, str(labels.get(k, ""))) for k in self.label_names))

    def inc(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        if amount < 0:
            raise ValueError("Counter increments must be non-negative")
        key = self._normalize_labels(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def collect(self) -> list[MetricSample]:
        with self._lock:
            items = list(self._values.items())
        samples: list[MetricSample] = []
        for key, val in items:
            samples.append(MetricSample(self.name, dict(key), val))
        return samples


class Gauge:
    """Instantaneous numerical value that can arbitrarily increase or decrease."""

    def __init__(self, name: str, description: str, label_names: Sequence[str] = ()) -> None:
        self.name: Final = name
        self.description: Final = description
        self.label_names: Final = tuple(label_names)
        self._values: dict[tuple[tuple[str, str], ...], float] = {}
        self._lock = threading.Lock()

    def _normalize_labels(self, labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        labels = labels or {}
        return tuple(sorted((k, str(labels.get(k, ""))) for k in self.label_names))

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._normalize_labels(labels)
        with self._lock:
            self._values[key] = float(value)

    def inc(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        key = self._normalize_labels(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        key = self._normalize_labels(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - amount

    def collect(self) -> list[MetricSample]:
        with self._lock:
            items = list(self._values.items())
        samples: list[MetricSample] = []
        for key, val in items:
            samples.append(MetricSample(self.name, dict(key), val))
        return samples


class Histogram:
    """Cumulative histogram counting observations across predefined threshold buckets."""

    def __init__(
        self,
        name: str,
        description: str,
        buckets: Sequence[float] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 12.0),
        label_names: Sequence[str] = (),
    ) -> None:
        self.name: Final = name
        self.description: Final = description
        sorted_buckets = sorted(set(buckets))
        if float("inf") not in sorted_buckets:
            sorted_buckets.append(float("inf"))
        self.buckets: Final = tuple(sorted_buckets)
        self.label_names: Final = tuple(label_names)
        # key -> (dict of bucket_bound -> count, count, sum)
        self._values: dict[tuple[tuple[str, str], ...], tuple[dict[float, int], int, float]] = {}
        self._lock = threading.Lock()

    def _normalize_labels(self, labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        labels = labels or {}
        return tuple(sorted((k, str(labels.get(k, ""))) for k in self.label_names))

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._normalize_labels(labels)
        with self._lock:
            if key not in self._values:
                bucket_counts = {b: 0 for b in self.buckets}
                self._values[key] = (bucket_counts, 0, 0.0)
            bucket_counts, total_count, total_sum = self._values[key]
            for b in self.buckets:
                if value <= b:
                    bucket_counts[b] += 1
            self._values[key] = (bucket_counts, total_count + 1, total_sum + value)

    def collect(self) -> list[MetricSample]:
        with self._lock:
            items = [
                (key, (dict(b_counts), t_count, t_sum))
                for key, (b_counts, t_count, t_sum) in self._values.items()
            ]
        samples: list[MetricSample] = []
        for key, (b_counts, t_count, t_sum) in items:
            base_labels = dict(key)
            for b in self.buckets:
                le_str = "+Inf" if b == float("inf") else str(b)
                bucket_labels = {**base_labels, "le": le_str}
                samples.append(
                    MetricSample(f"{self.name}_bucket", bucket_labels, float(b_counts[b]))
                )
            samples.append(MetricSample(f"{self.name}_sum", base_labels, t_sum))
            samples.append(MetricSample(f"{self.name}_count", base_labels, float(t_count)))
        return samples


class MetricsRegistry:
    """Registry coordinating standard metric collectors and custom callbacks."""

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._dynamic_collectors: list[
            Callable[[], list[tuple[str, str, str, dict[str, str], float]]]
        ] = []
        self._lock = threading.Lock()
        self._render_lock = threading.Lock()

    def counter(self, name: str, description: str, label_names: Sequence[str] = ()) -> Counter:
        with self._lock:
            if name in self._counters:
                return self._counters[name]
            c = Counter(name, description, label_names)
            self._counters[name] = c
            return c

    def gauge(self, name: str, description: str, label_names: Sequence[str] = ()) -> Gauge:
        with self._lock:
            if name in self._gauges:
                return self._gauges[name]
            g = Gauge(name, description, label_names)
            self._gauges[name] = g
            return g

    def histogram(
        self,
        name: str,
        description: str,
        buckets: Sequence[float] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 12.0),
        label_names: Sequence[str] = (),
    ) -> Histogram:
        with self._lock:
            if name in self._histograms:
                return self._histograms[name]
            h = Histogram(name, description, buckets, label_names)
            self._histograms[name] = h
            return h

    def register_collector(
        self,
        collector: Callable[[], list[tuple[str, str, str, dict[str, str], float]]],
    ) -> None:
        """Register a callback returning (name, help, type, labels, value).

        Collectors handle their own recoverable failures and expose their health.
        An uncaught error aborts exposition instead of silently hiding a failure.
        """
        with self._lock:
            self._dynamic_collectors.append(collector)

    def render(self) -> str:
        """Format all registered metrics in standard Prometheus text exposition format."""
        # Keep each collection and its health snapshot together across concurrent scrapes.
        # Event counters use their own locks and can still update while collection runs.
        with self._render_lock:
            return self._render()

    def _render(self) -> str:
        lines: list[str] = []

        with self._lock:
            counters = list(self._counters.values())
            gauges = list(self._gauges.values())
            histograms = list(self._histograms.values())
            dynamic_collectors = list(self._dynamic_collectors)

        # Collect exactly once before reading stored health metrics, so this response
        # reports the current attempt rather than the previous scrape's result.
        dynamic_entries = [collector() for collector in dynamic_collectors]

        # 1. Counters
        for counter in counters:
            samples = counter.collect()
            lines.append(f"# HELP {counter.name} {counter.description}")
            lines.append(f"# TYPE {counter.name} counter")
            if not samples:
                # Default sample with empty labels if defined
                lines.append(f"{counter.name} 0")
            else:
                for sample in samples:
                    lines.append(f"{sample.name}{_format_labels(sample.labels)} {sample.value}")

        # 2. Gauges
        for gauge in gauges:
            samples = gauge.collect()
            lines.append(f"# HELP {gauge.name} {gauge.description}")
            lines.append(f"# TYPE {gauge.name} gauge")
            if not samples:
                lines.append(f"{gauge.name} 0")
            else:
                for sample in samples:
                    lines.append(f"{sample.name}{_format_labels(sample.labels)} {sample.value}")

        # 3. Histograms
        for hist in histograms:
            samples = hist.collect()
            lines.append(f"# HELP {hist.name} {hist.description}")
            lines.append(f"# TYPE {hist.name} histogram")
            for sample in samples:
                lines.append(f"{sample.name}{_format_labels(sample.labels)} {sample.value}")

        # 4. Dynamic collectors
        for entries in dynamic_entries:
            # Group by metric name
            grouped: dict[str, tuple[str, str, list[tuple[dict[str, str], float]]]] = {}
            for name, help_text, mtype, labels, value in entries:
                if name not in grouped:
                    grouped[name] = (help_text, mtype, [])
                grouped[name][2].append((labels, value))

            for name, (help_text, mtype, series) in grouped.items():
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {mtype}")
                for labels, val in series:
                    lines.append(f"{name}{_format_labels(labels)} {val}")

        lines.append("")  # trailing newline required by Prometheus exposition standard
        return "\n".join(lines)
