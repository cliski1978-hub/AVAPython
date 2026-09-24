from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class WorkspaceKind(StrEnum):
    LOCAL = "local"
    EPHEMERAL = "ephemeral"


@dataclass(frozen=True)
class WorkspacePermissions:
    read: bool = False
    write: bool = False
    shell: bool = False
    network: bool = False


@dataclass(frozen=True)
class WorkspaceInfo:
    workspace_id: str
    display_name: str
    kind: WorkspaceKind


@dataclass(frozen=True)
class ResolvedWorkspace:
    info: WorkspaceInfo
    root_path: Path | None
    permissions: WorkspacePermissions

@dataclass(frozen=True)
class RuntimeWorkspaceBinding:
    workspace_id: str
    kind: WorkspaceKind
    local_path: Path | None
    permissions: WorkspacePermissions


def bind_workspace(resolved: ResolvedWorkspace) -> RuntimeWorkspaceBinding:
    """Convert a resolved AVA workspace into a runtime-approved binding.

    The conversion is a pure value mapping: the binding carries the same
    AVA-owned identity, kind, path reference, and permission policy as the
    resolved workspace. Runtimes and the agent adapter never re-derive
    permissions or paths from runtime type, prompt text, or client input.
    """
    return RuntimeWorkspaceBinding(
        workspace_id=resolved.info.workspace_id,
        kind=resolved.info.kind,
        local_path=resolved.root_path,
        permissions=resolved.permissions,
    )
