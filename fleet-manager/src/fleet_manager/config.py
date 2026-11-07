"""Validated process configuration for the local control plane."""

import hashlib
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from fleet_manager.errors import ConnectivityConfigurationError

TOKEN_ENV = "FLEET_MANAGER_API_TOKEN"
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}", re.ASCII)


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    operator_token_digest: bytes | None


@dataclass(frozen=True, slots=True)
class SSHSettings:
    username: str
    known_hosts_path: Path
    private_key_path: Path
    connect_timeout_seconds: float = 5.0
    authentication_timeout_seconds: float = 5.0
    banner_timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class ConnectivityLimits:
    max_concurrent: int
    total_timeout_seconds: float


DEFAULT_OBSERVATION_TTL_SECONDS = 180
DEFAULT_POLLING_INTERVAL_SECONDS = 60.0
DEFAULT_MONITORING_JITTER_RATIO = 0.1


@dataclass(frozen=True, slots=True)
class MonitoringSettings:
    observation_ttl_seconds: int = DEFAULT_OBSERVATION_TTL_SECONDS
    polling_interval_seconds: float = DEFAULT_POLLING_INTERVAL_SECONDS
    jitter_ratio: float = DEFAULT_MONITORING_JITTER_RATIO
    enabled: bool = True


def load_settings(
    database_path: Path | None = None,
    api_token: str | None = None,
    require_api_token: bool = True,
) -> Settings:
    """Validate process settings; retain only API token digest in application state."""
    raw_token = api_token if api_token is not None else os.getenv(TOKEN_ENV)
    token_digest: bytes | None = None
    if raw_token is not None:
        if _TOKEN_PATTERN.fullmatch(raw_token) is None:
            raise RuntimeError(f"{TOKEN_ENV} must be a 32-128 character URL-safe token")
        token_digest = hashlib.sha256(raw_token.encode("ascii")).digest()
    elif require_api_token:
        raise RuntimeError(f"{TOKEN_ENV} must be a 32-128 character URL-safe token")

    default_path = Path(__file__).resolve().parents[2] / ".local" / "inventory.db"
    configured_path = os.getenv("FLEET_MANAGER_DATABASE_PATH")
    selected_path = database_path or (Path(configured_path) if configured_path else default_path)
    return Settings(selected_path, token_digest)


def load_ssh_settings() -> SSHSettings:
    """Require explicit trust and key paths only when a check is requested."""
    username = os.getenv("FLEET_MANAGER_SSH_USERNAME", "")
    known_hosts = os.getenv("FLEET_MANAGER_SSH_KNOWN_HOSTS", "")
    private_key = os.getenv("FLEET_MANAGER_SSH_PRIVATE_KEY", "")
    if not username or username == "root" or any(c.isspace() for c in username):
        raise ConnectivityConfigurationError("SSH operator configuration is unavailable")
    if not known_hosts or not private_key:
        raise ConnectivityConfigurationError("SSH operator configuration is unavailable")
    known_hosts_path = Path(known_hosts).expanduser()
    private_key_path = Path(private_key).expanduser()
    try:
        if not known_hosts_path.is_file() or not private_key_path.is_file():
            raise ConnectivityConfigurationError("SSH operator configuration is unavailable")
        if os.name == "posix" and private_key_path.stat().st_mode & 0o077:
            raise ConnectivityConfigurationError("SSH operator configuration is unavailable")
    except OSError as exc:
        raise ConnectivityConfigurationError("SSH operator configuration is unavailable") from exc
    return SSHSettings(username, known_hosts_path, private_key_path)


def load_connectivity_limits() -> ConnectivityLimits:
    """Fail startup on unsafe admission or deadline configuration."""
    try:
        capacity = int(os.getenv("FLEET_MANAGER_SSH_MAX_CONCURRENT", "4"))
        timeout = float(os.getenv("FLEET_MANAGER_SSH_TOTAL_TIMEOUT_SECONDS", "12"))
    except ValueError as exc:
        raise RuntimeError("SSH concurrency or total timeout setting is invalid") from exc
    if not 1 <= capacity <= 16 or not math.isfinite(timeout) or not 1 <= timeout <= 60:
        raise RuntimeError("SSH concurrency or total timeout setting is out of range")
    return ConnectivityLimits(capacity, timeout)


def load_monitoring_settings(
    ttl_seconds: int | None = None,
    interval_seconds: float | None = None,
    jitter_ratio: float | None = None,
    enabled: bool | None = None,
) -> MonitoringSettings:
    """Load and validate observation TTL and automatic monitoring settings."""
    try:
        ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else int(
                os.getenv(
                    "FLEET_MANAGER_OBSERVATION_TTL_SECONDS",
                    str(DEFAULT_OBSERVATION_TTL_SECONDS),
                )
            )
        )
    except ValueError as exc:
        raise RuntimeError("FLEET_MANAGER_OBSERVATION_TTL_SECONDS must be an integer") from exc

    if not 1 <= ttl <= 86400:
        raise RuntimeError("Observation TTL must be between 1 and 86400 seconds")

    try:
        interval = (
            interval_seconds
            if interval_seconds is not None
            else float(
                os.getenv(
                    "FLEET_MANAGER_MONITORING_INTERVAL_SECONDS",
                    str(DEFAULT_POLLING_INTERVAL_SECONDS),
                )
            )
        )
    except ValueError as exc:
        raise RuntimeError("FLEET_MANAGER_MONITORING_INTERVAL_SECONDS must be a number") from exc

    if not math.isfinite(interval) or not 0.1 <= interval <= 3600.0:
        raise RuntimeError("Monitoring interval must be between 0.1 and 3600.0 seconds")

    try:
        jitter = (
            jitter_ratio
            if jitter_ratio is not None
            else float(
                os.getenv(
                    "FLEET_MANAGER_MONITORING_JITTER_RATIO",
                    str(DEFAULT_MONITORING_JITTER_RATIO),
                )
            )
        )
    except ValueError as exc:
        raise RuntimeError("FLEET_MANAGER_MONITORING_JITTER_RATIO must be a number") from exc

    if not math.isfinite(jitter) or not 0.0 <= jitter <= 0.5:
        raise RuntimeError("Monitoring jitter ratio must be between 0.0 and 0.5")

    if enabled is None:
        raw_enabled = os.getenv("FLEET_MANAGER_MONITORING_ENABLED", "true").lower().strip()
        is_enabled = raw_enabled in {"1", "true", "yes", "on"}
    else:
        is_enabled = enabled

    return MonitoringSettings(
        observation_ttl_seconds=ttl,
        polling_interval_seconds=interval,
        jitter_ratio=jitter,
        enabled=is_enabled,
    )


DEFAULT_OPERATION_MAX_CONCURRENT = 4
DEFAULT_OPERATION_TIMEOUT_SECONDS = 15.0
DEFAULT_OPERATION_MAX_OUTPUT_BYTES = 65536  # 64 KiB


@dataclass(frozen=True, slots=True)
class OperationLimits:
    max_concurrent: int = DEFAULT_OPERATION_MAX_CONCURRENT
    total_timeout_seconds: float = DEFAULT_OPERATION_TIMEOUT_SECONDS
    max_output_bytes: int = DEFAULT_OPERATION_MAX_OUTPUT_BYTES


def load_operation_limits(
    max_concurrent: int | None = None,
    total_timeout_seconds: float | None = None,
    max_output_bytes: int | None = None,
) -> OperationLimits:
    """Fail startup on unsafe operation concurrency, timeout, or output limits."""
    try:
        capacity = (
            max_concurrent
            if max_concurrent is not None
            else int(
                os.getenv(
                    "FLEET_MANAGER_OPERATION_MAX_CONCURRENT",
                    str(DEFAULT_OPERATION_MAX_CONCURRENT),
                )
            )
        )
        timeout = (
            total_timeout_seconds
            if total_timeout_seconds is not None
            else float(
                os.getenv(
                    "FLEET_MANAGER_OPERATION_TOTAL_TIMEOUT_SECONDS",
                    str(DEFAULT_OPERATION_TIMEOUT_SECONDS),
                )
            )
        )
        output_limit = (
            max_output_bytes
            if max_output_bytes is not None
            else int(
                os.getenv(
                    "FLEET_MANAGER_OPERATION_MAX_OUTPUT_BYTES",
                    str(DEFAULT_OPERATION_MAX_OUTPUT_BYTES),
                )
            )
        )
    except ValueError as exc:
        raise RuntimeError("Operation concurrency, timeout, or output limit is invalid") from exc

    if not 1 <= capacity <= 16:
        raise RuntimeError("Operation max concurrency must be between 1 and 16")
    if not math.isfinite(timeout) or not 1.0 <= timeout <= 120.0:
        raise RuntimeError("Operation total timeout must be between 1.0 and 120.0 seconds")
    if not 1024 <= output_limit <= 1048576:
        raise RuntimeError(
            "Operation max output bytes must be between 1024 and 1048576 (1 KiB to 1 MiB)"
        )

    return OperationLimits(capacity, timeout, output_limit)
