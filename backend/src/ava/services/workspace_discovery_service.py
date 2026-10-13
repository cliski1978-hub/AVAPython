"""Workspace discovery service.

Answers "what AVA-approved workspaces exist?" over the same ``WorkspaceRegistry``
used by the ``WorkspaceResolver``. Discovery is metadata-only: it reads
registered ``ResolvedWorkspace`` entries, exposes only the public-safe
``WorkspaceInfo`` (id, display name, kind), and never constructs a
``RuntimeWorkspaceBinding``, never resolves a runtime, never performs
filesystem/shell/network activity, and preserves deterministic registry
ordering.
"""

from ava.contracts.responses import WorkspaceDiscoveryResponse
from ava.workspaces.registry import WorkspaceRegistry


class WorkspaceDiscoveryService:
    """Enumerate registered AVA workspaces as safe public metadata."""

    def __init__(self, *, registry: WorkspaceRegistry) -> None:
        """Construct discovery over the registry it and resolution share.

        Args:
            registry: The application's ``WorkspaceRegistry``. The service
                reads it only through its public ``list()``/``get()`` surface
                and never registers or mutates entries.
        """
        self._registry = registry

    def discover(self) -> WorkspaceDiscoveryResponse:
        """Build a discovery snapshot over the registered workspaces.

        Workspaces are enumerated in registry insertion order. Only the
        public-safe ``WorkspaceInfo`` leaves this service; paths, permissions,
        and execution bindings stay internal.
        """
        workspaces = []
        for workspace_id in self._registry.list():
            workspace = self._registry.get(workspace_id)
            if workspace is None:
                continue
            workspaces.append(workspace.info)
        return WorkspaceDiscoveryResponse(workspaces=workspaces)
