"""Public CRUD routes for organizational conversation folders."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ava.contracts.conversation_folders import (
    ConversationFolderListResponse,
    ConversationFolderResponse,
    CreateConversationFolderRequest,
    UpdateConversationFolderRequest,
)
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.services.conversation_folder_service import (
    ConversationFolderNotFoundError,
    ConversationFolderService,
)

router = APIRouter(tags=["conversation folders"])


def _response(record: ConversationFolderRecord) -> ConversationFolderResponse:
    return ConversationFolderResponse(
        id=record.id, name=record.name, created_at=record.created_at, updated_at=record.updated_at
    )


def _not_found(folder_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error_code="conversation_folder_not_found",
            category=ErrorCategory.NOT_FOUND,
            message=f"Unknown conversation folder: {folder_id}",
        ).model_dump(),
    )


@router.post("/conversation-folders", response_model=ConversationFolderResponse, status_code=201)
async def create_conversation_folder(
    request: Request, body: CreateConversationFolderRequest
) -> ConversationFolderResponse:
    service: ConversationFolderService = request.app.state.conversation_folder_service
    return _response(service.create_folder(body.name))


@router.get("/conversation-folders", response_model=ConversationFolderListResponse)
async def list_conversation_folders(request: Request) -> ConversationFolderListResponse:
    service: ConversationFolderService = request.app.state.conversation_folder_service
    return ConversationFolderListResponse(folders=[_response(item) for item in service.list_folders()])


@router.get(
    "/conversation-folders/{folder_id}",
    response_model=ConversationFolderResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_conversation_folder(request: Request, folder_id: str) -> ConversationFolderResponse | JSONResponse:
    service: ConversationFolderService = request.app.state.conversation_folder_service
    try:
        return _response(service.get_folder(folder_id))
    except ConversationFolderNotFoundError:
        return _not_found(folder_id)


@router.patch(
    "/conversation-folders/{folder_id}",
    response_model=ConversationFolderResponse,
    responses={404: {"model": ErrorResponse}},
)
async def rename_conversation_folder(
    request: Request, folder_id: str, body: UpdateConversationFolderRequest
) -> ConversationFolderResponse | JSONResponse:
    service: ConversationFolderService = request.app.state.conversation_folder_service
    try:
        return _response(service.rename_folder(folder_id, body.name))
    except ConversationFolderNotFoundError:
        return _not_found(folder_id)


@router.delete(
    "/conversation-folders/{folder_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
    responses={404: {"model": ErrorResponse}},
)
async def delete_conversation_folder(request: Request, folder_id: str) -> Response | JSONResponse:
    service: ConversationFolderService = request.app.state.conversation_folder_service
    try:
        service.delete_folder(folder_id)
    except ConversationFolderNotFoundError:
        return _not_found(folder_id)
    return Response(status_code=204)
