"""Periodic automatic connectivity monitoring using bounded executor checks.

NOTE ON MULTI-WORKER EXECUTION:
This scheduler runs in-process as an asyncio background task. If the application
is deployed across multiple processes (e.g. multiple Uvicorn workers), each worker
process would run an independent scheduler, causing duplicated and conflicting checks.
Multi-worker deployments require explicit cross-process coordination (such as
distributed leader election or an external task queue). For single-host operation,
run exactly one application instance or worker process.
"""

import asyncio
import logging
import random
import threading
from typing import TYPE_CHECKING, Final

from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.errors import (
    ConnectivityBusy,
    ConnectivityConfigurationError,
    ConnectivityInProgress,
    ConnectivityUnavailable,
    NodeNotFound,
    StorageError,
)
from fleet_manager.inventory.models import Node

if TYPE_CHECKING:
    from fleet_manager.metrics.telemetry import Telemetry

logger: Final = logging.getLogger("fleet_manager.connectivity.scheduler")


class ConnectivityScheduler:
    """Periodic bounded connectivity monitoring for registered nodes."""

    def __init__(
        self,
        service: ConnectivityService,
        interval_seconds: float = 60.0,
        jitter_ratio: float = 0.1,
        initial_delay_seconds: float | None = None,
        max_concurrent: int = 4,
        telemetry: "Telemetry | None" = None,
    ) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self.jitter_ratio = jitter_ratio
        self.initial_delay_seconds = initial_delay_seconds
        self.max_concurrent = max_concurrent
        self.telemetry = telemetry
        self._running = False
        self._stopping = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_flight: set[int] = set()
        self._in_flight_lock = threading.Lock()
        self._workers: set[asyncio.Task[None]] = set()

    @property
    def is_running(self) -> bool:
        return self._running

    def calculate_delay(self) -> float:
        """Calculate next cycle delay with modest uniform jitter."""
        jitter_bound = self.interval_seconds * self.jitter_ratio
        jitter = random.uniform(-jitter_bound, jitter_bound)
        return max(0.1, self.interval_seconds + jitter)

    def _execute_node_check(self, node: Node) -> None:
        """Run one check using existing service security controls and handle capacity."""
        try:
            observation = self.service.check(node.id)
            logger.info(
                "Automatic check completed for node %s (%s): outcome=%s",
                node.id,
                node.address,
                observation.outcome.value,
                extra={
                    "event": "check_completed",
                    "node_id": node.id,
                    "address": node.address,
                    "outcome": observation.outcome.value,
                },
            )
        except ConnectivityBusy:
            if self.telemetry is not None:
                self.telemetry.scheduler_checks_skipped_total.inc(
                    labels={"reason": "capacity_busy"}
                )
            logger.warning(
                "Scheduler capacity exhausted; skipping check for node %s until next cycle",
                node.id,
                extra={
                    "event": "check_skipped",
                    "node_id": node.id,
                    "address": node.address,
                    "reason": "capacity_busy",
                },
            )
        except ConnectivityInProgress:
            if self.telemetry is not None:
                self.telemetry.scheduler_checks_skipped_total.inc(labels={"reason": "in_progress"})
            logger.info(
                "Check already in progress for node %s; skipping duplicate check",
                node.id,
                extra={
                    "event": "check_skipped",
                    "node_id": node.id,
                    "address": node.address,
                    "reason": "in_progress",
                },
            )
        except ConnectivityConfigurationError as exc:
            if self.telemetry is not None:
                self.telemetry.scheduler_errors_total.inc(labels={"reason": "configuration_error"})
            logger.warning(
                "SSH configuration unavailable for node %s: %s",
                node.id,
                exc,
                extra={
                    "event": "check_error",
                    "node_id": node.id,
                    "address": node.address,
                    "reason": "configuration_error",
                },
            )
        except ConnectivityUnavailable:
            logger.info(
                "Connectivity executor unavailable or shutting down for node %s",
                node.id,
                extra={
                    "event": "check_interrupted",
                    "node_id": node.id,
                    "address": node.address,
                    "reason": "unavailable",
                },
            )
        except NodeNotFound:
            if self.telemetry is not None:
                self.telemetry.scheduler_checks_skipped_total.inc(
                    labels={"reason": "node_not_found"}
                )
            logger.info(
                "Node %s not found during scheduled check (removed from inventory)",
                node.id,
                extra={
                    "event": "check_skipped",
                    "node_id": node.id,
                    "reason": "node_not_found",
                },
            )
        except StorageError as exc:
            if self.telemetry is not None:
                self.telemetry.scheduler_errors_total.inc(labels={"reason": "storage_error"})
            logger.error(
                "Storage error during scheduled check for node %s: %s",
                node.id,
                exc,
                extra={
                    "event": "check_error",
                    "node_id": node.id,
                    "address": node.address,
                    "reason": "storage_error",
                },
            )
        except Exception as exc:
            if self.telemetry is not None:
                self.telemetry.scheduler_errors_total.inc(labels={"reason": "unexpected_error"})
            logger.error(
                "Unexpected error during scheduled check for node %s: %s",
                node.id,
                exc,
                exc_info=True,
                extra={
                    "event": "check_error",
                    "node_id": node.id,
                    "address": node.address,
                    "reason": "unexpected_error",
                },
            )

    async def _check_node_bounded(self, node: Node) -> None:
        """Bound concurrency and avoid overlapping checks per node."""
        with self._in_flight_lock:
            if node.id in self._in_flight:
                if self.telemetry is not None:
                    self.telemetry.scheduler_checks_skipped_total.inc(
                        labels={"reason": "already_in_flight"}
                    )
                logger.info(
                    "Scheduler skipped node %s: already in flight in scheduler",
                    node.id,
                    extra={
                        "event": "check_skipped",
                        "node_id": node.id,
                        "address": node.address,
                        "reason": "already_in_flight",
                    },
                )
                return
            self._in_flight.add(node.id)

        worker: asyncio.Task[None] | None = None
        try:
            async with self._semaphore:
                if self._stopping:
                    return
                worker = asyncio.create_task(asyncio.to_thread(self._execute_node_check, node))
                self._workers.add(worker)
                worker.add_done_callback(lambda completed: self._finish_worker(node.id, completed))
                await asyncio.shield(worker)
        finally:
            if worker is None:
                with self._in_flight_lock:
                    self._in_flight.discard(node.id)

    def _finish_worker(self, node_id: int, worker: asyncio.Task[None]) -> None:
        self._workers.discard(worker)
        with self._in_flight_lock:
            self._in_flight.discard(node_id)
        if not worker.cancelled() and (error := worker.exception()) is not None:
            logger.error("Scheduled check task failed for node %s: %s", node_id, error)

    async def run_cycle(self) -> None:
        """Run one sweep across all registered nodes with bounded concurrency."""
        try:
            nodes = await asyncio.to_thread(self.service.inventory.list_nodes)
        except StorageError as exc:
            logger.error(
                "Could not list nodes for scheduled connectivity check: %s",
                exc,
                extra={"event": "cycle_error", "reason": "storage_error"},
            )
            return

        if not nodes or self._stopping:
            return

        tasks = [asyncio.create_task(self._check_node_bounded(node)) for node in nodes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for node, result in zip(nodes, results, strict=True):
            if isinstance(result, BaseException):
                logger.error("Scheduled check task failed for node %s: %s", node.id, result)
        if self.telemetry is not None:
            self.telemetry.scheduler_cycles_total.inc()

    async def _loop(self) -> None:
        """Main scheduler loop."""
        initial_delay = (
            self.initial_delay_seconds
            if self.initial_delay_seconds is not None
            else self.calculate_delay()
        )
        if initial_delay > 0:
            try:
                await asyncio.sleep(initial_delay)
            except asyncio.CancelledError:
                return

        while self._running:
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error during connectivity monitoring cycle: %s", exc, exc_info=True)

            if not self._running:
                break

            delay = self.calculate_delay()
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        """Start periodic scheduling; prevent duplicate schedulers in the same instance."""
        async with self._lock:
            if self._running:
                raise RuntimeError("Connectivity scheduler is already running in this process")
            self._running = True
            self._stopping = False
            if self.telemetry is not None:
                self.telemetry.scheduler_running.set(1.0)
            self._task = asyncio.create_task(self._loop(), name="fleet_connectivity_scheduler")

    async def stop(self, timeout: float = 5.0) -> None:
        """Stop scheduling and cancel active monitoring tasks cleanly."""
        async with self._lock:
            if not self._running and not self._stopping:
                return
            self._running = False
            self._stopping = True
            if self.telemetry is not None:
                self.telemetry.scheduler_running.set(0.0)
            task = self._task
            self._task = None

        if task is not None:
            deadline = asyncio.get_running_loop().time() + timeout
            task.cancel()
            try:
                await asyncio.wait_for(
                    task, timeout=max(0.0, deadline - asyncio.get_running_loop().time())
                )
            except (TimeoutError, asyncio.CancelledError):
                pass
            if self._workers:
                _, pending = await asyncio.wait(
                    tuple(self._workers),
                    timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
                )
                if pending:
                    logger.warning(
                        "Scheduler stopped with %s SSH check thread(s) still running", len(pending)
                    )
