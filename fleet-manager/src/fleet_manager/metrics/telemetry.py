"""Telemetry metrics collector for the Fleet Manager control plane."""

import time
from collections.abc import Callable
from typing import Final

from fleet_manager.connectivity.freshness import DisplayStatus
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.metrics.registry import Counter, Gauge, Histogram, MetricsRegistry
from fleet_manager.operations.catalog import ALLOWED_ACTIONS
from fleet_manager.operations.models import OperationOutcome


class Telemetry:
    """Manages control plane metrics and dynamic fleet status exposition.

    Each render attempts fleet-status collection once when a service is attached.
    Failed attempts increment collector errors; successful scrapes do not increment
    application event counters. No service means no attempt and success remains 0.
    Last-success time is Unix seconds, or 0 until the first success, and survives
    later failures. All values are local to this instance and reset on restart.
    """

    def __init__(
        self,
        service: ConnectivityService | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.service = service
        self._clock = clock
        self.registry = MetricsRegistry()

        # 1. Connectivity check outcomes counter
        self.connectivity_checks_total: Final[Counter] = self.registry.counter(
            "fleet_connectivity_checks_total",
            "Total SSH connectivity checks executed by outcome category",
            label_names=("outcome",),
        )

        # 2. Check duration histogram (in seconds)
        self.connectivity_check_duration_seconds: Final[Histogram] = self.registry.histogram(
            "fleet_connectivity_check_duration_seconds",
            "Duration of SSH connectivity checks in seconds",
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 12.0),
            label_names=("outcome",),
        )

        # 3. Active checks gauge and capacity gauge
        self.connectivity_active_checks: Final[Gauge] = self.registry.gauge(
            "fleet_connectivity_active_checks",
            "Number of active SSH checks currently executing",
        )
        self.connectivity_max_concurrent: Final[Gauge] = self.registry.gauge(
            "fleet_connectivity_max_concurrent",
            "Configured maximum concurrent SSH checks allowed by admission control",
        )

        # 4. Scheduler activity and failure counters
        self.scheduler_cycles_total: Final[Counter] = self.registry.counter(
            "fleet_scheduler_cycles_total",
            "Total automated connectivity monitoring scheduler cycles completed",
        )
        self.scheduler_checks_skipped_total: Final[Counter] = self.registry.counter(
            "fleet_scheduler_checks_skipped_total",
            "Total scheduled node checks skipped by reason",
            label_names=("reason",),
        )
        self.scheduler_errors_total: Final[Counter] = self.registry.counter(
            "fleet_scheduler_errors_total",
            "Total scheduler errors encountered by category",
            label_names=("reason",),
        )
        self.scheduler_running: Final[Gauge] = self.registry.gauge(
            "fleet_scheduler_running",
            "Whether the automated monitoring scheduler is currently active (1) or stopped (0)",
        )

        # 5. Health of the single, known dynamic collector; never label by exception or node.
        self.collector_success: Final[Gauge] = self.registry.gauge(
            "fleet_collector_success",
            "Whether the latest collection succeeded (1) or is unavailable (0)",
            label_names=("collector",),
        )
        self.collector_errors_total: Final[Counter] = self.registry.counter(
            "fleet_collector_errors_total",
            "Total failed collection attempts; each scrape triggers an attempt when configured",
            label_names=("collector",),
        )
        self.collector_last_success_timestamp_seconds: Final[Gauge] = self.registry.gauge(
            "fleet_collector_last_success_timestamp_seconds",
            "Unix timestamp of the most recent successful collection, or 0 before any success",
            label_names=("collector",),
        )
        self.collector_success.set(0.0, labels={"collector": "fleet_status"})
        self.collector_errors_total.inc(0.0, labels={"collector": "fleet_status"})
        self.collector_last_success_timestamp_seconds.set(0.0, labels={"collector": "fleet_status"})

        # Pre-populate known outcome counters with 0.0 so they appear in initial scrapes
        for outcome in ConnectivityOutcome:
            self.connectivity_checks_total.inc(0.0, labels={"outcome": outcome.value})

        self.connectivity_active_checks.set(0.0)
        self.scheduler_running.set(0.0)
        self.scheduler_cycles_total.inc(0.0)

        # 6. Remote operations metrics
        self.operations_total: Final[Counter] = self.registry.counter(
            "fleet_operations_total",
            "Total remote operations executed by action and terminal outcome",
            label_names=("action", "outcome"),
        )
        self.operation_duration_seconds: Final[Histogram] = self.registry.histogram(
            "fleet_operation_duration_seconds",
            "Duration of remote operations in seconds by action and terminal outcome",
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0),
            label_names=("action", "outcome"),
        )
        self.operations_active: Final[Gauge] = self.registry.gauge(
            "fleet_operations_active",
            "Number of remote operations currently executing by action",
            label_names=("action",),
        )

        for action in sorted(ALLOWED_ACTIONS):
            self.operations_active.set(0.0, labels={"action": action})
            for op_outcome in (
                OperationOutcome.SUCCESS,
                OperationOutcome.FAILURE,
                OperationOutcome.TIMEOUT,
                OperationOutcome.UNCERTAIN,
            ):
                self.operations_total.inc(
                    0.0, labels={"action": action, "outcome": op_outcome.value}
                )

        # Register dynamic fleet status collector
        self.registry.register_collector(self._collect_fleet_status)

    def _collect_fleet_status(self) -> list[tuple[str, str, str, dict[str, str], float]]:
        if self.service is None:
            self.collector_success.set(0.0, labels={"collector": "fleet_status"})
            return []
        try:
            status = self.service.fleet_status()
            counts = {state.value: 0.0 for state in DisplayStatus}
            for item in status.nodes:
                counts[item.display_status.value] += 1.0

            samples = [
                (
                    "fleet_nodes_by_status",
                    "Number of registered fleet nodes by derived display status",
                    "gauge",
                    {"status": state},
                    count,
                )
                for state, count in counts.items()
            ]
            collected_at = self._clock()
        except Exception:
            # Omit unavailable counts, including any partial result. Exception text
            # can contain database paths or records and must not be logged or exposed.
            self.collector_success.set(0.0, labels={"collector": "fleet_status"})
            self.collector_errors_total.inc(labels={"collector": "fleet_status"})
            return []

        self.collector_last_success_timestamp_seconds.set(
            collected_at, labels={"collector": "fleet_status"}
        )
        self.collector_success.set(1.0, labels={"collector": "fleet_status"})
        return samples

    def render(self) -> str:
        return self.registry.render()
