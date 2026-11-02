"""One-node SSH observation use case, independent of HTTP and Paramiko."""

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fleet_manager.config import SSHSettings, load_ssh_settings
from fleet_manager.connectivity.executor import SSHCheckExecutor
from fleet_manager.connectivity.freshness import derive_status
from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.schemas import (
    ConnectivityObservationResponse,
    FleetStatusResponse,
    NodeStatusResponse,
)
from fleet_manager.errors import (
    ConnectivityBusy,
    ConnectivityConfigurationError,
    ConnectivityInProgress,
    ConnectivityUnavailable,
    NodeNotFound,
)
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.inventory.schemas import NodeResponse

if TYPE_CHECKING:
    from fleet_manager.metrics.telemetry import Telemetry


class ConnectivityService:
    def __init__(
        self,
        inventory: SQLiteNodeRepository,
        observations: SQLiteConnectivityRepository,
        executor: SSHCheckExecutor,
        settings: SSHSettings | None = None,
        observation_ttl: timedelta | None = None,
        telemetry: "Telemetry | None" = None,
    ) -> None:
        self.inventory = inventory
        self.observations = observations
        self.executor = executor
        self.settings = settings
        self.observation_ttl = (
            observation_ttl if observation_ttl is not None else timedelta(seconds=180)
        )
        self.telemetry = telemetry

    def check(self, node_id: int) -> ConnectivityObservation:
        node = self.inventory.get_node(node_id)
        if node is None:
            raise NodeNotFound
        settings = self.settings if self.settings is not None else load_ssh_settings()
        if self.telemetry is not None:
            self.telemetry.connectivity_active_checks.inc()
        started_at = time.monotonic()
        try:
            try:
                outcome = self.executor.run(node, settings)
            except (
                ConnectivityConfigurationError,
                ConnectivityBusy,
                ConnectivityInProgress,
                ConnectivityUnavailable,
            ):
                raise
            except Exception:
                outcome = ConnectivityOutcome.UNKNOWN_ERROR
        finally:
            if self.telemetry is not None:
                self.telemetry.connectivity_active_checks.dec()

        duration = max(0.0, time.monotonic() - started_at)
        if self.telemetry is not None:
            self.telemetry.connectivity_checks_total.inc(labels={"outcome": outcome.value})
            self.telemetry.connectivity_check_duration_seconds.observe(
                duration, labels={"outcome": outcome.value}
            )

        return self.observations.save(node.id, datetime.now(UTC), outcome)

    def latest(self, node_id: int) -> ConnectivityObservation | None:
        if self.inventory.get_node(node_id) is None:
            raise NodeNotFound
        return self.observations.latest(node_id)

    def fleet_status(self, as_of: datetime | None = None) -> FleetStatusResponse:
        now = as_of if as_of is not None else datetime.now(UTC)
        nodes = self.inventory.list_nodes()
        statuses: list[NodeStatusResponse] = []
        for node in nodes:
            observation = self.observations.latest(node.id)
            derived = derive_status(observation, now, self.observation_ttl)
            statuses.append(
                NodeStatusResponse(
                    node=NodeResponse.from_node(node),
                    display_status=derived.status,
                    reason=derived.reason,
                    observation=(
                        ConnectivityObservationResponse.from_observation(derived.observation)
                        if derived.observation is not None
                        else None
                    ),
                )
            )
        return FleetStatusResponse(
            observation_ttl_seconds=int(self.observation_ttl.total_seconds()),
            nodes=statuses,
        )
