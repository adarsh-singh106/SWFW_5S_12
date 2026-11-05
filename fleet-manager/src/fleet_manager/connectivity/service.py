"""One-node SSH observation use case, independent of HTTP and Paramiko."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fleet_manager.config import SSHSettings, load_ssh_settings
from fleet_manager.connectivity.executor import SSHCheckExecutor
from fleet_manager.connectivity.freshness import derive_status
from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
from fleet_manager.connectivity.readiness import SetupState, configuration_revision, derive_setup
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
from fleet_manager.inventory.models import Node
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
        self._confirmation_secret = secrets.token_bytes(32)

    def check(self, node_id: int) -> ConnectivityObservation:
        node = self.inventory.get_node(node_id)
        if node is None:
            raise NodeNotFound
        settings = self.settings if self.settings is not None else load_ssh_settings()
        revision, _, _ = self.configuration(node)
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

        current = self.inventory.get_node(node.id)
        after = self.configuration(current)[0] if current else None
        if after != revision:
            revision = None
        return self.observations.save(node.id, datetime.now(UTC), outcome, revision)

    def latest(self, node_id: int) -> ConnectivityObservation | None:
        if self.inventory.get_node(node_id) is None:
            raise NodeNotFound
        return self.observations.latest(node_id)

    def has_connected(self, node_id: int) -> bool:
        if self.inventory.get_node(node_id) is None:
            raise NodeNotFound
        node = self.inventory.get_node(node_id)
        assert node is not None
        return self.observations.has_connected(node_id, self.configuration(node)[0])

    def configuration(self, node: Node) -> tuple[str | None, str | None, str | None]:
        try:
            settings = self.settings if self.settings is not None else load_ssh_settings()
            return configuration_revision(node, settings)
        except (ConnectivityConfigurationError, ValueError, OSError):
            return None, None, None

    def setup(
        self, node: Node, observation: ConnectivityObservation | None, now: datetime
    ) -> tuple[SetupState, str | None, str | None, str | None, str | None]:
        revision, host_fp, public = self.configuration(node)
        state, reason = derive_setup(
            observation,
            now,
            revision,
            host_fp is not None,
            public is not None,
            self.observations.has_connected(node.id, revision),
        )
        return state, reason, revision, host_fp, public

    def confirmation(self, node: Node, fingerprint: str) -> str:
        payload = json.dumps(
            [
                node.id,
                node.address,
                node.ssh_port,
                self.configuration(node)[0],
                fingerprint,
                int(time.time()),
            ],
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(self._confirmation_secret, payload, hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(payload).decode() + "." + signature

    def validate_confirmation(self, node: Node, fingerprint: str, confirmation: str) -> None:
        try:
            encoded, signature = confirmation.split(".")
            payload = base64.urlsafe_b64decode(encoded)
            expected = hmac.new(self._confirmation_secret, payload, hashlib.sha256).hexdigest()
            values = json.loads(payload)
            assert hmac.compare_digest(signature, expected)
            assert values[:5] == [
                node.id,
                node.address,
                node.ssh_port,
                self.configuration(node)[0],
                fingerprint,
            ]
            assert 0 <= time.time() - values[5] <= 300
        except Exception as exc:
            raise ValueError(
                "Scan confirmation expired or endpoint/configuration changed; rescan"
            ) from exc

    def fleet_status(self, as_of: datetime | None = None) -> FleetStatusResponse:
        now = as_of if as_of is not None else datetime.now(UTC)
        nodes = self.inventory.list_nodes()
        observations = self.observations.latest_all()
        statuses: list[NodeStatusResponse] = []
        for node in nodes:
            observation = observations.get(node.id)
            setup, blocking, _, _, _ = self.setup(node, observation, now)
            has_conn = setup is SetupState.READY
            derived = derive_status(observation, now, self.observation_ttl, has_connected=has_conn)
            statuses.append(
                NodeStatusResponse(
                    node=NodeResponse.from_node(node),
                    display_status=derived.status,
                    setup_state=setup,
                    blocking_reason=blocking,
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
