from ava.workspaces.contracts import ResolvedWorkspace, WorkspaceAccessLookupPort
from ava.workspaces.registry import WorkspaceRegistry


class UnknownWorkspaceError(ValueError):
    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        super().__init__(f"Unknown workspace: {workspace_id!r}")


class WorkspaceResolver:
    def __init__(self, registry: WorkspaceRegistry, access_lookup: WorkspaceAccessLookupPort | None = None) -> None:
        self._registry = registry
        self._access_lookup = access_lookup

    def resolve(self, workspace_id: str) -> ResolvedWorkspace:
        if not workspace_id or not workspace_id.strip():
            raise UnknownWorkspaceError(workspace_id)
        workspace = self._registry.get(workspace_id)
        if workspace is None:
            raise UnknownWorkspaceError(workspace_id)
        return workspace

    def resolve_tool_access(self, workspace_id: str) -> ResolvedWorkspace:
        """Resolve current Workspace configuration for normalized-tool policy.

        Caller, run, and tool grants remain the responsibility of the trusted
        ``ToolExecutionAuthorityPort`` consumed by that policy.
        """
        if not workspace_id or not workspace_id.strip():
            raise UnknownWorkspaceError(workspace_id)
        configured = False
        workspace = None
        if self._access_lookup is not None:
            configured, workspace = self._access_lookup.resolve(workspace_id)
        if not configured:
            workspace = self._registry.get(workspace_id)
        if workspace is None:
            raise UnknownWorkspaceError(workspace_id)
        return workspace
