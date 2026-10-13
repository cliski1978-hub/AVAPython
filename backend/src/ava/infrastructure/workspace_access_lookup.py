"""Persistence adapter that projects current Workspace configuration for policy."""

from pathlib import Path

from ava.contracts.tools import ToolCapability
from ava.contracts.workspace_access import WorkspaceAccessStatus
from ava.repositories.workspace_access_repository import WorkspaceAccessRepository
from ava.workspaces.contracts import ResolvedWorkspace, WorkspaceAccessLookupPort, WorkspaceInfo, WorkspacePermissions


class PersistentWorkspaceAccessLookup(WorkspaceAccessLookupPort):
    """Reads current revisions; it never authenticates callers or issues grants."""

    def __init__(self, repository: WorkspaceAccessRepository) -> None:
        self._repository = repository

    def resolve(self, workspace_id: str) -> tuple[bool, ResolvedWorkspace | None]:
        try:
            configuration = self._repository.get(workspace_id)
        except Exception:
            # A persistence or decode failure must not fall back to a legacy
            # in-memory registration that could hide a revoked durable identity.
            return True, None
        if configuration is None:
            return False, None
        if configuration.status is not WorkspaceAccessStatus.ACTIVE:
            return True, None
        try:
            configured_root = Path(configuration.root_path)
            root = configured_root.resolve(strict=True)
            if root != configured_root or not root.is_dir():
                return True, None
        except (OSError, RuntimeError, ValueError):
            return True, None
        capabilities = frozenset(configuration.allowed_capabilities)
        return True, ResolvedWorkspace(
            info=WorkspaceInfo(
                workspace_id=configuration.workspace_id,
                display_name=configuration.name or configuration.workspace_id,
                kind=configuration.kind,
            ),
            root_path=root,
            permissions=WorkspacePermissions(
                read=ToolCapability.FILE_READ in capabilities,
                write=ToolCapability.FILE_WRITE in capabilities,
                shell=ToolCapability.COMMAND_EXECUTION in capabilities,
                network=ToolCapability.NETWORK_ACCESS in capabilities,
            ),
            configuration_revision=configuration.revision,
            configured_capabilities=frozenset(capability.value for capability in capabilities),
        )
