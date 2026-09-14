"""Agent adapter contracts (Ports).

AVA-owned, framework-neutral interfaces that future agent frameworks
(AWS, Databricks, LangGraph, mock, etc.) must implement.

AVA Core depends on this abstraction. Framework types must never escape
adapters; inputs and outputs use AVA contracts.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel

from ava.contracts.capabilities import CapabilityName
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
    async def start_run(self, run_id: str, request: RunRequest) -> AgentRunResult:
        """Start an agent run under an AVA-generated run identifier.

        Args:
            run_id: The AVA-owned run identifier assigned by the run service.
            request: An AVA-owned RunRequest contract.

        Returns:
            An AVA-owned AgentRunResult describing the run outcome and any
            generic assistant content produced for the lifecycle.
        """
        raise NotImplementedError

    @abstractmethod
    async def cancel_run(self, run_id: str) -> RunResponse:
        """Cancel an in-progress run.

        Args:
            run_id: The run identifier to cancel.

        Returns:
            An AVA-owned RunResponse with the updated run state.
        """
        raise NotImplementedError

    @abstractmethod
    def get_capabilities(self) -> set[CapabilityName]:
        """Return the capabilities the adapter actually supports."""
        raise NotImplementedError


# ============================================================
# END: Agent Port
# ============================================================