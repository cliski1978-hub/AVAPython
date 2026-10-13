"""Mock agent adapter.

The first concrete implementation of the AVA ``AgentPort``. It exists only to
validate AVA's execution flow without binding AVA to an AI framework or
provider, and performs no real inference.

Design rules followed here:

* AVA owns run identity. The adapter receives the AVA-generated ``run_id``
  from ``RunService`` and never generates one itself; callers must not supply
  one.
* Everything is deterministic. Responses and failure messages derive only
  from the request prompt, so automated tests rely on exact matches.
* No external AI/provider SDK is used and none may be added. The adapter
  depends inward on AVA-owned ports and contracts only.
"""

import asyncio
import logging
from collections.abc import Callable

from ava.agents.contracts import AgentPort, AgentRunResult
from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import RunContext
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.contracts.run_inspection import RunInspectionSnapshot

logger = logging.getLogger(__name__)

#: Stable identifier returned by :meth:`MockAgentAdapter.name`. Aligned with
#: the Sprint 1 configuration default ``agent_provider = mock``.
MOCK_AGENT_NAME = "mock"

#: Deterministic execution window that makes cancellation testable without
#: adding wall-clock-dependent behavior.
DEFAULT_RUN_DELAY_SECONDS = 0.001


class MockAgentAdapter(AgentPort):
    """Deterministic, provider-neutral mock implementation of ``AgentPort``.

    Each ``start_run`` simulates a short in-progress window during which
    ``cancel_run`` can take effect, then records a deterministic outcome for
    that run. Run state lives only in memory on this instance; no persistence
    is introduced.
    """

    def __init__(
        self,
        *,
        run_delay: float = DEFAULT_RUN_DELAY_SECONDS,
        fail_on_prompt: str | None = None,
        content_snapshots: tuple[str, ...] = (),
    ) -> None:
        """Construct a mock agent adapter.

        Args:
            run_delay: Seconds to keep a run "in progress" so cancellation
                has a deterministic window to target. Kept small and constant
                so tests stay fast and dependable.
            fail_on_prompt: Optional exact prompt that triggers a predictable
                failure instead of completion. Test-only and explicit; normal
                prompts are never affected when left unset.
        """
        self._run_delay: float = run_delay
        self._fail_on_prompt: str | None = fail_on_prompt
        self._content_snapshots = content_snapshots
        self._active_runs: set[str] = set()
        self._final_status: dict[str, RunStatus] = {}
        self._responses: dict[str, str] = {}

    def name(self) -> str:
        """Return the stable adapter name (``mock``)."""
        return MOCK_AGENT_NAME

    def get_capabilities(self) -> set[CapabilityName]:
        """Return only the capabilities this adapter genuinely supports.

        The mock can start runs and cancel them while in progress. Tests may
        configure normalized content snapshots, but this does not claim a
        provider streaming capability. It does not call tools, produce
        structured output, require approval, touch documents, or use a model.
        """
        return {CapabilityName.RUNS, CapabilityName.CANCELLATION}

    async def start_run(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None = None,
        resolved_execution: object | None = None,
    ) -> AgentRunResult:
        """Run a deterministic mock "agent" pass for ``request``.

        AVA owns the run identifier: ``run_id`` is supplied by the run
        service. The adapter never invents one, and the returned
        ``AgentRunResult`` carries status and generic assistant content only.

        The mock performs no inference, so it accepts the AVA-constructed
        ``context`` without reading it. Its deterministic output stays derived
        from ``request.prompt``, which keeps mock-based tests stable and makes
        the real Native/OpenHands context paths the only ones that translate
        history.
        """
        del context, resolved_execution
        self._active_runs.add(run_id)
        logger.debug("Mock agent starting run %s", run_id)
        await asyncio.sleep(self._run_delay)
        if run_id not in self._active_runs:
            # Removed by cancel_run while the mock was "in progress".
            logger.debug("Mock agent run %s was cancelled during the run", run_id)
            return AgentRunResult(status=RunStatus.CANCELLED)
        self._active_runs.discard(run_id)

        if self._fail_on_prompt is not None and request.prompt == self._fail_on_prompt:
            self._final_status[run_id] = RunStatus.FAILED
            self._responses[run_id] = self.failure_text(request.prompt)
            return AgentRunResult(status=RunStatus.FAILED)

        self._final_status[run_id] = RunStatus.COMPLETED
        self._responses[run_id] = self.success_text(request.prompt)
        return AgentRunResult(
            status=RunStatus.COMPLETED,
            content=self.success_text(request.prompt),
        )

    async def start_run_streaming(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None = None,
        on_content: Callable[[str], None],
        on_inspection: Callable[[RunInspectionSnapshot], None] | None = None,
        resolved_execution: object | None = None,
    ) -> AgentRunResult:
        """Emit configured full-content snapshots, then return the normal result."""
        del on_inspection, resolved_execution
        if not self._content_snapshots:
            return await self.start_run(run_id, request, context=context)
        self._active_runs.add(run_id)
        for snapshot in self._content_snapshots:
            await asyncio.sleep(self._run_delay / max(len(self._content_snapshots), 1))
            if run_id not in self._active_runs:
                return AgentRunResult(status=RunStatus.CANCELLED)
            on_content(snapshot)
        if self._fail_on_prompt is not None and request.prompt == self._fail_on_prompt:
            self._active_runs.discard(run_id)
            self._final_status[run_id] = RunStatus.FAILED
            return AgentRunResult(status=RunStatus.FAILED)
        self._active_runs.discard(run_id)
        self._final_status[run_id] = RunStatus.COMPLETED
        final = self._content_snapshots[-1]
        self._responses[run_id] = final
        return AgentRunResult(status=RunStatus.COMPLETED, content=final)

    async def cancel_run(self, run_id: str) -> RunResponse:
        """Cancel an in-progress run, or report why cancellation is a no-op.

        Behavior:
        * An active run is cancelled and recorded as cancelled.
        * A run that already finished reports its recorded outcome.
        * A missing handle reports running: no terminal outcome is known.
        """
        if run_id in self._active_runs:
            self._active_runs.discard(run_id)
            self._final_status[run_id] = RunStatus.CANCELLED
            self._responses[run_id] = self.cancelled_text(run_id)
            logger.debug("Mock agent cancelled run %s", run_id)
            return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)

        previous = self._final_status.get(run_id)
        if previous is not None:
            # Idempotent redundant cancellation: report the recorded outcome.
            return RunResponse(run_id=run_id, status=previous)

        # Missing handles do not prove execution stopped.
        logger.debug("Mock agent cancel no-op for unknown run %s", run_id)
        return RunResponse(run_id=run_id, status=RunStatus.RUNNING)

    @classmethod
    def success_text(cls, prompt: str) -> str:
        """Return the deterministic completion message for a prompt."""
        return f"AVA mock agent received: {prompt}"

    @classmethod
    def cancelled_text(cls, run_id: str) -> str:
        """Return the deterministic cancellation message for a run."""
        return f"AVA mock agent run cancelled: {run_id}"

    @classmethod
    def failure_text(cls, prompt: str) -> str:
        """Return the deterministic failure message for a prompt."""
        return f"AVA mock agent failed: {prompt}"

    def response_for(self, run_id: str) -> str | None:
        """Return the recorded deterministic output for ``run_id``.

        Mock-specific accessor used by tests to inspect produced output; it
        is not part of the ``AgentPort`` contract.
        """
        return self._responses.get(run_id)

    def active_run_ids(self) -> frozenset[str]:
        """Return the run identifiers currently in their in-progress window.

        Mock-specific accessor used by tests to observe the deterministic
        cancellation window; it is not part of the ``AgentPort`` contract.
        """
        return frozenset(self._active_runs)

    def final_status_for(self, run_id: str) -> RunStatus | None:
        """Return the recorded final status for ``run_id``.

        Mock-specific accessor used by tests to inspect run outcomes; it is
        not part of the ``AgentPort`` contract.
        """
        return self._final_status.get(run_id)
