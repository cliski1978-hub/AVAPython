"""Agent adapter contracts (Ports).

AVA-owned, framework-neutral interfaces that future agent frameworks
(AWS, Databricks, LangGraph, mock, etc.) must implement.

AVA Core depends on this abstraction. Framework types must never escape
adapters; inputs and outputs use AVA contracts.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable

from pydantic import BaseModel

from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import RunContext
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus

# ============================================================
# BEGIN: Agent Port
# ============================================================


class AgentRunResult(BaseModel):
    """AVA-owned result of an agent execution.

    This is an internal port-boundary DTO, not a wire contract: the public
    HTTP API continues to use ``RunResponse``. ``content`` carries generic
    assistant text that the run service normalizes into AVA
    ``message_content`` events. Future real providers may expose many content
    events; this minimal shape keeps Step 8 provider-neutral.
    """

    status: RunStatus
    content: str | None = None
    execution_selection: RunExecutionSelection | None = None


class AgentPort(ABC):
    """Port that all AVA agent adapters must implement.

    Frameworks integrate through adapters that implement this interface; the
    core never depends on vendor SDKs.
    """

    @abstractmethod
    def name(self) -> str:
        """Return the adapter name."""
        raise NotImplementedError

    @abstractmethod
    async def start_run(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None = None,
    ) -> AgentRunResult:
        """Start an agent run under an AVA-generated run identifier.

        Args:
            run_id: The AVA-owned run identifier assigned by the run service.
            request: An AVA-owned RunRequest contract.
            context: The AVA-constructed durable context for this run. When
                present its messages are the only conversational history the
                adapter may forward, and ``request.prompt`` must not be added
                to them. ``None`` means the run has no durable context.

        Returns:
            An AVA-owned AgentRunResult describing the run outcome and any
            generic assistant content produced for the lifecycle.
        """
        raise NotImplementedError

    async def start_run_streaming(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None = None,
        on_content: Callable[[str], None],
    ) -> AgentRunResult:
        """Execute with optional AVA snapshot notifications.

        Adapters without genuine incremental output remain valid: the default
        implementation returns the ordinary final result and emits no callback.
        The run service reconciles that final result through the same durable
        content path.
        """
        return await self.start_run(run_id, request, context=context)

    @abstractmethod
    async def cancel_run(self, run_id: str) -> RunResponse:
        """Cancel an in-progress run.

        Args:
            run_id: The run identifier to cancel.

        Returns:
            An AVA-owned RunResponse with the observed execution outcome.
            Report running when cancellation is in flight or a handle is
            absent with no known terminal outcome.
        """
        raise NotImplementedError

    @abstractmethod
    def get_capabilities(self) -> set[CapabilityName]:
        """Return the capabilities the adapter actually supports."""
        raise NotImplementedError


# ============================================================
# END: Agent Port
# ============================================================
