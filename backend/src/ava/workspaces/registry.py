from __future__ import annotations

from ava.workspaces.contracts import ResolvedWorkspace


class WorkspaceRegistry:
    """Explicitly provisioned in-process legacy runtime Workspaces."""

    def __init__(self) -> None:
        self._items: dict[str, ResolvedWorkspace] = {}

    def register(self, workspace: ResolvedWorkspace) -> None:
        key = workspace.info.workspace_id
        if not key or key in self._items:
            raise ValueError(f"Workspace already registered: {key}")
        self._items[key] = workspace

    def get(self, workspace_id: str) -> ResolvedWorkspace | None:
        """Return only server-provisioned legacy runtime entries."""
        return self._items.get(workspace_id)

    def list(self) -> list[str]:
        return list(self._items)
