"""HTTP contract for a completed SSH observation, status, and onboarding states."""

from datetime import datetime

from pydantic import BaseModel, Field

from fleet_manager.connectivity.freshness import DisplayStatus, SetupState
from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
from fleet_manager.inventory.schemas import NodeResponse


class ConnectivityObservationResponse(BaseModel):
    id: int
    node_id: int
    observed_at: datetime
    outcome: ConnectivityOutcome
    error_category: ConnectivityOutcome | None

    @classmethod
    def from_observation(
        cls, observation: ConnectivityObservation
    ) -> "ConnectivityObservationResponse":
        return cls(
            id=observation.id,
            node_id=observation.node_id,
            observed_at=observation.observed_at,
            outcome=observation.outcome,
            error_category=observation.error_category,
        )


class LatestConnectivityResponse(BaseModel):
    observation: ConnectivityObservationResponse | None


class NodeStatusResponse(BaseModel):
    node: NodeResponse
    display_status: DisplayStatus
    setup_state: SetupState = SetupState.PENDING_SETUP
    reason: str | None = None
    blocking_reason: str | None = None
    observation: ConnectivityObservationResponse | None = None


class FleetStatusResponse(BaseModel):
    observation_ttl_seconds: int
    nodes: list[NodeStatusResponse]
    configuration_issues: list[str] = Field(default_factory=list)
