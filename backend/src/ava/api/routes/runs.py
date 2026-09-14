"""Run routes.

Kept deliberately thin; orchestration lives in ``RunService`` and the wire
contracts live in ``ava.contracts``. Routes operate entirely with AVA-owned
types and never depend on concrete agent adapters or provider SDKs.

Semantics: ``POST /runs`` awaits the configured agent's run to completion
before responding (status 200 with a terminal ``RunResponse``). It is not a
streaming or background endpoint; each run yields a normalized, retrievable
event lifecycle. Retrieval endpoints return snapshots, not streams.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.events import RunEvent
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse
from ava.services.run_service import RunService

router = APIRouter(tags=["runs"])


# ============================================================
# BEGIN: Start Run
# ============================================================


@router.post("/runs", response_model=RunResponse, status_code=200)
async def start_run(request: Request, body: RunRequest) -> RunResponse:
    """Start an AVA run.

    Ava generates the run identifier in the service layer; the route never
    invents one. The response reflects the run outcome that the configured
    agent produced for the request.
    """
    service: RunService = request.app.state.run_service
    return await service.start_run(body)


# ============================================================
# END: Start Run
# ============================================================


# ============================================================
# BEGIN: Cancel Run
# ============================================================


@router.post("/runs/{run_id}/cancel", response_model=RunResponse, status_code=200)
async def cancel_run(request: Request, run_id: str) -> RunResponse:
    """Cancel an in-progress AVA run.

    Cancellation logic lives in the service/agent; this route only forwards
    the run identifier and returns the AVA-owned ``RunResponse``.
    """
    service: RunService = request.app.state.run_service
    return await service.cancel_run(run_id)


# ============================================================
# END: Cancel Run
# ============================================================


# ============================================================
# BEGIN: Get Run
# ============================================================


@router.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_run(request: Request, run_id: str) -> RunResponse | JSONResponse:
    """Return the stored state for an AVA run as a snapshot.

    Retrieval is not streaming; this returns exactly what the service
    recorded so far.
    """
    service: RunService = request.app.state.run_service
    run = service.get_run(run_id)
    if run is None:
        return _unknown_run(run_id)
    return run


# ============================================================
# END: Get Run
# ============================================================


# ============================================================
# BEGIN: Get Run Events
# ============================================================


@router.get(
    "/runs/{run_id}/events",
    response_model=list[RunEvent],
    responses={404: {"model": ErrorResponse}},
)
async def get_run_events(request: Request, run_id: str) -> list[RunEvent] | JSONResponse:
    """Return an AVA run's normalized events in append order.

    Snapshot retrieval only; this is not a streaming or SSE endpoint.
    """
    service: RunService = request.app.state.run_service
    events = service.get_run_events(run_id)
    if events is None:
        return _unknown_run(run_id)
    return events


# ============================================================
# END: Get Run Events
# ============================================================


def _unknown_run(run_id: str) -> JSONResponse:
    """Build a 404 JSON response for an unknown run identifier."""
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error_code="run_not_found",
            category=ErrorCategory.NOT_FOUND,
            message=f"Unknown run: {run_id}",
        ).model_dump(),
    )