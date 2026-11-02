"""SSH observation values independent of HTTP and transport libraries."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ConnectivityOutcome(StrEnum):
    CONNECTED = "CONNECTED"
    HOST_KEY_UNKNOWN = "HOST_KEY_UNKNOWN"
    HOST_KEY_MISMATCH = "HOST_KEY_MISMATCH"
    AUTH_FAILED = "AUTH_FAILED"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    TIMEOUT = "TIMEOUT"
    DNS_ERROR = "DNS_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass(frozen=True, slots=True)
class ConnectivityObservation:
    id: int
    node_id: int
    observed_at: datetime
    outcome: ConnectivityOutcome
    error_category: ConnectivityOutcome | None
