"""Platform-neutral security port for local Workspace file reads."""

from typing import Protocol

from ava.contracts.tools import ToolResult
from ava.services.tool_execution_service import AuthorizedToolInvocation


class WorkspaceFilesystemSecurityPort(Protocol):
    """Perform one Workspace read with a trusted service-created invocation."""

    async def execute(self, invocation: AuthorizedToolInvocation) -> ToolResult: ...
