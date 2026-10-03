"""Agent adapter contracts (Ports).

AVA-owned, framework-neutral interfaces that future agent frameworks
(AWS, Databricks, LangGraph, mock, etc.) must implement.

AVA Core depends on this abstraction. Framework types must never escape
adapters; inputs and outputs use AVA contracts.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Collection
from typing import Protocol

from pydantic import BaseModel

from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import RunContext
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus

# ============================================================
# BEGIN: Agent Port
# ============================================================


class ExecutionConfigurationError(ValueError):
    """Base for every failure raised while resolving persisted execution.

    It lives here, on the port, rather than in ``ava.execution``, because of
    *who has to catch it*. The execution adapters raise it while resolving a
    run's configuration, and it escapes through :class:`AgentPort` to the run
    service, which turns it into a durable, user-facing failure. Both sides of
    that boundary must be able to name the type, so it belongs to the contract
    they share; leaving it in the execution layer would force the service to
    import a concrete execution module merely to classify an error, which the
    dependency-direction guards forbid.

    The concrete subclasses stay in ``ava.execution.persisted_execution`` and
    re-export this name, so execution code and existing importers are
    unaffected: this is the same class object, not a parallel hierarchy.

    A ``ValueError`` subclass, because the whole execution path already treats
    an unresolvable configuration as a value problem and turns it into a clean
    run failure; a new base exception would have escaped that handling and
    surfaced as an unhandled 500.

    Every message names configured identities and non-secret connection data
    only. No message, and no attribute, ever contains resolved secret material:
    the credential layer's own errors already name only a reference location,
    and the credential failure subclass adds the connection id rather than the
    underlying detail.
    """

    #: Stable, non-secret reason for logs and diagnostics.
    reason = "execution_configuration_invalid"


class ExecutionPromptContextBuilderPort(Protocol):
    """AVA-owned seam for resolving instructions after runtime selection."""

    def build(
        self,
        context: RunContext | None,
        *,
        runtime_key: str,
        capabilities: Collection[CapabilityName],
    ) -> RunContext: ...


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
    #: Public classification for a FAILED run, from the AVA failure taxonomy.
    #: The agent sets it for failures it can name itself (a context window that
    #: cannot fit, an incompatible combination) and preserves one handed up by
    #: the runtime, so a known provider failure is not widened into
    #: ``agent_failed`` on its way to the durable record.
    failure_code: str | None = None


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
