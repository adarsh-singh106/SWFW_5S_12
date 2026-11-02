"""Pure display interpretation of an SSH observation at a chosen clock instant."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome


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


def derive_status(
    observation: ConnectivityObservation | None, as_of: datetime, ttl: timedelta
) -> DerivedStatus:
    """Describe the SSH endpoint, never the health of the whole Linux node."""
    if observation is None:
        return DerivedStatus(DisplayStatus.NOT_CHECKED, None, None)
    if observation.observed_at.utcoffset() is None or as_of.utcoffset() is None:
        return DerivedStatus(DisplayStatus.CHECK_ERROR, "INVALID_TIMESTAMP", observation)
    age = as_of - observation.observed_at
    if age < timedelta(0):
        return DerivedStatus(DisplayStatus.CHECK_ERROR, "FUTURE_TIMESTAMP", observation)
    if age > ttl:
        return DerivedStatus(DisplayStatus.STALE, "TTL_EXPIRED", observation)
    if observation.outcome is ConnectivityOutcome.CONNECTED:
        return DerivedStatus(DisplayStatus.REACHABLE, None, observation)
    if observation.outcome in (
        ConnectivityOutcome.CONNECTION_REFUSED,
        ConnectivityOutcome.CONNECTION_TIMEOUT,
    ):
        return DerivedStatus(DisplayStatus.UNREACHABLE, observation.outcome.value, observation)
    return DerivedStatus(DisplayStatus.CHECK_ERROR, observation.outcome.value, observation)
