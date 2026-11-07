"""Authenticated fixed telemetry route for registered nodes."""

from fastapi import APIRouter, Depends, HTTPException, Request

from fleet_manager.inventory.schemas import ErrorResponse
from fleet_manager.metrics.health import PrometheusHealth
from fleet_manager.security.auth import require_operator_token

router = APIRouter(prefix="/api/nodes", dependencies=[Depends(require_operator_token)])


@router.get(
    "/{node_id}/health",
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def node_health(node_id: int, request: Request) -> dict[str, object]:
    if request.query_params:
        raise HTTPException(status_code=400, detail="Query parameters are not supported")
    node = request.app.state.inventory_repository.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node is not registered")
    health: PrometheusHealth = request.app.state.prometheus_health
    return await health.node(node_id, node.address, node.name)
