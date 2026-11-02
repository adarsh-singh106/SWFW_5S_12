"""Prometheus metrics scrape HTTP route."""

from typing import cast

from fastapi import APIRouter, Request, Response

from fleet_manager.metrics.telemetry import Telemetry

router = APIRouter()


@router.get(
    "/metrics",
    response_class=Response,
    include_in_schema=False,
)
def metrics(request: Request) -> Response:
    """Expose control plane metrics in Prometheus text format.

    SCRAPE SECURITY BOUNDARY:
    This endpoint does not require the operator bearer token to facilitate
    Prometheus scraping. It must be restricted to loopback (127.0.0.1 / ::1)
    or private management network interfaces at reverse proxy / firewall boundaries.
    """
    try:
        telemetry = cast(Telemetry, request.app.state.telemetry)
        body = telemetry.render()
    except Exception:
        # A fleet-status failure is represented by collector metrics. An exception
        # escaping rendering means exposition itself failed, so the scrape must fail.
        return Response(
            content="Metrics exposition failed\n", status_code=500, media_type="text/plain"
        )
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
