"""Lock-protected Workspace grant adapter for isolated tests and memory mode."""

from threading import RLock

from ava.contracts.workspace_grants import WorkspaceGrant, WorkspaceGrantStatus
from ava.repositories.workspace_grant_repository import WorkspaceGrantConflictError, WorkspaceGrantRepository


class WorkspaceGrantStore(WorkspaceGrantRepository):
    def __init__(self) -> None:
        self._items: dict[str, WorkspaceGrant] = {}
        self._lock = RLock()

    def list_for_workspace(self, workspace_id: str) -> list[WorkspaceGrant]:
        with self._lock:
            return sorted(
                (item for item in self._items.values() if item.workspace_id == workspace_id),
                key=lambda item: (item.created_at, item.grant_id),
            )

    def get(self, grant_id: str) -> WorkspaceGrant | None:
        with self._lock:
            return self._items.get(grant_id)

    def get_active_for_principal(
        self, workspace_id: str, principal_ref: str, tenant_ref: str | None
    ) -> WorkspaceGrant | None:
        with self._lock:
            active = [
                item
                for item in self._items.values()
                if item.workspace_id == workspace_id
                and item.principal_ref == principal_ref
                and item.tenant_ref == tenant_ref
                and item.status == WorkspaceGrantStatus.ACTIVE
            ]
            if len(active) > 1:
                raise WorkspaceGrantConflictError("multiple active Workspace grants conflict")
            return active[0] if active else None

    def create(self, grant: WorkspaceGrant) -> None:
        with self._lock:
            if grant.grant_id in self._items:
                raise WorkspaceGrantConflictError("Workspace grant identity already exists")
            if grant.status != WorkspaceGrantStatus.ACTIVE:
                raise ValueError("new Workspace grants must be active")
            if self.get_active_for_principal(grant.workspace_id, grant.principal_ref, grant.tenant_ref):
                raise WorkspaceGrantConflictError("an active Workspace grant already exists")
            self._items[grant.grant_id] = grant

    def compare_and_set(self, expected_revision: int, grant: WorkspaceGrant) -> None:
        with self._lock:
            current = self._items.get(grant.grant_id)
            if current is None or current.revision != expected_revision or grant.revision != expected_revision + 1:
                raise WorkspaceGrantConflictError("Workspace grant revision conflict")
            if current.status == WorkspaceGrantStatus.REVOKED:
                raise WorkspaceGrantConflictError("revoked Workspace grants are terminal")
            if grant.status not in {WorkspaceGrantStatus.ACTIVE, WorkspaceGrantStatus.REVOKED}:
                raise ValueError("invalid Workspace grant status")
            self._items[grant.grant_id] = grant
