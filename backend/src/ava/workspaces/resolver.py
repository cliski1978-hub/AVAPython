from ava.workspaces.contracts import ResolvedWorkspace
from ava.workspaces.registry import WorkspaceRegistry


class UnknownWorkspaceError(ValueError):
    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        super().__init__(f"Unknown workspace: {workspace_id!r}")


class WorkspaceResolver:
    def __init__(self, registry: WorkspaceRegistry) -> None:
        self._registry = registry

    def resolve(self, workspace_id: str) -> ResolvedWorkspace:
        if not workspace_id or not workspace_id.strip():
            raise UnknownWorkspaceError(workspace_id)
        workspace = self._registry.get(workspace_id)
        if workspace is None:
            raise UnknownWorkspaceError(workspace_id)
        return workspace
