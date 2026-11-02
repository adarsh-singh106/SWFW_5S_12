"""Authenticated inventory HTTP routes."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status

from fleet_manager.inventory.schemas import (
    ErrorResponse,
    NodeListResponse,
    NodeRegistrationRequest,
    NodeResponse,
)
from fleet_manager.inventory.service import NodeService
from fleet_manager.security.auth import require_operator_token


def _service(request: Request) -> NodeService:
    return cast(NodeService, request.app.state.node_service)


NodeServiceDependency = Annotated[NodeService, Depends(_service)]
router = APIRouter(prefix="/api", dependencies=[Depends(require_operator_token)])


@router.post(
    "/nodes",
    response_model=NodeResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def register_node(
    payload: NodeRegistrationRequest, node_service: NodeServiceDependency
) -> NodeResponse:
    node = node_service.register(payload.name, payload.address, payload.ssh_port)
    return NodeResponse.from_node(node)


@router.get(
    "/nodes",
    response_model=NodeListResponse,
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def list_nodes(node_service: NodeServiceDependency) -> NodeListResponse:
    return NodeListResponse(
        nodes=[NodeResponse.from_node(node) for node in node_service.list_nodes()]
    )
