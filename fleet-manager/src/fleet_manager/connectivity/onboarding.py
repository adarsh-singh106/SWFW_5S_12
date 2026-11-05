"""Node setup readiness state and onboarding domain models."""

from pydantic import BaseModel, ConfigDict

from fleet_manager.connectivity.freshness import DisplayStatus
from fleet_manager.connectivity.readiness import SetupState as SetupState


class ServerIdentityInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trust_state: str  # TRUSTED, UNTRUSTED, MISMATCH, UNCHECKED
    presented_fingerprint: str | None = None
    key_type: str | None = None
    known_hosts_source: str


class ClientAuthenticationInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_profile: str = "default_operator"
    ssh_username: str
    public_key: str
    bootstrap_instruction: str
    storage_notice: str


class OnboardingStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: int
    name: str
    address: str
    ssh_port: int
    setup_state: SetupState
    display_status: DisplayStatus
    server_identity: ServerIdentityInfo
    client_authentication: ClientAuthenticationInfo
    is_ready: bool
    blocking_reason: str | None = None


class ScanHostKeyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: int
    address: str
    ssh_port: int
    key_type: str
    fingerprint: str
    trust_state: str
    confirmation: str
    verification_instruction: str


class TrustHostKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: str
    confirmation: str


class TrustHostKeyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: int
    status: str
    enrolled_fingerprint: str
