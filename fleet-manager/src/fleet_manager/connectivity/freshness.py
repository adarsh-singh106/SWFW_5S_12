"""Pure display interpretation of an SSH observation at a chosen clock instant."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
from fleet_manager.connectivity.readiness import SetupState as SetupState
from fleet_manager.connectivity.readiness import derive_setup


class DisplayStatus(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    REACHABLE = "REACHABLE"
    UNREACHABLE = "UNREACHABLE"
    STALE = "STALE"
    CHECK_ERROR = "CHECK_ERROR"


@dataclass(frozen=True, slots=True)
class DerivedStatus:
    status: DisplayStatus
    reason: str | None
    observation: ConnectivityObservation | None
    setup_state: SetupState = SetupState.PENDING_SETUP


def derive_status(
    observation: ConnectivityObservation | None,
    as_of: datetime,
    ttl: timedelta,
    has_connected: bool = False,
) -> DerivedStatus:
    """Describe the SSH endpoint, separating live connectivity status from setup readiness."""
    if observation is None:
        return DerivedStatus(DisplayStatus.NOT_CHECKED, None, None, SetupState.PENDING_SETUP)

    if observation.observed_at.utcoffset() is None or as_of.utcoffset() is None:
        return DerivedStatus(
            DisplayStatus.CHECK_ERROR,
            "INVALID_TIMESTAMP",
            observation,
            SetupState.CONFIGURATION_ERROR,
        )

    age = as_of - observation.observed_at
    if age < timedelta(0):
        return DerivedStatus(
            DisplayStatus.CHECK_ERROR,
            "FUTURE_TIMESTAMP",
            observation,
            SetupState.CONFIGURATION_ERROR,
        )

    validated = has_connected or (
        observation is not None and observation.outcome is ConnectivityOutcome.CONNECTED
    )
    is_trusted = observation is None or observation.outcome not in (
        ConnectivityOutcome.HOST_KEY_UNKNOWN,
        ConnectivityOutcome.HOST_KEY_MISMATCH,
    )
    setup_state, _ = derive_setup(
        observation,
        as_of,
        observation.revision if observation is not None else None,
        trusted=is_trusted,
        credentials_valid=True,
        validated=validated,
    )

    if age > ttl:
        return DerivedStatus(DisplayStatus.STALE, "TTL_EXPIRED", observation, setup_state)

    if observation.outcome is ConnectivityOutcome.CONNECTED:
        return DerivedStatus(DisplayStatus.REACHABLE, None, observation, setup_state)

    if observation.outcome in (
        ConnectivityOutcome.CONNECTION_REFUSED,
        ConnectivityOutcome.CONNECTION_TIMEOUT,
    ):
        return DerivedStatus(
            DisplayStatus.UNREACHABLE, observation.outcome.value, observation, setup_state
        )

    return DerivedStatus(
        DisplayStatus.CHECK_ERROR, observation.outcome.value, observation, setup_state
    )
