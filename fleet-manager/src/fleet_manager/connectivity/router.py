"""Authenticated endpoints for one explicit SSH check, observation, and guided onboarding."""

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from fleet_manager.config import SSHSettings, load_ssh_settings
from fleet_manager.connectivity.freshness import derive_status
from fleet_manager.connectivity.onboarding import (
    ClientAuthenticationInfo,
    OnboardingStatusResponse,
    ScanHostKeyResponse,
    ServerIdentityInfo,
    SetupState,
    TrustHostKeyRequest,
    TrustHostKeyResponse,
)
from fleet_manager.connectivity.schemas import (
    ConnectivityObservationResponse,
    FleetStatusResponse,
    LatestConnectivityResponse,
)
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.connectivity.trust import (
    check_host_key_trust,
    enroll_host_key,
    generate_bootstrap_instruction,
    get_operator_public_key,
    get_presented_host_key,
    trusted_host_key,
)
from fleet_manager.errors import ConnectivityConfigurationError, NodeNotFound
from fleet_manager.inventory.schemas import ErrorResponse
from fleet_manager.security.auth import require_operator_token


def _service(request: Request) -> ConnectivityService:
    return cast(ConnectivityService, request.app.state.connectivity_service)


ServiceDependency = Annotated[ConnectivityService, Depends(_service)]
router = APIRouter(prefix="/api/nodes", dependencies=[Depends(require_operator_token)])


@router.get(
    "/status",
    response_model=FleetStatusResponse,
    responses={
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def fleet_status(service: ServiceDependency) -> FleetStatusResponse:
    return service.fleet_status()


@router.post(
    "/{node_id}/connectivity-check",
    response_model=ConnectivityObservationResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def check_connectivity(node_id: int, service: ServiceDependency) -> ConnectivityObservationResponse:
    return ConnectivityObservationResponse.from_observation(service.check(node_id))


@router.get(
    "/{node_id}/connectivity",
    response_model=LatestConnectivityResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def latest_connectivity(node_id: int, service: ServiceDependency) -> LatestConnectivityResponse:
    observation = service.latest(node_id)
    return LatestConnectivityResponse(
        observation=(
            ConnectivityObservationResponse.from_observation(observation)
            if observation is not None
            else None
        )
    )


@router.get(
    "/{node_id}/onboarding",
    response_model=OnboardingStatusResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_onboarding_status(node_id: int, service: ServiceDependency) -> OnboardingStatusResponse:
    """Retrieve guided onboarding status, host key trust state, and client auth bootstrap."""
    node = service.inventory.get_node(node_id)
    if node is None:
        raise NodeNotFound(f"Node {node_id} is not registered")

    observation = service.latest(node_id)
    has_conn = service.has_connected(node_id)
    setup_state, blocking_reason, _, host_fp, public = service.setup(
        node, observation, datetime.now(UTC)
    )
    derived = derive_status(
        observation, datetime.now(UTC), service.observation_ttl, has_connected=has_conn
    )

    # SSH operator settings resolution
    settings: SSHSettings | None = service.settings
    if settings is None:
        try:
            settings = load_ssh_settings()
        except ConnectivityConfigurationError:
            settings = None

    if settings is None:
        server_identity = ServerIdentityInfo(
            trust_state="UNCONFIGURED",
            presented_fingerprint=None,
            key_type=None,
            known_hosts_source="unconfigured",
        )
        client_auth = ClientAuthenticationInfo(
            credential_profile="default_operator",
            ssh_username="unconfigured",
            public_key="unavailable",
            bootstrap_instruction="SSH operator settings not configured",
            storage_notice="Configure SSH private key and known_hosts environment settings",
        )
        return OnboardingStatusResponse(
            node_id=node.id,
            name=node.name,
            address=node.address,
            ssh_port=node.ssh_port,
            setup_state=SetupState.CONFIGURATION_ERROR,
            display_status=derived.status,
            server_identity=server_identity,
            client_authentication=client_auth,
            is_ready=False,
            blocking_reason="SSH operator configuration is missing or invalid",
        )

    # Server Identity Trust State
    trust_state = "UNTRUSTED"
    if host_fp is not None:
        trust_state = "TRUSTED"
    elif observation and observation.outcome == "HOST_KEY_MISMATCH":
        trust_state = "MISMATCH"

    trusted_key = trusted_host_key(node.address, node.ssh_port, settings.known_hosts_path)
    server_identity = ServerIdentityInfo(
        trust_state=trust_state,
        presented_fingerprint=host_fp,
        key_type=trusted_key.get_name() if trusted_key is not None else None,
        known_hosts_source=str(settings.known_hosts_path),
    )

    # Client Authentication configuration (safe derived public key, NEVER private key)
    try:
        pub_key = get_operator_public_key(settings.private_key_path)
        bootstrap_cmd = generate_bootstrap_instruction(settings.username, pub_key)
    except Exception:
        pub_key = "unavailable"
        bootstrap_cmd = "unavailable"

    client_auth = ClientAuthenticationInfo(
        credential_profile="default_operator",
        ssh_username=settings.username,
        public_key=pub_key,
        bootstrap_instruction=bootstrap_cmd,
        storage_notice="Private keys reside in secure server storage and are never exposed.",
    )

    return OnboardingStatusResponse(
        node_id=node.id,
        name=node.name,
        address=node.address,
        ssh_port=node.ssh_port,
        setup_state=setup_state,
        display_status=derived.status,
        server_identity=server_identity,
        client_authentication=client_auth,
        is_ready=(setup_state is SetupState.READY),
        blocking_reason=blocking_reason,
    )


@router.post(
    "/{node_id}/scan-host-key",
    response_model=ScanHostKeyResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def scan_host_key(node_id: int, service: ServiceDependency) -> ScanHostKeyResponse:
    """Probe the endpoint's presented host public key WITHOUT auto-accepting it."""
    node = service.inventory.get_node(node_id)
    if node is None:
        raise NodeNotFound(f"Node {node_id} is not registered")

    settings = service.settings
    if settings is None:
        try:
            settings = load_ssh_settings()
        except ConnectivityConfigurationError as exc:
            raise HTTPException(
                status_code=503, detail="SSH operator settings not configured"
            ) from exc

    try:
        key_type, base64_key, fp = get_presented_host_key(
            node.address, node.ssh_port, timeout=settings.connect_timeout_seconds
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to connect to host: {exc}") from exc

    trust_state = check_host_key_trust(
        node.address, node.ssh_port, settings.known_hosts_path, key_type, base64_key
    )

    clean_type = key_type.replace("ssh-", "")
    instruction = (
        f"Verify this fingerprint matches target server console output: "
        f"ssh-keygen -l -f /etc/ssh/ssh_host_{clean_type}_key.pub"
    )

    return ScanHostKeyResponse(
        node_id=node.id,
        address=node.address,
        ssh_port=node.ssh_port,
        key_type=key_type,
        fingerprint=fp,
        trust_state=trust_state,
        confirmation=service.confirmation(node, fp),
        verification_instruction="Untrusted presented fingerprint. " + instruction,
    )


@router.post(
    "/{node_id}/trust-host-key",
    response_model=TrustHostKeyResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def trust_host_key(
    node_id: int,
    body: TrustHostKeyRequest,
    service: ServiceDependency,
) -> TrustHostKeyResponse:
    """Deliberate confirmation to enroll the verified host key fingerprint into known_hosts."""
    node = service.inventory.get_node(node_id)
    if node is None:
        raise NodeNotFound(f"Node {node_id} is not registered")

    settings = service.settings
    if settings is None:
        try:
            settings = load_ssh_settings()
        except ConnectivityConfigurationError as exc:
            raise HTTPException(
                status_code=503, detail="SSH operator settings not configured"
            ) from exc

    try:
        service.validate_confirmation(node, body.fingerprint.strip(), body.confirmation)
        enrolled_fp = enroll_host_key(
            node.address,
            node.ssh_port,
            settings.known_hosts_path,
            expected_fingerprint=body.fingerprint.strip(),
            timeout=settings.connect_timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to enroll host key: {exc}") from exc

    return TrustHostKeyResponse(
        node_id=node.id,
        status="enrolled",
        enrolled_fingerprint=enrolled_fp,
    )
