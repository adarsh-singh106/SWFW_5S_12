"""Authenticated endpoints for one explicit SSH check and latest observation."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status

from fleet_manager.connectivity.schemas import (
    ConnectivityObservationResponse,
    FleetStatusResponse,
    LatestConnectivityResponse,
)
from fleet_manager.connectivity.service import ConnectivityService
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
