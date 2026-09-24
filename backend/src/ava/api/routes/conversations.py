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

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ava.contracts.conversations import (
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    MessageResponse,
    UpdateConversationRequest,
)
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.services.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
    DuplicateConversationError,
    DuplicateMessageError,
)

router = APIRouter(tags=["conversations"])


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
    request: Request, body: CreateConversationRequest
) -> ConversationResponse | JSONResponse:
    """Create an AVA conversation.

    Ava generates the conversation identifier in the service layer; the route
    never invents one. An omitted or blank title resolves to the service's
    default title.
    """
    service: ConversationService = request.app.state.conversation_service
    try:
        return service.create_conversation(title=body.title)
    except DuplicateConversationError as exc:
        return _duplicate_error("conversation_id_conflict", exc)


# ============================================================
# END: Create Conversation
# ============================================================


# ============================================================
# BEGIN: List Conversations
# ============================================================


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(request: Request) -> ConversationListResponse:
    """Return all AVA conversations in stable insertion order."""
    service: ConversationService = request.app.state.conversation_service
    return service.list_conversations()


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
async def get_conversation(
    request: Request, conversation_id: str
) -> ConversationResponse | JSONResponse:
    """Return an AVA conversation as a snapshot, or ``404`` if unknown."""
    service: ConversationService = request.app.state.conversation_service
    conversation = service.get_conversation(conversation_id)
    if conversation is None:
        return _unknown_conversation(conversation_id)
    return conversation


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
async def list_messages(
    request: Request, conversation_id: str
) -> ConversationMessagesResponse | JSONResponse:
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