"""Authenticated endpoints for controlled remote node operations."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status

from fleet_manager.errors import OperationNotFound
from fleet_manager.inventory.schemas import ErrorResponse
from fleet_manager.operations.schemas import (
    ExecuteOperationRequest,
    OperationListResponse,
    OperationRecordResponse,
)
from fleet_manager.operations.service import OperationService
from fleet_manager.security.auth import require_operator_token


def _service(request: Request) -> OperationService:
    return cast(OperationService, request.app.state.operation_service)


def _operator_digest(request: Request) -> bytes:
    return cast(bytes, request.app.state.operator_token_digest)


ServiceDependency = Annotated[OperationService, Depends(_service)]
DigestDependency = Annotated[bytes, Depends(_operator_digest)]

router = APIRouter(prefix="/api/nodes", dependencies=[Depends(require_operator_token)])


@router.post(
    "/{node_id}/operations",
    response_model=OperationRecordResponse,
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
def execute_operation(
    node_id: int,
    body: ExecuteOperationRequest,
    service: ServiceDependency,
    digest: DigestDependency,
) -> OperationRecordResponse:
    record = service.execute(
        node_id=node_id,
        action=body.action,
        arguments=body.arguments,
        operator_digest=digest,
    )
    return OperationRecordResponse.from_record(record)


@router.get(
    "/{node_id}/operations",
    response_model=OperationListResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def list_operations(
    node_id: int,
    service: ServiceDependency,
) -> OperationListResponse:
    records = service.list_operations_for_node(node_id)
    return OperationListResponse(
        operations=[OperationRecordResponse.from_record(rec) for rec in records]
    )


@router.get(
    "/{node_id}/operations/{operation_id}",
    response_model=OperationRecordResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_operation(
    node_id: int,
    operation_id: str,
    service: ServiceDependency,
) -> OperationRecordResponse:
    record = service.get_operation(operation_id)
    if record is None or record.node_id != node_id:
        raise OperationNotFound(f"Operation {operation_id} was not found for node {node_id}")
    return OperationRecordResponse.from_record(record)
