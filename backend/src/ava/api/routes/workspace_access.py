"""Workspace Access Settings API with trusted server-side mutation checks."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.workspace_access import (
    CreateWorkspaceAccessRequest,
    UpdateWorkspaceAccessRequest,
    WorkspaceAccessResponse,
)
from ava.repositories.workspace_access_repository import WorkspaceAccessAlreadyExistsError, WorkspaceAccessConflictError
from ava.services.workspace_access_service import WorkspaceAccessService, WorkspaceAdministrationRequiredError

router = APIRouter(tags=["settings"])


@router.get("/settings/workspace-access", response_model=WorkspaceAccessResponse)
def get_workspace_access(request: Request) -> WorkspaceAccessResponse:
    service: WorkspaceAccessService = request.app.state.workspace_access_service
    return service.state()


@router.post("/settings/workspace-access", response_model=WorkspaceAccessResponse)
def create_workspace_access(
    request: Request, body: CreateWorkspaceAccessRequest
) -> WorkspaceAccessResponse | JSONResponse:
    service: WorkspaceAccessService = request.app.state.workspace_access_service
    try:
        return service.create(body)
    except WorkspaceAdministrationRequiredError as exc:
        return _error(403, "workspace_administration_required", str(exc))
    except WorkspaceAccessAlreadyExistsError as exc:
        return _error(409, "workspace_identity_exists", str(exc))
    except ValueError as exc:
        return _error(422, "workspace_configuration_invalid", str(exc))


@router.put("/settings/workspace-access/{workspace_id}", response_model=WorkspaceAccessResponse)
def update_workspace_access(
    request: Request, workspace_id: str, body: UpdateWorkspaceAccessRequest
) -> WorkspaceAccessResponse | JSONResponse:
    service: WorkspaceAccessService = request.app.state.workspace_access_service
    try:
        return service.update(workspace_id, body)
    except WorkspaceAdministrationRequiredError as exc:
        return _error(403, "workspace_administration_required", str(exc))
    except WorkspaceAccessConflictError as exc:
        return _error(409, "workspace_configuration_conflict", str(exc))
    except ValueError as exc:
        return _error(422, "workspace_configuration_invalid", str(exc))


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(error_code=code, category=ErrorCategory.CONFIGURATION, message=message).model_dump(
            mode="json"
        ),
    )
