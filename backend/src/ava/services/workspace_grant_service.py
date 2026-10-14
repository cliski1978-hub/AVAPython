"""Trusted administration and revocation for Workspace access grants."""

from datetime import UTC, datetime
from uuid import uuid4

from ava.contracts.security_identity import VerifiedPrincipal
from ava.contracts.workspace_grants import (
    CreateWorkspaceGrantRequest,
    UpdateWorkspaceGrantRequest,
    WorkspaceGrant,
    WorkspaceGrantAdministrationPort,
    WorkspaceGrantItem,
    WorkspaceGrantStatus,
)
from ava.repositories.workspace_access_repository import WorkspaceAccessRepository
from ava.repositories.workspace_grant_repository import WorkspaceGrantConflictError, WorkspaceGrantRepository


class WorkspaceGrantAdministrationRequiredError(PermissionError):
    """No trusted grant administrator authorized the requested change."""


class WorkspaceGrantService:
    def __init__(
        self,
        *,
        grants: WorkspaceGrantRepository,
        workspaces: WorkspaceAccessRepository,
        administration: WorkspaceGrantAdministrationPort | None = None,
    ) -> None:
        self._grants = grants
        self._workspaces = workspaces
        self._administration = administration

    def list(self, principal: VerifiedPrincipal, workspace_id: str) -> tuple[WorkspaceGrantItem, ...]:
        configuration = self._workspaces.get(workspace_id)
        if configuration is None or not self._can_manage(principal, workspace_id, "list"):
            raise WorkspaceGrantAdministrationRequiredError("Workspace grant administration is unavailable")
        del configuration
        return tuple(WorkspaceGrantItem.from_grant(item) for item in self._grants.list_for_workspace(workspace_id))

    def create(
        self, principal: VerifiedPrincipal, workspace_id: str, request: CreateWorkspaceGrantRequest
    ) -> WorkspaceGrantItem:
        self._require_admin(principal, workspace_id, "create")
        configuration = self._workspaces.get(workspace_id)
        if configuration is None or configuration.status.value != "active":
            raise ValueError("Workspace is unavailable")
        if configuration.revision != request.expected_workspace_revision:
            raise WorkspaceGrantConflictError("Workspace configuration revision changed")
        if request.tenant_ref != principal.tenant_ref:
            raise PermissionError("Grant tenant must match the authenticated administrator scope")
        if not set(request.capabilities).issubset(configuration.allowed_capabilities):
            raise ValueError("Grant capabilities exceed the Workspace configuration ceiling")
        now = datetime.now(UTC)
        grant = WorkspaceGrant(
            grant_id=uuid4().hex,
            workspace_id=workspace_id,
            principal_ref=request.principal_ref,
            tenant_ref=request.tenant_ref,
            run_id=request.run_id,
            capabilities=request.capabilities,
            workspace_configuration_revision=configuration.revision,
            status=WorkspaceGrantStatus.ACTIVE,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        self._grants.create(grant)
        return WorkspaceGrantItem.from_grant(grant)

    def update(
        self,
        principal: VerifiedPrincipal,
        grant_id: str,
        request: UpdateWorkspaceGrantRequest,
        *,
        revoke: bool = False,
    ) -> WorkspaceGrantItem:
        grant = self._grants.get(grant_id)
        if grant is None:
            raise ValueError("Workspace grant is unavailable")
        self._require_admin(principal, grant.workspace_id, "revoke" if revoke else "update")
        if grant.status == WorkspaceGrantStatus.REVOKED:
            raise ValueError("Revoked Workspace grants cannot be updated or reactivated")
        configuration = self._workspaces.get(grant.workspace_id)
        if configuration is None or configuration.status.value != "active":
            raise ValueError("Workspace is unavailable")
        if grant.tenant_ref != principal.tenant_ref:
            raise PermissionError("Workspace grant is outside the administrator tenant scope")
        if request.expected_revision != grant.revision:
            raise WorkspaceGrantConflictError("Workspace grant revision changed")
        if not revoke and not set(request.capabilities).issubset(configuration.allowed_capabilities):
            raise ValueError("Grant capabilities exceed the Workspace configuration ceiling")
        updated = grant.model_copy(
            update={
                "capabilities": () if revoke else request.capabilities,
                "workspace_configuration_revision": configuration.revision,
                "status": WorkspaceGrantStatus.REVOKED if revoke else WorkspaceGrantStatus.ACTIVE,
                "revision": grant.revision + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        updated = WorkspaceGrant.model_validate(updated.model_dump())
        self._grants.compare_and_set(grant.revision, updated)
        return WorkspaceGrantItem.from_grant(updated)

    def _can_manage(self, principal: VerifiedPrincipal, workspace_id: str, action: str) -> bool:
        try:
            return self._administration is not None and self._administration.can_manage(
                principal, workspace_id=workspace_id, action=action
            ) is True
        except Exception:
            return False

    def _require_admin(self, principal: VerifiedPrincipal, workspace_id: str, action: str) -> None:
        if not self._can_manage(principal, workspace_id, action):
            raise WorkspaceGrantAdministrationRequiredError("Workspace grant administration is unavailable")
