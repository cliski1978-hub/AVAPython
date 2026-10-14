"""AVA-owned persistence port for principal Workspace grants."""

from typing import Protocol

from ava.contracts.workspace_grants import WorkspaceGrant


class WorkspaceGrantConflictError(ValueError):
    """A grant identity or expected revision conflicted with current state."""


class WorkspaceGrantRepository(Protocol):
    def list_for_workspace(self, workspace_id: str) -> list[WorkspaceGrant]: ...

    def get(self, grant_id: str) -> WorkspaceGrant | None: ...

    def get_active_for_principal(
        self,
        workspace_id: str,
        principal_ref: str,
        tenant_ref: str | None,
    ) -> WorkspaceGrant | None: ...

    def create(self, grant: WorkspaceGrant) -> None: ...

    def compare_and_set(self, expected_revision: int, grant: WorkspaceGrant) -> None: ...
