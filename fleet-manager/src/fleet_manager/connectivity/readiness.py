"""Canonical configuration-bound setup contract, independent of HTTP."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
from fleet_manager.connectivity.trust import (
    calculate_fingerprint,
    endpoint_identity,
    get_operator_public_key,
    parse_public_key,
    trusted_host_key,
)
from fleet_manager.inventory.models import Node


class SetupState(StrEnum):
    PENDING_SETUP = "PENDING_SETUP"
    HOST_KEY_REQUIRED = "HOST_KEY_REQUIRED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    READY = "READY"


def configuration_revision(node: Node, settings: SSHSettings) -> tuple[str, str | None, str]:
    public = get_operator_public_key(settings.private_key_path)
    host = trusted_host_key(node.address, node.ssh_port, settings.known_hosts_path)
    host_fp = calculate_fingerprint(host) if host else None
    data = [
        node.id,
        endpoint_identity(node.address, node.ssh_port),
        settings.username,
        "default_operator",
        str(settings.private_key_path.resolve()),
        calculate_fingerprint(parse_public_key(public)),
        host_fp,
    ]
    revision = hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()
    return revision, host_fp, public


def derive_setup(
    observation: ConnectivityObservation | None,
    now: datetime,
    revision: str | None,
    trusted: bool,
    credentials_valid: bool,
    validated: bool,
) -> tuple[SetupState, str | None]:
    if observation is not None:
        if now.utcoffset() is None or observation.observed_at.utcoffset() is None:
            return SetupState.CONFIGURATION_ERROR, "INVALID_TIMESTAMP"
        if observation.observed_at > now:
            return SetupState.CONFIGURATION_ERROR, "FUTURE_TIMESTAMP"
    if not credentials_valid:
        return (
            SetupState.CONFIGURATION_ERROR,
            "Client credential or trust-store configuration invalid",
        )
    if not trusted:
        return SetupState.HOST_KEY_REQUIRED, "Actual endpoint has no unique trusted host identity"
    if observation is None or observation.revision != revision:
        return (
            SetupState.PENDING_SETUP,
            "Current configuration requires SSH authentication verification",
        )
    if observation.outcome in (
        ConnectivityOutcome.HOST_KEY_UNKNOWN,
        ConnectivityOutcome.HOST_KEY_MISMATCH,
    ):
        return (
            SetupState.HOST_KEY_REQUIRED,
            "Server identity verification failed; administrative review required",
        )
    if observation.outcome == ConnectivityOutcome.AUTH_FAILED:
        return SetupState.AUTHENTICATION_REQUIRED, "Current SSH user/key authentication failed"
    if observation.outcome == ConnectivityOutcome.UNKNOWN_ERROR:
        return SetupState.CONFIGURATION_ERROR, "SSH execution or configuration error"
    if validated:
        return (
            SetupState.READY,
            "Configuration verified; connectivity freshness is reported separately",
        )
    return SetupState.PENDING_SETUP, "Current configuration has no valid successful authentication"
