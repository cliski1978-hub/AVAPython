"""Public CRUD and archive routes for Projects."""

import re
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ava.api.principal import require_project_owner, require_verified_principal
from ava.contracts.conversations import ConversationListResponse, ConversationResponse, CreateConversationRequest
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.project_files import ProjectFileListResponse, ProjectFileResponse
from ava.contracts.projects import (
    CreateProjectRequest,
    ProjectExecutionDefaultsResponse,
    ProjectListResponse,
    ProjectResponse,
    SetProjectArchivedRequest,
    UpdateProjectExecutionDefaultsRequest,
    UpdateProjectRequest,
)
from ava.contracts.security_identity import VerifiedPrincipal
from ava.models.model_registry import ModelDisabledError, UnknownModelError
from ava.repositories.project import ProjectRecord
from ava.repositories.project_file import ProjectFileRecord
from ava.runtimes.resolver import UnknownRuntimeError
from ava.services.conversation_service import (
    ConversationHasActiveRunError,
    ConversationService,
    DuplicateConversationError,
)
from ava.services.project_execution_defaults_service import ProjectExecutionDefaultsService
from ava.services.project_file_service import (
    ProjectFileAlreadyExistsError,
    ProjectFileNotFoundError,
    ProjectFileService,
    ProjectFileStorageError,
)
from ava.services.project_service import (
    DuplicateProjectIdentityError,
    ProjectNotFoundError,
    ProjectService,
)

router = APIRouter(tags=["projects"], dependencies=[Depends(require_project_owner)])


def _project_file_response(record: ProjectFileRecord) -> ProjectFileResponse:
    return ProjectFileResponse(
        id=record.id,
        project_id=record.project_id,
        file_name=record.file_name,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _project_file_not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error_code="project_file_not_found",
            category=ErrorCategory.NOT_FOUND,
            message="Project file not found.",
        ).model_dump(mode="json"),
    )


def _project_file_storage_error() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="project_file_storage_error",
            category=ErrorCategory.INTERNAL,
            message="Project file storage operation failed.",
            recoverable=True,
        ).model_dump(mode="json"),
    )


@router.get("/projects/{project_id}/files", response_model=ProjectFileListResponse)
async def list_project_files(request: Request, project_id: str) -> ProjectFileListResponse | JSONResponse:
    service: ProjectFileService = request.app.state.project_file_service
    try:
        result = ProjectFileListResponse(
            project_id=project_id, files=[_project_file_response(row) for row in service.list(project_id)]
        )
        return JSONResponse(content=result.model_dump(mode="json"))
    except ProjectNotFoundError:
        return _not_found(project_id)


@router.post(
    "/projects/{project_id}/files",
    response_model=ProjectFileResponse,
    status_code=201,
    responses={409: {"model": ErrorResponse}},
)
async def upload_project_file(
    request: Request,
    project_id: str,
    file: Annotated[UploadFile, File()],
    file_name: Annotated[str | None, Form()] = None,
    content_type: Annotated[str | None, Form()] = None,
) -> ProjectFileResponse | JSONResponse:
    service: ProjectFileService = request.app.state.project_file_service
    try:
        record = service.create(
            project_id,
            file_name=file_name if file_name is not None else (file.filename or "upload"),
            content_type=content_type if content_type is not None else file.content_type,
            source=file.file,
        )
        return _project_file_response(record)
    except ProjectNotFoundError:
        return _not_found(project_id)
    except ProjectFileAlreadyExistsError as exc:
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="project_file_name_conflict",
                category=ErrorCategory.VALIDATION,
                message=(
                    f'A file named "{exc.file_name}" already exists in this Project. '
                    "Delete or rename the existing file before uploading another."
                ),
            ).model_dump(mode="json"),
        )
    except ProjectFileStorageError:
        return _project_file_storage_error()
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error_code="invalid_project_file_metadata",
                category=ErrorCategory.VALIDATION,
                message=str(exc),
            ).model_dump(mode="json"),
        )


@router.get("/projects/{project_id}/files/{file_id}", response_model=ProjectFileResponse)
async def get_project_file(request: Request, project_id: str, file_id: str) -> ProjectFileResponse | JSONResponse:
    service: ProjectFileService = request.app.state.project_file_service
    try:
        return _project_file_response(service.get(project_id, file_id))
    except ProjectNotFoundError:
        return _not_found(project_id)
    except ProjectFileNotFoundError:
        return _project_file_not_found()


@router.get("/projects/{project_id}/files/{file_id}/content")
async def download_project_file(request: Request, project_id: str, file_id: str) -> Response:
    service: ProjectFileService = request.app.state.project_file_service
    try:
        record = service.get(project_id, file_id)
        source = service.open_content(project_id, file_id)
    except ProjectNotFoundError:
        return _not_found(project_id)
    except ProjectFileNotFoundError:
        return _project_file_not_found()
    except ProjectFileStorageError:
        return _project_file_storage_error()
    media_type = record.content_type or "application/octet-stream"
    if re.search(r"[\r\n\x00-\x1f\x7f]", media_type):
        media_type = "application/octet-stream"
    disposition_name = quote(record.file_name, safe="")

    async def chunks() -> AsyncIterator[bytes]:
        try:
            while chunk := source.read(1024 * 1024):
                yield chunk
        finally:
            source.close()

    return StreamingResponse(
        chunks(),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{disposition_name}",
        },
    )


@router.delete("/projects/{project_id}/files/{file_id}", status_code=204, response_class=Response)
async def delete_project_file(request: Request, project_id: str, file_id: str) -> Response:
    service: ProjectFileService = request.app.state.project_file_service
    try:
        service.delete(project_id, file_id)
    except ProjectNotFoundError:
        return _not_found(project_id)
    except ProjectFileNotFoundError:
        return _project_file_not_found()
    except ProjectFileStorageError:
        return _project_file_storage_error()
    return Response(status_code=204)


def _response(record: ProjectRecord) -> ProjectResponse:
    return ProjectResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        instructions=record.instructions,
        is_archived=record.is_archived,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _not_found(project_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error_code="project_not_found",
            category=ErrorCategory.NOT_FOUND,
            message=f"Unknown Project: {project_id}",
        ).model_dump(mode="json"),
    )


def _identity_conflict() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=ErrorResponse(
            error_code="project_identity_conflict",
            category=ErrorCategory.INTERNAL,
            message="Could not create Project.",
        ).model_dump(mode="json"),
    )


def _execution_validation(exc: ValueError) -> JSONResponse:
    if isinstance(exc, UnknownRuntimeError):
        error_code, message = "runtime_not_found", "Unknown runtime key."
    elif isinstance(exc, UnknownModelError):
        error_code, message = "model_not_found", "Unknown configured model."
    elif isinstance(exc, ModelDisabledError):
        error_code, message = "model_disabled", "Configured model is disabled."
    else:
        error_code, message = "invalid_project_execution_defaults", "Invalid Project execution defaults."
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(error_code=error_code, category=ErrorCategory.VALIDATION, message=message).model_dump(
            mode="json"
        ),
    )


def _execution_defaults_response(request: Request, record: ProjectRecord) -> ProjectExecutionDefaultsResponse:
    runtime_key = record.execution_defaults.runtime_key
    available = None
    if runtime_key is not None:
        try:
            request.app.state.runtime_resolver.resolve(runtime_key)
            available = True
        except UnknownRuntimeError:
            available = False
    return ProjectExecutionDefaultsResponse(
        project_id=record.id,
        runtime_key=runtime_key,
        model_id=record.execution_defaults.model_id,
        runtime_available=available,
    )


@router.get(
    "/projects/{project_id}/execution-defaults",
    response_model=ProjectExecutionDefaultsResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_project_execution_defaults(
    request: Request, project_id: str
) -> ProjectExecutionDefaultsResponse | JSONResponse:
    service: ProjectExecutionDefaultsService = request.app.state.project_execution_defaults_service
    try:
        return _execution_defaults_response(request, service.get(project_id))
    except ProjectNotFoundError:
        return _not_found(project_id)


@router.patch(
    "/projects/{project_id}/execution-defaults",
    response_model=ProjectExecutionDefaultsResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def update_project_execution_defaults(
    request: Request, project_id: str, body: UpdateProjectExecutionDefaultsRequest
) -> ProjectExecutionDefaultsResponse | JSONResponse:
    service: ProjectExecutionDefaultsService = request.app.state.project_execution_defaults_service
    try:
        return _execution_defaults_response(request, service.update(project_id, body))
    except ProjectNotFoundError:
        return _not_found(project_id)
    except (UnknownRuntimeError, UnknownModelError, ModelDisabledError) as exc:
        return _execution_validation(exc)


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    request: Request, body: CreateProjectRequest,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> ProjectResponse | JSONResponse:
    service: ProjectService = request.app.state.project_service
    try:
        return _response(
            service.create_project(
                name=body.name,
                description=body.description,
                instructions=body.instructions,
                owner_principal_ref=principal.principal_ref,
                owner_tenant_ref=principal.tenant_ref,
            )
        )
    except DuplicateProjectIdentityError:
        return _identity_conflict()


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    request: Request, principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)]
) -> ProjectListResponse:
    service: ProjectService = request.app.state.project_service
    return ProjectListResponse(
        projects=[
            _response(item)
            for item in service.list_projects_for_owner(principal.principal_ref, principal.tenant_ref)
        ]
    )


@router.get(
    "/projects/{project_id}/conversations",
    response_model=ConversationListResponse,
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(require_verified_principal)],
)
async def list_project_conversations(
    request: Request, project_id: str,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> ConversationListResponse | JSONResponse:
    service: ConversationService = request.app.state.conversation_service
    try:
        return service.list_project_conversations_for_owner(project_id, principal.principal_ref, principal.tenant_ref)
    except ProjectNotFoundError:
        return _not_found(project_id)


@router.post(
    "/projects/{project_id}/conversations",
    response_model=ConversationResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    dependencies=[Depends(require_verified_principal)],
)
async def create_project_conversation(
    request: Request, project_id: str, body: CreateConversationRequest,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> ConversationResponse | JSONResponse:
    service: ConversationService = request.app.state.conversation_service
    try:
        return service.create_conversation_in_project(
            project_id, title=body.title,
            owner_principal_ref=principal.principal_ref, owner_tenant_ref=principal.tenant_ref,
        )
    except ProjectNotFoundError:
        return _not_found(project_id)
    except DuplicateConversationError as exc:
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="conversation_id_conflict",
                category=ErrorCategory.VALIDATION,
                message=str(exc),
            ).model_dump(mode="json"),
        )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_project(request: Request, project_id: str) -> ProjectResponse | JSONResponse:
    service: ProjectService = request.app.state.project_service
    try:
        return _response(service.get_project(project_id))
    except ProjectNotFoundError:
        return _not_found(project_id)


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"model": ErrorResponse}},
)
async def update_project(
    request: Request, project_id: str, body: UpdateProjectRequest
) -> ProjectResponse | JSONResponse:
    service: ProjectService = request.app.state.project_service
    try:
        return _response(service.update_project(project_id, body))
    except ProjectNotFoundError:
        return _not_found(project_id)


@router.patch(
    "/projects/{project_id}/archive",
    response_model=ProjectResponse,
    responses={404: {"model": ErrorResponse}},
)
async def set_project_archived(
    request: Request, project_id: str, body: SetProjectArchivedRequest
) -> ProjectResponse | JSONResponse:
    service: ProjectService = request.app.state.project_service
    try:
        return _response(service.set_archived(project_id, body.is_archived))
    except ProjectNotFoundError:
        return _not_found(project_id)


@router.delete(
    "/projects/{project_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
    responses={
        200: {"description": "Project and conversation IDs deleted when requested"},
        404: {"model": ErrorResponse},
    },
)
async def delete_project(
    request: Request,
    project_id: str,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
    delete_conversations: Annotated[bool, Query()] = False,
) -> Response | JSONResponse:
    service: ProjectService = request.app.state.project_service
    conversation_service: ConversationService = request.app.state.conversation_service
    access = getattr(request.app.state, "conversation_access", None)
    try:
        conversations = conversation_service.list_project_conversations(project_id).conversations
        if access is None or any(
            access.can_access(principal.principal_ref, principal.tenant_ref, item.conversation_id) is not True
            for item in conversations
        ):
            return _not_found(project_id)
    except Exception:
        # Without complete project and conversation ownership evidence, do not
        # mutate linked context or cascade a destructive delete.
        return _not_found(project_id)
    try:
        deleted_conversation_ids = service.delete_project(project_id, delete_conversations=delete_conversations)
    except ProjectNotFoundError:
        return _not_found(project_id)
    except ProjectFileStorageError:
        return _project_file_storage_error()
    except ConversationHasActiveRunError:
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error_code="conversation_run_active",
                category=ErrorCategory.VALIDATION,
                message="Project conversations cannot be deleted while a run is active.",
            ).model_dump(),
        )
    if delete_conversations:
        return JSONResponse(
            status_code=200,
            content={"deleted_conversation_ids": list(deleted_conversation_ids or ())},
        )
    return Response(status_code=204)
