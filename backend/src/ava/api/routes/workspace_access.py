"""Workspace Access Settings API with trusted server-side mutation checks."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ava.api.principal import require_verified_principal
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.security_identity import VerifiedPrincipal
from ava.contracts.workspace_access import (
    CreateWorkspaceAccessRequest,
    UpdateWorkspaceAccessRequest,
    WorkspaceAccessResponse,
)
from ava.contracts.workspace_grants import CreateWorkspaceGrantRequest, UpdateWorkspaceGrantRequest, WorkspaceGrantItem
from ava.repositories.workspace_access_repository import WorkspaceAccessAlreadyExistsError, WorkspaceAccessConflictError
from ava.services.workspace_access_service import WorkspaceAccessService, WorkspaceAdministrationRequiredError
from ava.services.workspace_grant_service import WorkspaceGrantAdministrationRequiredError, WorkspaceGrantService

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


@router.get("/settings/workspace-access/{workspace_id}/grants", response_model=list[WorkspaceGrantItem])
def list_workspace_grants(
    request: Request,
    workspace_id: str,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> list[WorkspaceGrantItem] | JSONResponse:
    service: WorkspaceGrantService = request.app.state.workspace_grant_service
    try:
        return list(service.list(principal, workspace_id))
    except WorkspaceGrantAdministrationRequiredError as exc:
        return _error(403, "workspace_grant_administration_required", str(exc))


@router.post("/settings/workspace-access/{workspace_id}/grants", response_model=WorkspaceGrantItem, status_code=201)
def create_workspace_grant(
    request: Request,
    workspace_id: str,
    body: CreateWorkspaceGrantRequest,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> WorkspaceGrantItem | JSONResponse:
    service: WorkspaceGrantService = request.app.state.workspace_grant_service
    try:
        return service.create(principal, workspace_id, body)
    except WorkspaceGrantAdministrationRequiredError as exc:
        return _error(403, "workspace_grant_administration_required", str(exc))
    except PermissionError as exc:
        return _error(403, "workspace_grant_scope_denied", str(exc))
    except ValueError as exc:
        return _error(409, "workspace_grant_conflict", str(exc))


@router.put("/settings/workspace-access/grants/{grant_id}", response_model=WorkspaceGrantItem)
def update_workspace_grant(
    request: Request,
    grant_id: str,
    body: UpdateWorkspaceGrantRequest,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> WorkspaceGrantItem | JSONResponse:
    service: WorkspaceGrantService = request.app.state.workspace_grant_service
    try:
        return service.update(principal, grant_id, body)
    except WorkspaceGrantAdministrationRequiredError as exc:
        return _error(403, "workspace_grant_administration_required", str(exc))
    except PermissionError as exc:
        return _error(403, "workspace_grant_scope_denied", str(exc))
    except ValueError as exc:
        return _error(409, "workspace_grant_conflict", str(exc))


@router.post("/settings/workspace-access/grants/{grant_id}/revoke", response_model=WorkspaceGrantItem)
def revoke_workspace_grant(
    request: Request,
    grant_id: str,
    body: UpdateWorkspaceGrantRequest,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> WorkspaceGrantItem | JSONResponse:
    service: WorkspaceGrantService = request.app.state.workspace_grant_service
    try:
        return service.update(principal, grant_id, body, revoke=True)
    except WorkspaceGrantAdministrationRequiredError as exc:
        return _error(403, "workspace_grant_administration_required", str(exc))
    except PermissionError as exc:
        return _error(403, "workspace_grant_scope_denied", str(exc))
    except ValueError as exc:
        return _error(409, "workspace_grant_conflict", str(exc))


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(error_code=code, category=ErrorCategory.CONFIGURATION, message=message).model_dump(
            mode="json"
        ),
    )
