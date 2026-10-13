"""Internal trusted authority inputs; no issuer, client DTO or granting registry."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ava.contracts.tools import ToolCapability, ToolExecutionContext
from ava.workspaces.contracts import RuntimeWorkspaceBinding


class ToolOperationType(StrEnum):
    READ = "read"
    WRITE = "write"
    EDIT = "edit"
    DELETE = "delete"
    COMMAND = "command"


@dataclass(frozen=True)
class ToolExecutionAuthority:
    """Server-issued immutable references and narrowing grants.

    The provider must authenticate/attribute the caller and bind current
    run/scope before returning this record. No production allowing provider
    exists yet. Technical support is distinct from allowed capabilities.
    """

    context: ToolExecutionContext
    workspace: RuntimeWorkspaceBinding
    revision_ref: str
    allowed_tool_ids: frozenset[str]
    allowed_capabilities: frozenset[ToolCapability]
    technical_capabilities: frozenset[ToolCapability]
    run_id: str | None = None
    narrowing_tool_ids: frozenset[str] | None = None
    revoked: bool = False


class ToolExecutionAuthorityPort(Protocol):
    def resolve(self, context_ref: str) -> ToolExecutionAuthority | None:
        """Resolve current trusted authority, including revocation, or return None."""
        ...
