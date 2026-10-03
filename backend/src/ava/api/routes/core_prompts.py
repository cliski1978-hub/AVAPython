"""Public CRUD and enabled-state routes for CORE prompt definitions."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ava.contracts.core_prompts import (
    CorePromptAssignmentListResponse,
    CorePromptAssignmentResponse,
    CorePromptListResponse,
    CorePromptResponse,
    CreateCorePromptRequest,
    EffectivePromptSetResponse,
    PromptResolutionContextResponse,
    ResolveCorePromptsRequest,
    ResolvedCorePromptResponse,
    SetCorePromptAssignmentRequest,
    SetCorePromptEnabledRequest,
    UpdateCorePromptRequest,
)
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.repositories.core_prompt import CorePromptRecord
from ava.repositories.core_prompt_assignment import CorePromptAssignmentRecord, CorePromptScopeType
from ava.services.core_prompt_assignment_service import CorePromptAssignmentError, CorePromptAssignmentService
from ava.services.core_prompt_service import (
    CorePromptNotFoundError,
    CorePromptService,
    DuplicateCorePromptIdentityError,
)
from ava.services.effective_prompt_resolver import (
    EffectivePromptResolver,
    PromptResolutionContext,
    PromptResolutionError,
)

router = APIRouter(tags=["core prompts"])


def _response(record: CorePromptRecord) -> CorePromptResponse:
    return CorePromptResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        prompt_text=record.prompt_text,
        category=record.category,
        is_enabled=record.is_enabled,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _not_found(core_prompt_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error_code="core_prompt_not_found",
            category=ErrorCategory.NOT_FOUND,
            message=f"Unknown CORE prompt: {core_prompt_id}",
        ).model_dump(mode="json"),
    )


def _identity_conflict() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=ErrorResponse(
            error_code="core_prompt_identity_conflict",
            category=ErrorCategory.INTERNAL,
            message="Could not create CORE prompt.",
        ).model_dump(mode="json"),
    )


def _assignment_response(
    prompt_id: str, scope: CorePromptScopeType, scope_id: str | None, record: CorePromptAssignmentRecord | None
) -> CorePromptAssignmentResponse:
    return CorePromptAssignmentResponse(
        core_prompt_id=prompt_id,
        scope_type=scope,
        scope_id=scope_id,
        state=record.mode.value if record else "inherit",
        assignment_id=record.id if record else None,
        created_at=record.created_at if record else None,
        updated_at=record.updated_at if record else None,
    )


def _assignment_error(exc: CorePromptAssignmentError) -> JSONResponse:
    not_found = exc.error_code in {
        "core_prompt_not_found",
        "project_not_found",
        "conversation_folder_not_found",
        "conversation_not_found",
        "core_prompt_scope_target_not_found",
    }
    return JSONResponse(
        status_code=404 if not_found else 422,
        content=ErrorResponse(
            error_code=exc.error_code,
            category=ErrorCategory.NOT_FOUND if not_found else ErrorCategory.VALIDATION,
            message=str(exc),
        ).model_dump(mode="json"),
    )


def _resolution_error(exc: PromptResolutionError) -> JSONResponse:
    not_found = exc.error_code in {"conversation_not_found", "runtime_not_found", "capability_not_found"}
    return JSONResponse(
        status_code=404 if not_found else 422,
        content=ErrorResponse(
            error_code=exc.error_code,
            category=ErrorCategory.NOT_FOUND if not_found else ErrorCategory.VALIDATION,
            message=str(exc),
        ).model_dump(mode="json"),
    )


@router.post("/core-prompts/resolve", response_model=EffectivePromptSetResponse)
async def resolve_core_prompts(
    request: Request, body: ResolveCorePromptsRequest
) -> EffectivePromptSetResponse | JSONResponse:
    resolver: EffectivePromptResolver = request.app.state.effective_prompt_resolver
    try:
        result = resolver.resolve(
            PromptResolutionContext(
                conversation_id=body.conversation_id,
                runtime_key=body.runtime_key,
                capabilities=frozenset(item.value for item in body.capabilities),
            )
        )
    except PromptResolutionError as exc:
        return _resolution_error(exc)
    return EffectivePromptSetResponse(
        context=PromptResolutionContextResponse(
            conversation_id=result.context.conversation_id,
            project_id=result.context.project_id,
            folder_id=result.context.folder_id,
            runtime_key=result.context.runtime_key,
            capabilities=list(result.context.capabilities),
        ),
        enabled_prompts=[ResolvedCorePromptResponse(**item.__dict__) for item in result.enabled_prompts],
        excluded_prompts=[ResolvedCorePromptResponse(**item.__dict__) for item in result.excluded_prompts],
    )


@router.post("/core-prompts", response_model=CorePromptResponse, status_code=201)
async def create_core_prompt(request: Request, body: CreateCorePromptRequest) -> CorePromptResponse | JSONResponse:
    service: CorePromptService = request.app.state.core_prompt_service
    try:
        return _response(service.create_core_prompt(body))
    except DuplicateCorePromptIdentityError:
        return _identity_conflict()


@router.get("/core-prompts", response_model=CorePromptListResponse)
async def list_core_prompts(request: Request) -> CorePromptListResponse:
    service: CorePromptService = request.app.state.core_prompt_service
    return CorePromptListResponse(core_prompts=[_response(item) for item in service.list_core_prompts()])


@router.get(
    "/core-prompts/{core_prompt_id}",
    response_model=CorePromptResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_core_prompt(request: Request, core_prompt_id: str) -> CorePromptResponse | JSONResponse:
    service: CorePromptService = request.app.state.core_prompt_service
    try:
        return _response(service.get_core_prompt(core_prompt_id))
    except CorePromptNotFoundError:
        return _not_found(core_prompt_id)


@router.patch(
    "/core-prompts/{core_prompt_id}",
    response_model=CorePromptResponse,
    responses={404: {"model": ErrorResponse}},
)
async def update_core_prompt(
    request: Request, core_prompt_id: str, body: UpdateCorePromptRequest
) -> CorePromptResponse | JSONResponse:
    service: CorePromptService = request.app.state.core_prompt_service
    try:
        return _response(service.update_core_prompt(core_prompt_id, body))
    except CorePromptNotFoundError:
        return _not_found(core_prompt_id)


@router.patch(
    "/core-prompts/{core_prompt_id}/enabled",
    response_model=CorePromptResponse,
    responses={404: {"model": ErrorResponse}},
)
async def set_core_prompt_enabled(
    request: Request, core_prompt_id: str, body: SetCorePromptEnabledRequest
) -> CorePromptResponse | JSONResponse:
    service: CorePromptService = request.app.state.core_prompt_service
    try:
        return _response(service.set_enabled(core_prompt_id, body.is_enabled))
    except CorePromptNotFoundError:
        return _not_found(core_prompt_id)


@router.delete(
    "/core-prompts/{core_prompt_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
    responses={404: {"model": ErrorResponse}},
)
async def delete_core_prompt(request: Request, core_prompt_id: str) -> Response | JSONResponse:
    service: CorePromptService = request.app.state.core_prompt_service
    try:
        service.delete_core_prompt(core_prompt_id)
    except CorePromptNotFoundError:
        return _not_found(core_prompt_id)
    return Response(status_code=204)


@router.get("/core-prompts/{core_prompt_id}/assignments", response_model=CorePromptAssignmentListResponse)
async def list_core_prompt_assignments(
    request: Request, core_prompt_id: str
) -> CorePromptAssignmentListResponse | JSONResponse:
    service: CorePromptAssignmentService = request.app.state.core_prompt_assignment_service
    try:
        records = service.list_for_prompt(core_prompt_id)
    except CorePromptAssignmentError as exc:
        return _assignment_error(exc)
    return CorePromptAssignmentListResponse(
        assignments=[_assignment_response(core_prompt_id, item.scope_type, item.scope_id, item) for item in records]
    )


@router.put("/core-prompts/{core_prompt_id}/assignments", response_model=CorePromptAssignmentResponse)
async def set_core_prompt_assignment(
    request: Request, core_prompt_id: str, body: SetCorePromptAssignmentRequest
) -> CorePromptAssignmentResponse | JSONResponse:
    service: CorePromptAssignmentService = request.app.state.core_prompt_assignment_service
    try:
        record = service.set_assignment(core_prompt_id, body.scope_type, body.scope_id, body.state)
    except CorePromptAssignmentError as exc:
        return _assignment_error(exc)
    return _assignment_response(core_prompt_id, body.scope_type, body.scope_id, record)


@router.get("/core-prompt-assignments", response_model=CorePromptAssignmentListResponse)
async def list_assignments_for_scope(
    request: Request, scope_type: CorePromptScopeType, scope_id: str | None = None
) -> CorePromptAssignmentListResponse | JSONResponse:
    service: CorePromptAssignmentService = request.app.state.core_prompt_assignment_service
    try:
        records = service.list_for_scope(scope_type, scope_id)
    except CorePromptAssignmentError as exc:
        return _assignment_error(exc)
    return CorePromptAssignmentListResponse(
        assignments=[
            _assignment_response(item.core_prompt_id, item.scope_type, item.scope_id, item) for item in records
        ]
    )
