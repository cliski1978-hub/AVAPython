"""Fail-closed adapter for execution hosts without a certified implementation."""

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.tools import ToolResult, ToolStatus
from ava.services.tool_execution_service import AuthorizedToolInvocation


class UnavailableWorkspaceFilesystemAdapter:
    async def execute(self, invocation: AuthorizedToolInvocation) -> ToolResult:
        if not isinstance(invocation, AuthorizedToolInvocation):
            raise TypeError("service authorization required")
        return ToolResult(
            invocation_id=invocation.request.invocation_id,
            tool_id=invocation.request.tool_id,
            tool_version=invocation.request.tool_version,
            status=ToolStatus.FAILED,
            error=ErrorResponse(
                error_code="secure_filesystem_unavailable",
                category=ErrorCategory.UNAVAILABLE,
                message="Secure Workspace access is not available on this execution host.",
            ),
        )
