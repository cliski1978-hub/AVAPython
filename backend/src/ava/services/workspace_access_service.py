"""Administrative Workspace configuration; registration is not an execution grant."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ava.contracts.workspace_access import (
    CreateWorkspaceAccessRequest,
    UpdateWorkspaceAccessRequest,
    WorkspaceAccessConfiguration,
    WorkspaceAccessItem,
    WorkspaceAccessResponse,
    WorkspaceAccessStatus,
    WorkspaceAdministrationPort,
)
from ava.repositories.workspace_access_repository import WorkspaceAccessRepository


class WorkspaceAdministrationRequiredError(PermissionError):
    pass


class DenyWorkspaceAdministration:
    """Default boundary: ordinary Web/Desktop sessions cannot administer roots."""

    def can_manage(self) -> bool:
        return False


class WorkspaceAccessService:
    def __init__(
        self,
        repository: WorkspaceAccessRepository,
        administration: WorkspaceAdministrationPort | None = None,
        *,
        on_workspace_changed: Callable[[str], object] | None = None,
    ) -> None:
        self._repository = repository
        self._administration = administration or DenyWorkspaceAdministration()
        self._on_workspace_changed = on_workspace_changed

    def _can_manage(self) -> bool:
        try:
            return self._administration.can_manage() is True
        except Exception:
            return False

    @staticmethod
    def _root(value: str) -> str:
        supplied = Path(value)
        if not supplied.is_absolute():
            raise ValueError("Workspace root must be an absolute directory")
        try:
            root = supplied.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("Workspace root must be an existing directory") from exc
        if not root.is_dir() or root != supplied:
            raise ValueError("Workspace root must be a canonical existing directory")
        return str(root)

    @staticmethod
    def _item(configuration: WorkspaceAccessConfiguration, *, disclose_root: bool) -> WorkspaceAccessItem:
        return WorkspaceAccessItem(
            workspace_id=configuration.workspace_id,
            name=configuration.name,
            kind=configuration.kind,
            root_path=configuration.root_path if disclose_root else None,
            allowed_capabilities=configuration.allowed_capabilities,
            status=configuration.status,
            revision=configuration.revision,
            created_at=configuration.created_at,
            updated_at=configuration.updated_at,
        )

    def state(self) -> WorkspaceAccessResponse:
        can_manage = self._can_manage()
        try:
            configurations = self._repository.list()
            items = tuple(self._item(item, disclose_root=can_manage) for item in configurations)
        except (ValueError, OSError, ValidationError):
            return WorkspaceAccessResponse(
                workspaces=(), can_manage=can_manage, roots_disclosed=False, configuration_status="invalid"
            )
        return WorkspaceAccessResponse(
            workspaces=items, can_manage=can_manage, roots_disclosed=can_manage, configuration_status="valid"
        )

    def create(self, request: CreateWorkspaceAccessRequest) -> WorkspaceAccessResponse:
        self._require_admin()
        now = datetime.now(UTC)
        configuration = WorkspaceAccessConfiguration(
            workspace_id=request.workspace_id,
            name=request.name,
            kind=request.kind,
            root_path=self._root(request.root_path),
            allowed_capabilities=request.allowed_capabilities,
            status=WorkspaceAccessStatus.ACTIVE,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        self._repository.create(configuration)
        return self.state()

    def update(self, workspace_id: str, request: UpdateWorkspaceAccessRequest) -> WorkspaceAccessResponse:
        self._require_admin()
        current = self._repository.get(workspace_id)
        if current is None:
            raise ValueError("Workspace does not exist")
        if request.expected_revision != current.revision:
            from ava.repositories.workspace_access_repository import WorkspaceAccessConflictError

            raise WorkspaceAccessConflictError(workspace_id)
        updated = current.model_copy(
            update={
                "name": request.name,
                "kind": request.kind,
                "root_path": self._root(request.root_path),
                "allowed_capabilities": request.allowed_capabilities,
                "status": request.status,
                "revision": current.revision + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        # Revalidate after model_copy: it intentionally skips Pydantic validation.
        updated = WorkspaceAccessConfiguration.model_validate(updated.model_dump())
        self._repository.compare_and_set(current.revision, updated)
        if self._on_workspace_changed is not None:
            self._on_workspace_changed(workspace_id)
        return self.state()

    def _require_admin(self) -> None:
        if not self._can_manage():
            raise WorkspaceAdministrationRequiredError("Trusted Workspace administration is unavailable")
