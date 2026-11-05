"""Application composition, lifecycle, and shared HTTP error mapping."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from fleet_manager.config import (
    MonitoringSettings,
    OperationLimits,
    SSHSettings,
    load_connectivity_limits,
    load_monitoring_settings,
    load_operation_limits,
    load_settings,
)
from fleet_manager.connectivity.executor import (
    DirectSSHExecutor,
    ProcessSSHExecutor,
    SSHCheckExecutor,
    SSHTransport,
)
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.connectivity.router import router as connectivity_router
from fleet_manager.connectivity.scheduler import ConnectivityScheduler
from fleet_manager.connectivity.service import ConnectivityService
from fleet_manager.errors import (
    AuthenticationError,
    ConnectivityBusy,
    ConnectivityConfigurationError,
    ConnectivityInProgress,
    ConnectivityUnavailable,
    DuplicateNode,
    InvalidAction,
    InvalidNode,
    InvalidOperationArguments,
    NodeNotFound,
    OperationBusy,
    OperationInProgress,
    OperationNotFound,
    OperationUnavailable,
    StorageError,
)
from fleet_manager.inventory.repository import SQLiteNodeRepository
from fleet_manager.inventory.router import router as inventory_router
from fleet_manager.inventory.service import NodeService
from fleet_manager.metrics.router import router as metrics_router
from fleet_manager.metrics.telemetry import Telemetry
from fleet_manager.operations.executor import (
    DirectOperationExecutor,
    OperationExecutor,
    ProcessOperationExecutor,
)
from fleet_manager.operations.repository import SQLiteOperationsRepository
from fleet_manager.operations.router import router as operations_router
from fleet_manager.operations.service import OperationService
from fleet_manager.operations.transport import OperationTransport
from fleet_manager.ui.router import STATIC_DIR
from fleet_manager.ui.router import router as ui_router


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_app(
    database_path: Path | None = None,
    api_token: str | None = None,
    ssh_transport: SSHTransport | None = None,
    ssh_settings: SSHSettings | None = None,
    ssh_executor: SSHCheckExecutor | None = None,
    monitoring_settings: MonitoringSettings | None = None,
    enable_scheduler: bool | None = None,
    observation_ttl_seconds: int | None = None,
    monitoring_interval_seconds: float | None = None,
    operation_transport: OperationTransport | None = None,
    operation_executor: OperationExecutor | None = None,
    operation_limits: OperationLimits | None = None,
) -> FastAPI:
    """Construct the API; validate settings and initialize storage on startup."""
    if ssh_transport is not None and ssh_executor is not None:
        raise ValueError("Provide either an SSH transport or an SSH executor")
    if operation_transport is not None and operation_executor is not None:
        raise ValueError("Provide either an operation transport or an operation executor")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.is_ready = False
        scheduler: ConnectivityScheduler | None = None
        executor: SSHCheckExecutor | None = None
        active_op_executor: OperationExecutor | None = None

        try:
            settings = load_settings(database_path, api_token)
            limits = load_connectivity_limits()
            active_operation_limits = (
                operation_limits if operation_limits is not None else load_operation_limits()
            )
            active_monitoring = (
                monitoring_settings
                if monitoring_settings is not None
                else load_monitoring_settings(
                    ttl_seconds=observation_ttl_seconds,
                    interval_seconds=monitoring_interval_seconds,
                    enabled=enable_scheduler,
                )
            )
            application.state.operator_token_digest = settings.operator_token_digest
            application.state.monitoring_settings = active_monitoring
            telemetry = Telemetry()
            application.state.telemetry = telemetry

            # Initialize SQLite repositories in explicit dependency order (v1 -> v2 -> v3)
            inventory_repository = SQLiteNodeRepository(settings.database_path)
            inventory_repository.initialize()
            application.state.inventory_repository = inventory_repository

            connectivity_repository = SQLiteConnectivityRepository(settings.database_path)
            connectivity_repository.initialize()
            application.state.connectivity_repository = connectivity_repository

            operations_repository = SQLiteOperationsRepository(settings.database_path)
            operations_repository.initialize()
            application.state.operations_repository = operations_repository

            # SINGLE-WORKER CRASH RECOVERY:
            # Reconcile orphaned RUNNING operations to UNCERTAIN before accepting HTTP requests.
            # INVARIANT: Assumes a single application process with SQLite and in-memory locks.
            # In a multi-worker deployment, a newly starting worker would blindly mark active
            # operations owned by other live workers as UNCERTAIN. Multi-worker deployments
            # require distributed lease-based coordination.
            operations_repository.reconcile_in_flight()

            application.state.node_service = NodeService(inventory_repository)
            executor = (
                ssh_executor
                if ssh_executor is not None
                else (
                    DirectSSHExecutor(ssh_transport)
                    if ssh_transport is not None
                    else ProcessSSHExecutor(limits)
                )
            )
            active_op_executor = (
                operation_executor
                if operation_executor is not None
                else (
                    DirectOperationExecutor(operation_transport, limits=active_operation_limits)
                    if operation_transport is not None
                    else ProcessOperationExecutor(active_operation_limits)
                )
            )
            connectivity_service = ConnectivityService(
                inventory_repository,
                connectivity_repository,
                executor,
                ssh_settings,
                observation_ttl=timedelta(seconds=active_monitoring.observation_ttl_seconds),
                telemetry=telemetry,
            )
            application.state.connectivity_service = connectivity_service
            telemetry.service = connectivity_service
            telemetry.connectivity_max_concurrent.set(float(limits.max_concurrent))

            operation_service = OperationService(
                inventory_repository,
                operations_repository,
                active_op_executor,
                ssh_settings,
                telemetry=telemetry,
            )
            application.state.operation_service = operation_service

            if active_monitoring.enabled:
                scheduler = ConnectivityScheduler(
                    service=connectivity_service,
                    interval_seconds=active_monitoring.polling_interval_seconds,
                    jitter_ratio=active_monitoring.jitter_ratio,
                    max_concurrent=limits.max_concurrent,
                    telemetry=telemetry,
                )
                application.state.connectivity_scheduler = scheduler
                await scheduler.start()

            application.state.is_ready = True
            yield
        finally:
            application.state.is_ready = False
            try:
                if scheduler is not None:
                    await scheduler.stop()
            finally:
                try:
                    if executor is not None:
                        executor.close()
                finally:
                    if active_op_executor is not None:
                        active_op_executor.close()

    application = FastAPI(title="Fleet Manager Inventory API", lifespan=lifespan)
    application.state.is_ready = False

    @application.get(
        "/healthz",
        response_model=dict[str, str],
        tags=["probes"],
        summary="Basic process liveness probe",
    )
    def healthz() -> JSONResponse:
        """Process liveness probe; returns minimal JSON without touching DB or SSH."""
        return JSONResponse(status_code=200, content={"status": "ok"})

    @application.get(
        "/readyz",
        response_model=dict[str, str],
        responses={
            200: {"description": "Application and dependencies are ready"},
            503: {
                "description": "Application is starting, shutting down, or storage is unavailable"
            },
        },
        tags=["probes"],
        summary="Application readiness probe",
    )
    def readyz(request: Request) -> JSONResponse:
        """Application readiness probe; verifies startup completion and database access."""
        if not getattr(request.app.state, "is_ready", False):
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        repository = getattr(request.app.state, "inventory_repository", None)
        if repository is None:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        try:
            repository.check_ready()
        except Exception:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return JSONResponse(status_code=200, content={"status": "ready"})

    @application.exception_handler(AuthenticationError)
    async def authentication_error(_request: Request, _exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "unauthorized", "message": "Authentication required"}},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error(422, "invalid_request", "Request body has missing or invalid fields")

    @application.exception_handler(InvalidNode)
    async def invalid_node_error(_request: Request, exc: InvalidNode) -> JSONResponse:
        return _error(422, "invalid_node", str(exc))

    @application.exception_handler(DuplicateNode)
    async def duplicate_node_error(_request: Request, _exc: DuplicateNode) -> JSONResponse:
        return _error(409, "duplicate_node", "Node endpoint is already registered")

    @application.exception_handler(StorageError)
    async def storage_error(_request: Request, _exc: StorageError) -> JSONResponse:
        return _error(503, "storage_unavailable", "Inventory storage is unavailable")

    @application.exception_handler(NodeNotFound)
    async def node_not_found(_request: Request, _exc: NodeNotFound) -> JSONResponse:
        return _error(404, "node_not_found", "Node is not registered")

    @application.exception_handler(ConnectivityConfigurationError)
    async def connectivity_configuration_error(
        _request: Request, _exc: ConnectivityConfigurationError
    ) -> JSONResponse:
        return _error(503, "connectivity_unavailable", "SSH verification is not configured")

    @application.exception_handler(ConnectivityUnavailable)
    async def connectivity_unavailable(
        _request: Request, _exc: ConnectivityUnavailable
    ) -> JSONResponse:
        return _error(503, "connectivity_unavailable", "SSH verification is unavailable")

    @application.exception_handler(ConnectivityBusy)
    async def connectivity_busy(_request: Request, _exc: ConnectivityBusy) -> JSONResponse:
        return _error(429, "connectivity_busy", "SSH check capacity is exhausted")

    @application.exception_handler(ConnectivityInProgress)
    async def connectivity_in_progress(
        _request: Request, _exc: ConnectivityInProgress
    ) -> JSONResponse:
        return _error(409, "connectivity_in_progress", "Node already has an active SSH check")

    @application.exception_handler(InvalidAction)
    async def invalid_action_error(_request: Request, exc: InvalidAction) -> JSONResponse:
        return _error(422, "invalid_action", str(exc))

    @application.exception_handler(InvalidOperationArguments)
    async def invalid_operation_arguments_error(
        _request: Request, exc: InvalidOperationArguments
    ) -> JSONResponse:
        return _error(422, "invalid_arguments", str(exc))

    @application.exception_handler(OperationBusy)
    async def operation_busy_error(_request: Request, exc: OperationBusy) -> JSONResponse:
        return _error(429, "operation_busy", str(exc))

    @application.exception_handler(OperationInProgress)
    async def operation_in_progress_error(
        _request: Request, exc: OperationInProgress
    ) -> JSONResponse:
        return _error(409, "operation_in_progress", str(exc))

    @application.exception_handler(OperationNotFound)
    async def operation_not_found_error(_request: Request, exc: OperationNotFound) -> JSONResponse:
        return _error(404, "operation_not_found", str(exc))

    @application.exception_handler(OperationUnavailable)
    async def operation_unavailable_error(
        _request: Request, exc: OperationUnavailable
    ) -> JSONResponse:
        return _error(503, "operation_unavailable", str(exc))

    @application.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, "http_error", str(exc.detail))

    application.include_router(inventory_router)
    application.include_router(connectivity_router)
    application.include_router(operations_router)
    application.include_router(metrics_router)
    application.include_router(ui_router)
    if STATIC_DIR.is_dir():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return application


app = create_app()
