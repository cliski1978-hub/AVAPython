"""Runtime-neutral executor for the initial Workspace read tools."""

import asyncio

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.execution import ExecutionMode
from ava.contracts.tools import ToolResult, ToolStatus
from ava.services.tool_execution_service import AuthorizedToolInvocation
from ava.tools.workspace_filesystem import WorkspaceFilesystemSecurityPort


class WorkspaceReadExecutor:
    """Enforce the public tool/mode contract, then delegate to a trusted port."""

    def __init__(self, filesystem: WorkspaceFilesystemSecurityPort) -> None:
        self._filesystem = filesystem

    async def execute(self, invocation: AuthorizedToolInvocation) -> ToolResult:
        if not isinstance(invocation, AuthorizedToolInvocation):
            raise TypeError("service authorization required")
        if invocation.execution_mode == ExecutionMode.CHAT:
            return ToolResult(
                invocation_id=invocation.request.invocation_id,
                tool_id=invocation.request.tool_id,
                tool_version=invocation.request.tool_version,
                status=ToolStatus.FAILED,
                error=ErrorResponse(
                    error_code="execution_mode_denied",
                    category=ErrorCategory.UNAVAILABLE,
                    message="Chat mode cannot access Workspace tools.",
                ),
            )
        await asyncio.sleep(0)
        return await self._filesystem.execute(invocation)
