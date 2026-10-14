"""Run routes.

Kept deliberately thin; orchestration lives in ``RunService`` and the wire
contracts live in ``ava.contracts``. Routes operate entirely with AVA-owned
types and never depend on concrete agent adapters or provider SDKs.

Semantics: ``POST /runs`` creates the run and returns its stable identity
immediately (status 202). Execution continues in the background and yields a
normalized lifecycle, available both as a snapshot and as an SSE stream.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from ava.api.principal import principal_is_current, require_verified_principal
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.events import EventType, RunEvent
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse
from ava.contracts.run_inspection import ContextWindowAccounting, RunInspection, RunListItem
from ava.contracts.security_identity import VerifiedPrincipal
from ava.services.context_construction_service import ContextConstructionError
from ava.services.run_service import (
    CancellationRequestError,
    ConversationRunActiveError,
    RunNotSupersedableError,
    RunRelationshipError,
    RunService,
)

router = APIRouter(tags=["runs"])


@router.post("/runs/context-preview", response_model=ContextWindowAccounting)
async def preview_context_window(
    request: Request, body: RunRequest, principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)]
) -> ContextWindowAccounting | JSONResponse:
    """Estimate the current draft using the same resolved execution and budget policy as a run."""
    service: RunService = request.app.state.run_service
    if body.workspace_id is not None:
        # The legacy OpenHands tool factory consumes the globally configured
        # Workspace binding and cannot yet narrow it with this principal's
        # durable grant. Do not start a Workspace-bound Run until the runtime
        # path itself enforces principal-scoped authority.
        return JSONResponse(
            status_code=503,
            content={"detail": "Workspace-scoped execution is not provisioned for authenticated Runs."},
        )
    if body.conversation_id is not None and not _can_access_conversation(request, principal, body.conversation_id):
        return JSONResponse(status_code=503, content={"detail": "Conversation ownership is not provisioned."})
    try:
        result = service.preview_context_window(body)
        if result is None:
            return JSONResponse(status_code=422, content={"detail": "Context preview is unavailable."})
        return result
    except ContextConstructionError:
        return JSONResponse(status_code=422, content={"detail": "Conversation context is unavailable."})
    except Exception:
        return JSONResponse(status_code=422, content={"detail": "Execution selection could not be resolved."})


@router.get("/runs", response_model=list[RunListItem])
async def list_conversation_runs(
    request: Request,
    conversation_id: Annotated[str, Query(min_length=1)],
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> list[RunListItem]:
    """List the captured runs that belong to one conversation."""
    return [
        RunListItem(
            run_id=record.run_id,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            execution_mode=record.execution_mode,
        )
        for record in request.app.state.run_access_service.list_for_conversation(conversation_id, principal)
    ]


# ============================================================
# BEGIN: Start Run
# ============================================================


@router.post("/runs", response_model=RunResponse, status_code=202)
async def start_run(
    request: Request,
    body: RunRequest,
    background_tasks: BackgroundTasks,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> RunResponse | JSONResponse:
    """Start an AVA run.

    Ava generates and persists the run identifier before returning. Execution
    continues in an application task; callers may immediately observe the run
    through its snapshot or its SSE stream.
    """
    service: RunService = request.app.state.run_service
    if body.workspace_id is not None:
        return JSONResponse(
            status_code=503,
            content={"detail": "Workspace-scoped execution is not provisioned for authenticated Runs."},
        )
    if body.conversation_id is not None and not _can_access_conversation(request, principal, body.conversation_id):
        return JSONResponse(
            status_code=503,
            content={"detail": "Conversation ownership is not provisioned for authenticated Run context."},
        )
    try:
        prepared = service.prepare_run(body, owner=principal)
        if isinstance(prepared, RunResponse):
            return prepared
        background_tasks.add_task(service.execute_prepared_run, prepared)
        created = service.get_run(prepared.run_id)
        if created is None:  # pragma: no cover - prepare_run just created it
            raise RuntimeError("prepared run disappeared before response")
        return created
    except RunNotSupersedableError as exc:
        # A well-formed request naming a run that cannot be branched from: it is
        # unknown, belongs to another conversation, or is still active. Reported
        # as its own eligibility refusal so a stale client can tell "you asked
        # for the impossible" from "your request was malformed".
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="run_not_supersedable",
                category=ErrorCategory.VALIDATION,
                message=str(exc),
            ).model_dump(),
        )
    except ConversationRunActiveError as exc:
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="conversation_run_active",
                category=ErrorCategory.VALIDATION,
                message=str(exc),
            ).model_dump(),
        )
    except RunRelationshipError as exc:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error_code="invalid_run_relationship",
                category=ErrorCategory.VALIDATION,
                message=str(exc),
            ).model_dump(),
        )
    except ContextConstructionError as exc:
        # The relationship was accepted, so the durable graph could not be
        # resolved into context. Reported deterministically instead of
        # silently executing the run without its history.
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error_code="context_construction_failed",
                category=ErrorCategory.INTERNAL,
                message=str(exc),
            ).model_dump(),
        )


# ============================================================
# END: Start Run
# ============================================================


# ============================================================
# BEGIN: Stream Run Events
# ============================================================

_STREAM_POLL_INTERVAL_SECONDS = 0.1
_STREAM_HEARTBEAT_TICKS = 150


@router.get("/runs/{run_id}/stream", response_model=None)
async def stream_run(
    request: Request,
    run_id: str,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse | JSONResponse:
    """Observe one run's persisted AVA events as standards-compliant SSE.

    The stream is intentionally an observer: it neither starts, settles, nor
    cancels a run. A connection close has no lifecycle meaning.
    """
    service: RunService = request.app.state.run_service
    if request.app.state.run_access_service.get_authorized(run_id, principal) is None:
        return _unknown_run(run_id)
    events = service.get_run_events(run_id, after_sequence=0)
    latest_sequence = events[-1].sequence if events else 0
    # Unlike a replay read, an ahead stream cursor would wait forever: future
    # events continue at ``latest_sequence + 1``, never at the claimed cursor.
    if after_sequence > latest_sequence:
        return _invalid_resume_cursor(run_id, after_sequence, latest_sequence)
    return StreamingResponse(
        _run_event_stream(request, service, run_id, principal, after_sequence=after_sequence),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _run_event_stream(
    request: Request, service: RunService, run_id: str, principal: VerifiedPrincipal, *, after_sequence: int = 0
) -> AsyncIterator[str]:
    """Yield persisted events after a cursor, then tail later persisted ones.

    Every pass reads from the durable event log after the last emitted sequence.
    That single cursor loop closes the historical-catch-up/live-tail race: an
    event persisted while a prior pass is being emitted appears on the next.
    """
    delivered_sequence = after_sequence
    idle_ticks = 0
    while True:
        if (
            not principal_is_current(request, principal)
            or request.app.state.run_access_service.get_authorized(run_id, principal) is None
        ):
            return
        if await request.is_disconnected():
            return
        events = service.get_run_events(run_id, after_sequence=delivered_sequence)
        if events is None:
            return
        emitted = False
        for event in events:
            emitted = True
            delivered_sequence = event.sequence
            yield _encode_sse_event(event)
            if event.event_type in {
                EventType.RUN_COMPLETED,
                EventType.RUN_FAILED,
                EventType.RUN_CANCELLED,
            }:
                return
        if emitted:
            idle_ticks = 0
            continue
        run = service.get_run(run_id)
        # A status/event crash gap is historical truth, not permission to
        # manufacture a terminal event or hold an already-terminal stream open.
        if run is None or run.status.is_terminal:
            return
        idle_ticks += 1
        if idle_ticks >= _STREAM_HEARTBEAT_TICKS:
            idle_ticks = 0
            yield ": heartbeat\n\n"
        await asyncio.sleep(_STREAM_POLL_INTERVAL_SECONDS)


def _encode_sse_event(event: RunEvent) -> str:
    """Serialize the AVA transport envelope using SSE's standard framing."""
    data = json.dumps(jsonable_encoder(event), separators=(",", ":"), sort_keys=True)
    return f"id: {event.event_id}\nevent: {event.event_type.value}\ndata: {data}\n\n"


# ============================================================
# END: Stream Run Events
# ============================================================


# ============================================================
# BEGIN: Cancel Run
# ============================================================


@router.post("/runs/{run_id}/cancel", response_model=RunResponse, status_code=200)
async def cancel_run(
    request: Request, run_id: str, principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)]
) -> RunResponse | JSONResponse:
    """Durably request cancellation and return the actual run status.

    A request timestamp confirms intent, not a terminal outcome. The service
    performs best-effort cancellation; the returned status can remain active.
    """
    service: RunService = request.app.state.run_service
    if request.app.state.run_access_service.get_authorized(run_id, principal) is None:
        return _unknown_run(run_id)
    try:
        return await service.cancel_run(run_id)
    except CancellationRequestError:
        return JSONResponse(
            status_code=503,
            content=ErrorResponse(
                error_code="cancellation_request_failed",
                category=ErrorCategory.INTERNAL,
                message="Unable to persist cancellation request. Retry or read the run status.",
            ).model_dump(),
        )


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
async def get_run(
    request: Request, run_id: str, principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)]
) -> RunResponse | JSONResponse:
    """Return the stored state for an AVA run as a snapshot.

    Retrieval is not streaming; this returns exactly what the service
    recorded so far.
    """
    service: RunService = request.app.state.run_service
    if request.app.state.run_access_service.get_authorized(run_id, principal) is None:
        return _unknown_run(run_id)
    run = service.get_run(run_id)
    return run if run is not None else _unknown_run(run_id)


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
async def get_run_events(
    request: Request,
    run_id: str,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
) -> list[RunEvent] | JSONResponse:
    """Return an AVA run's normalized events in append order.

    Snapshot retrieval only; this is not a streaming or SSE endpoint.
    """
    service: RunService = request.app.state.run_service
    if request.app.state.run_access_service.get_authorized(run_id, principal) is None:
        return _unknown_run(run_id)
    events = service.get_run_events(run_id, after_sequence=after_sequence)
    if events is None:
        return _unknown_run(run_id)
    return events


@router.get("/runs/{run_id}/inspection", response_model=RunInspection, responses={404: {"model": ErrorResponse}})
async def get_run_inspection(
    request: Request, run_id: str, principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)]
) -> RunInspection | JSONResponse:
    """Return backend-captured execution facts and the ordered normalized event stream."""
    service: RunService = request.app.state.run_service
    if request.app.state.run_access_service.get_authorized(run_id, principal) is None:
        return _unknown_run(run_id)
    inspection = service.get_run_inspection(run_id)
    if inspection is None:
        return _unknown_run(run_id)
    return inspection


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


def _can_access_conversation(request: Request, principal: VerifiedPrincipal, conversation_id: str) -> bool:
    try:
        return request.app.state.conversation_access.can_access(
            principal.principal_ref, principal.tenant_ref, conversation_id
        ) is True
    except Exception:
        return False


def _invalid_resume_cursor(run_id: str, after_sequence: int, latest_sequence: int) -> JSONResponse:
    """Reject a stream cursor that cannot ever observe a future event."""
    return JSONResponse(
        status_code=409,
        content=ErrorResponse(
            error_code="invalid_resume_cursor",
            category=ErrorCategory.VALIDATION,
            message=(
                f"Resume cursor {after_sequence} is ahead of the latest event "
                f"sequence {latest_sequence} for run {run_id}."
            ),
        ).model_dump(),
    )
