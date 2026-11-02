"""Display status is derived from immutable SSH observations and one clock instant."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from fleet_manager.connectivity.freshness import DisplayStatus, derive_status
from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
TTL = timedelta(seconds=60)


def _observation(outcome: ConnectivityOutcome, when: datetime) -> ConnectivityObservation:
    return ConnectivityObservation(1, 7, when, outcome, None if outcome == "CONNECTED" else outcome)


def test_never_checked_is_explicit() -> None:
    result = derive_status(None, NOW, TTL)
    assert result.status is DisplayStatus.NOT_CHECKED
    assert result.reason is None


def test_fresh_success_is_reachable_only_within_ttl() -> None:
    original = _observation(ConnectivityOutcome.CONNECTED, NOW - timedelta(seconds=60))
    result = derive_status(original, NOW, TTL)
    assert result.status is DisplayStatus.REACHABLE
    assert result.observation is original
    assert result.reason is None

    expired = derive_status(original, NOW + timedelta(microseconds=1), TTL)
    assert expired.status is DisplayStatus.STALE
    assert expired.reason == "TTL_EXPIRED"
    assert expired.observation is not None
    assert expired.observation.outcome is ConnectivityOutcome.CONNECTED


@pytest.mark.parametrize(
    "outcome",
    [ConnectivityOutcome.CONNECTION_TIMEOUT, ConnectivityOutcome.CONNECTION_REFUSED],
)
def test_fresh_transport_failure_is_endpoint_unreachable(outcome: ConnectivityOutcome) -> None:
    result = derive_status(_observation(outcome, NOW), NOW, TTL)
    assert result.status is DisplayStatus.UNREACHABLE
    assert result.reason == outcome.value


@pytest.mark.parametrize(
    "outcome",
    [
        ConnectivityOutcome.HOST_KEY_UNKNOWN,
        ConnectivityOutcome.HOST_KEY_MISMATCH,
        ConnectivityOutcome.AUTH_FAILED,
        ConnectivityOutcome.DNS_ERROR,
        ConnectivityOutcome.UNKNOWN_ERROR,
        ConnectivityOutcome.TIMEOUT,
        ConnectivityOutcome.EXECUTION_TIMEOUT,
    ],
)
def test_fresh_verification_or_lookup_failure_is_check_error(outcome: ConnectivityOutcome) -> None:
    result = derive_status(_observation(outcome, NOW), NOW, TTL)
    assert result.status is DisplayStatus.CHECK_ERROR
    assert result.reason == outcome.value


def test_failed_observation_ages_to_stale_without_erasing_reason() -> None:
    original = _observation(ConnectivityOutcome.AUTH_FAILED, NOW - timedelta(seconds=61))
    result = derive_status(original, NOW, TTL)
    assert result.status is DisplayStatus.STALE
    assert result.reason == "TTL_EXPIRED"
    assert result.observation is not None
    assert result.observation.error_category is ConnectivityOutcome.AUTH_FAILED


def test_future_or_naive_timestamp_cannot_be_reported_reachable() -> None:
    future = derive_status(
        _observation(ConnectivityOutcome.CONNECTED, NOW + timedelta(seconds=1)), NOW, TTL
    )
    assert future.status is DisplayStatus.CHECK_ERROR
    assert future.reason == "FUTURE_TIMESTAMP"

    naive = derive_status(
        _observation(ConnectivityOutcome.CONNECTED, NOW.replace(tzinfo=None)), NOW, TTL
    )
    assert naive.status is DisplayStatus.CHECK_ERROR
    assert naive.reason == "INVALID_TIMESTAMP"

    naive_clock = derive_status(
        _observation(ConnectivityOutcome.CONNECTED, NOW), NOW.replace(tzinfo=None), TTL
    )
    assert naive_clock.status is DisplayStatus.CHECK_ERROR
    assert naive_clock.reason == "INVALID_TIMESTAMP"


def test_timezone_offset_is_normalized_by_datetime_arithmetic() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    same_instant = NOW.astimezone(offset)
    result = derive_status(_observation(ConnectivityOutcome.CONNECTED, same_instant), NOW, TTL)
    assert result.status is DisplayStatus.REACHABLE
