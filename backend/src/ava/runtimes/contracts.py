"""Framework-neutral runtime boundary, independent of agent implementations.

Agent runtime selection and model-provider selection are independent axes.
The selected model provider is an execution input, never resolved or owned
by the runtime. No production execution uses this boundary yet.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from ava.contracts.conversations import RunContext
from ava.contracts.json_types import JsonValue
from ava.contracts.models import ModelCapabilities
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeInfo
from ava.contracts.tools import ToolDefinition, ToolResult
from ava.models.bindings import ConfiguredModelBinding
from ava.models.contracts import ModelProviderPort
from ava.workspaces.contracts import RuntimeWorkspaceBinding


class RuntimeRunResult(BaseModel):
    """Internal runtime result, not an API response or an agent-layer DTO.

    Implementations normalize execution into COMPLETED, FAILED, or CANCELLED
    using the existing RunStatus vocabulary. Content is optional assistant
    text or a sanitized failure message, never framework or transport data.

    ``failure`` carries a classification the runtime already knows, so a
    provider failure that the runtime can name is not widened into the generic
    code on the way up. It holds only a public
    :class:`~ava.contracts.failures.FailureCode`; provider wording, statuses, and
    payloads stay in the runtime's log.
    """

    status: RunStatus
    content: str | None = None
    failure_code: str | None = None
    runtime_request: JsonValue | None = None
    runtime_response: JsonValue | None = None


class RuntimeToolDisposition(StrEnum):
    """Safe normalized outcomes exposed to an agent runtime."""

    EXECUTED = "executed"
    AWAITING_APPROVAL = "awaiting_approval"
    DENIED = "denied"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INDETERMINATE = "indeterminate"


class RuntimeToolOutcome(BaseModel):
    """Runtime-facing projection of the central execution service outcome."""

    invocation_id: str
    tool_id: str
    tool_version: str
    disposition: RuntimeToolDisposition
    result: ToolResult | None = None
    reason_code: str | None = None


class RuntimeToolBridgePort(Protocol):
    """AVA-owned seam for runtime tool discovery and normalized invocation."""

    def discover_tools(
        self,
        *,
        run_id: str,
        request: RunRequest,
        context: RunContext | None,
        workspace: RuntimeWorkspaceBinding | None,
    ) -> list[ToolDefinition]: ...

    async def execute_tool(
        self,
        *,
        run_id: str,
        request: RunRequest,
        context: RunContext | None,
        workspace: RuntimeWorkspaceBinding | None,
        tool_id: str,
        tool_version: str,
        call_id: str,
        arguments_json: str,
    ) -> RuntimeToolOutcome: ...

    def reject_unadvertised_tool(
        self,
        *,
        run_id: str,
        tool_id: str,
        tool_version: str,
        call_id: str,
        reason_code: str,
    ) -> RuntimeToolOutcome: ...


class AgentRuntimePort(ABC):
    """Interchangeable execution framework using AVA contracts only.

    RuntimeInfo carries runtime identity and RuntimeCapabilities, separate
    from model capabilities and application capabilities. A runtime instance
    may execute with different model providers on different calls. Provider
    configuration, selection, and resource lifecycle remain caller-owned.
    """

    @abstractmethod
    def get_runtime_info(self) -> RuntimeInfo:
        """Return AVA-owned runtime identity and capability metadata."""
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
        model_capabilities: ModelCapabilities | None = None,
        context: RunContext | None = None,
    ) -> RuntimeRunResult:
        """Execute with the selected provider under an AVA-generated run id.

        The runtime neither selects a provider nor a model nor generates a
        replacement run id. ``model_binding`` carries the stable AVA ``model_id``
        and the provider-native ``provider_model_name`` the runtime must target;
        when omitted, a runtime falls back to the provider's bootstrap identity.
        ``context`` carries the AVA-constructed durable message sequence; a
        runtime translates it into its own request shape and never selects,
        re-orders, or drops messages itself. Normalize completion, failure, and
        cancellation into AVA results; framework-specific handles and raw errors
        must not cross the boundary.
        """
        raise NotImplementedError

    async def execute_streaming(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        on_content: Callable[[str], None],
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
        model_capabilities: ModelCapabilities | None = None,
        context: RunContext | None = None,
    ) -> RuntimeRunResult:
        """Execute with optional full-content snapshot notifications.

        Final-only runtimes inherit this implementation. A runtime that can
        surface genuine updates overrides it and reports normalized AVA text
        snapshots through ``on_content`` without leaking SDK objects.
        """
        del on_content
        return await self.execute(
            run_id=run_id,
            request=request,
            model_provider=model_provider,
            workspace=workspace,
            model_binding=model_binding,
            model_capabilities=model_capabilities,
            context=context,
        )

    @abstractmethod
    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        """Request cancellation using the same AVA run id passed to execute.

        Implementations keep task/session mappings internal. Cancellation is
        cooperative and should report CANCELLED when it takes effect, or the
        recorded terminal outcome when execution already finished. Repeated
        cancellation is idempotent. Report RUNNING while the outcome is
        unknown, including missing handles; absence is not proof of a stop.
        """
        raise NotImplementedError
