"""Conversation and message routes.

Kept deliberately thin; orchestration lives in ``ConversationService`` and
the wire contracts live in ``ava.contracts``. Routes operate entirely with
AVA-owned types and never depend on concrete stores or vendor SDKs.

Semantics: ``POST /conversations`` and ``POST /conversations/{id}/messages``
create resources and respond ``201 Created`` (a deviation from ``POST /runs``,
which returns ``200`` with the terminal run outcome). Conversation and
message identifiers are always service-generated; clients never supply them.
Retrieval endpoints return snapshots, not streams.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from ava.api.principal import require_conversation_owner, require_verified_principal
from ava.contracts.conversations import (
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    ExecutionPromptLayers,
    MessageResponse,
    RelocateConversationRequest,
    RunContext,
    SetConversationArchivedRequest,
    SetConversationFolderRequest,
    SetConversationPinnedRequest,
    SetConversationProjectRequest,
    UpdateConversationRequest,
)
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.security_identity import VerifiedPrincipal
from ava.services.conversation_folder_service import (
    ConversationFolderNotFoundError,
    ConversationFolderService,
    ConversationNotFoundForFolderError,
)
from ava.services.conversation_service import (
    ConversationFolderNotFoundForCreationError,
    ConversationHasActiveRunError,
    ConversationNotFoundError,
    ConversationService,
    DuplicateConversationError,
    DuplicateMessageError,
)
from ava.services.project_service import ProjectNotFoundError

router = APIRouter(tags=["conversations"], dependencies=[Depends(require_conversation_owner)])


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def delete_conversation(request: Request, conversation_id: str) -> Response | JSONResponse:
    """Permanently remove a conversation through the application service."""
    service: ConversationService = request.app.state.conversation_service
    try:
        deleted = service.delete_conversation(conversation_id)
    except ConversationHasActiveRunError:
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="conversation_run_active",
                category=ErrorCategory.VALIDATION,
                message="Conversation cannot be deleted while a run is active.",
            ).model_dump(),
        )
    if not deleted:
        return _unknown_conversation(conversation_id)
    return Response(status_code=204)


# ============================================================
# BEGIN: Create Conversation
# ============================================================


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=201,
    responses={409: {"model": ErrorResponse}},
)
async def create_conversation(
    request: Request,
    body: CreateConversationRequest,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> ConversationResponse | JSONResponse:
    """Create an AVA conversation.

    Ava generates the conversation identifier in the service layer; the route
    never invents one. An omitted or blank title resolves to the service's
    default title.
    """
    service: ConversationService = request.app.state.conversation_service
    try:
        return service.create_conversation(
            title=body.title, folder_id=body.folder_id,
            owner_principal_ref=principal.principal_ref, owner_tenant_ref=principal.tenant_ref,
        )
    except DuplicateConversationError as exc:
        return _duplicate_error("conversation_id_conflict", exc)
    except ConversationFolderNotFoundForCreationError:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="conversation_folder_not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"Unknown conversation folder: {body.folder_id}",
            ).model_dump(),
        )


# ============================================================
# END: Create Conversation
# ============================================================


# ============================================================
# BEGIN: List Conversations
# ============================================================


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    request: Request,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
    search: str | None = Query(default=None),
) -> ConversationListResponse:
    """Return AVA conversations in stable order, optionally matching titles."""
    service: ConversationService = request.app.state.conversation_service
    return service.list_conversations_for_owner(principal.principal_ref, principal.tenant_ref, search=search)


# ============================================================
# END: List Conversations
# ============================================================


# ============================================================
# BEGIN: Get Conversation
# ============================================================


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_conversation(request: Request, conversation_id: str) -> ConversationResponse | JSONResponse:
    """Return an AVA conversation as a snapshot, or ``404`` if unknown."""
    service: ConversationService = request.app.state.conversation_service
    conversation = service.get_conversation(conversation_id)
    if conversation is None:
        return _unknown_conversation(conversation_id)
    return conversation


@router.get(
    "/conversations/{conversation_id}/prompt-preview",
    response_model=ExecutionPromptLayers,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def get_conversation_prompt_preview(
    request: Request, conversation_id: str
) -> ExecutionPromptLayers | JSONResponse:
    """Resolve current conversation prompt layers for the no-run inspector state."""
    service: ConversationService = request.app.state.conversation_service
    if service.get_conversation(conversation_id) is None:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="conversation_not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"Unknown conversation: {conversation_id}",
            ).model_dump(),
        )
    builder = request.app.state.execution_prompt_context_service
    try:
        context: RunContext = builder.build(
            RunContext(conversation_id=conversation_id),
            runtime_key=request.app.state.default_runtime_key,
            capabilities=request.app.state.agent_port.get_capabilities(),
        )
    except Exception:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error_code="prompt_preview_unavailable",
                category=ErrorCategory.VALIDATION,
                message="Current prompt configuration could not be resolved.",
            ).model_dump(),
        )
    if context.prompt_layers is None:  # pragma: no cover - builder always supplies layers
        raise RuntimeError("Prompt context builder returned no prompt layers")
    return context.prompt_layers


@router.get("/prompt-preview", response_model=ExecutionPromptLayers)
async def get_global_prompt_preview(request: Request) -> ExecutionPromptLayers:
    """Resolve application-level prompts before any conversation or run exists."""
    context: RunContext = request.app.state.execution_prompt_context_service.build(
        RunContext(),
        runtime_key=request.app.state.default_runtime_key,
        capabilities=request.app.state.agent_port.get_capabilities(),
    )
    if context.prompt_layers is None:  # pragma: no cover - builder always supplies layers
        raise RuntimeError("Prompt context builder returned no prompt layers")
    return context.prompt_layers


# ============================================================
# END: Get Conversation
# ============================================================


# ============================================================
# BEGIN: Rename Conversation
# ============================================================


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    responses={404: {"model": ErrorResponse}},
)
async def rename_conversation(
    request: Request, conversation_id: str, body: UpdateConversationRequest
) -> ConversationResponse | JSONResponse:
    """Rename an AVA conversation by identifier.

    Returns the updated snapshot, or ``404`` if the conversation is unknown.
    The request contract rejects blank titles (``422``) before this route
    runs.
    """
    service: ConversationService = request.app.state.conversation_service
    conversation = service.update_title(conversation_id, body.title)
    if conversation is None:
        return _unknown_conversation(conversation_id)
    return conversation


# ============================================================
# END: Rename Conversation
# ============================================================


@router.patch(
    "/conversations/{conversation_id}/pin",
    response_model=ConversationResponse,
    responses={404: {"model": ErrorResponse}},
)
async def set_conversation_pinned(
    request: Request, conversation_id: str, body: SetConversationPinnedRequest
) -> ConversationResponse | JSONResponse:
    """Set pin state only, returning the usual conversation snapshot."""
    service: ConversationService = request.app.state.conversation_service
    conversation = service.set_pinned(conversation_id, body.is_pinned)
    if conversation is None:
        return _unknown_conversation(conversation_id)
    return conversation


@router.patch(
    "/conversations/{conversation_id}/archive",
    response_model=ConversationResponse,
    responses={404: {"model": ErrorResponse}},
)
async def set_conversation_archived(
    request: Request, conversation_id: str, body: SetConversationArchivedRequest
) -> ConversationResponse | JSONResponse:
    """Set archive state only, returning the usual conversation snapshot."""
    service: ConversationService = request.app.state.conversation_service
    conversation = service.set_archived(conversation_id, body.is_archived)
    if conversation is None:
        return _unknown_conversation(conversation_id)
    return conversation


@router.patch(
    "/conversations/{conversation_id}/folder",
    response_model=ConversationResponse,
    responses={404: {"model": ErrorResponse}},
)
async def set_conversation_folder(
    request: Request, conversation_id: str, body: SetConversationFolderRequest
) -> ConversationResponse | JSONResponse:
    service: ConversationFolderService = request.app.state.conversation_folder_service
    try:
        record = service.set_conversation_folder(conversation_id, body.folder_id)
        return ConversationResponse.model_validate(record.__dict__)
    except ConversationNotFoundForFolderError:
        return _unknown_conversation(conversation_id)
    except ConversationFolderNotFoundError:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="conversation_folder_not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"Unknown conversation folder: {body.folder_id}",
            ).model_dump(),
        )


@router.patch(
    "/conversations/{conversation_id}/project",
    response_model=ConversationResponse,
    responses={404: {"model": ErrorResponse}},
)
async def set_conversation_project(
    request: Request, conversation_id: str, body: SetConversationProjectRequest
) -> ConversationResponse | JSONResponse:
    service: ConversationService = request.app.state.conversation_service
    try:
        conversation = service.set_project(conversation_id, body.project_id)
    except ProjectNotFoundError:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="project_not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"Unknown Project: {body.project_id}",
            ).model_dump(),
        )
    if conversation is None:
        return _unknown_conversation(conversation_id)
    return conversation


@router.patch(
    "/conversations/{conversation_id}/move",
    response_model=ConversationResponse,
    responses={404: {"model": ErrorResponse}},
)
async def relocate_conversation(
    request: Request, conversation_id: str, body: RelocateConversationRequest
) -> ConversationResponse | JSONResponse:
    service: ConversationService = request.app.state.conversation_service
    try:
        conversation = service.relocate(
            conversation_id,
            destination_type=body.destination_type,
            destination_id=body.destination_id,
        )
    except ProjectNotFoundError:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="project_not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"Unknown Project: {body.destination_id}",
            ).model_dump(),
        )
    except ConversationFolderNotFoundError:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error_code="conversation_folder_not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"Unknown conversation folder: {body.destination_id}",
            ).model_dump(),
        )
    if conversation is None:
        return _unknown_conversation(conversation_id)
    return conversation


# ============================================================
# BEGIN: Append Message
# ============================================================


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def append_message(
    request: Request, conversation_id: str, body: CreateMessageRequest
) -> MessageResponse | JSONResponse:
    """Append a message to an AVA conversation.

    Ava generates the message identifier; the route never invents one.
    Returns ``404`` for an unknown conversation and ``409`` if a message
    identifier collides (defensive; the service owns identifier generation).
    """
    service: ConversationService = request.app.state.conversation_service
    try:
        return service.append_message(
            conversation_id,
            content=body.content,
            role=body.role,
            source_run_id=body.source_run_id,
        )
    except ConversationNotFoundError:
        return _unknown_conversation(conversation_id)
    except DuplicateMessageError as exc:
        return _duplicate_error("message_id_conflict", exc)


# ============================================================
# END: Append Message
# ============================================================


# ============================================================
# BEGIN: List Messages
# ============================================================


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
    responses={404: {"model": ErrorResponse}},
)
async def list_messages(request: Request, conversation_id: str) -> ConversationMessagesResponse | JSONResponse:
    """Return a conversation's messages in stable append order.

    Returns ``404`` for an unknown conversation so an empty conversation
    (empty list, ``200``) stays distinguishable.
    """
    service: ConversationService = request.app.state.conversation_service
    messages = service.list_messages(conversation_id)
    if messages is None:
        return _unknown_conversation(conversation_id)
    return messages


# ============================================================
# END: List Messages
# ============================================================


def _unknown_conversation(conversation_id: str) -> JSONResponse:
    """Build a 404 JSON response for an unknown conversation identifier."""
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error_code="conversation_not_found",
            category=ErrorCategory.NOT_FOUND,
            message=f"Unknown conversation: {conversation_id}",
        ).model_dump(),
    )


def _duplicate_error(error_code: str, exc: Exception) -> JSONResponse:
    """Build a 409 JSON response for a duplicate identifier collision."""
    return JSONResponse(
        status_code=409,
        content=ErrorResponse(
            error_code=error_code,
            category=ErrorCategory.VALIDATION,
            message=str(exc),
        ).model_dump(),
    )
