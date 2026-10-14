"""Run service tests.

Verify that the run service owns run identifier generation and delegates
execution through the AgentPort rather than a concrete agent implementation.
"""

import asyncio
from uuid import UUID

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.agents.contracts import AgentPort, AgentRunResult
from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import RunContext
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.execution.selector import ResolvedExecution
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore

# ============================================================
# BEGIN: Stub Agent
# ============================================================


class StubAgent(AgentPort):
    """An in-memory AgentPort stub that records what it receives.

    ``block_start`` optionally holds ``start_run`` on an event so tests can
    exercise cancellation of an in-progress, AVA-tracked run.
    """

    def __init__(self, *, block_start: bool = False) -> None:
        self.captured_run_id: str | None = None
        self.captured_request: RunRequest | None = None
        self.captured_context: RunContext | None = None
        self.cancelled_run_id: str | None = None
        self._block_start = block_start
        self._start_released = asyncio.Event()

    def name(self) -> str:
        return "stub"

    async def start_run(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None = None,
        resolved_execution: ResolvedExecution | None = None,
    ) -> AgentRunResult:
        del resolved_execution
        self.captured_run_id = run_id
        self.captured_request = request
        self.captured_context = context
        if self._block_start:
            await self._start_released.wait()
        return AgentRunResult(status=RunStatus.COMPLETED, content="stub replied")

    def release_start(self) -> None:
        """Unblock a ``start_run`` held by ``block_start``."""
        self._start_released.set()

    async def cancel_run(self, run_id: str) -> RunResponse:
        self.cancelled_run_id = run_id
        return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)

    def get_capabilities(self) -> set[CapabilityName]:
        return set()


# ============================================================
# END: Stub Agent
# ============================================================


# ============================================================
# BEGIN: Run Service Tests
# ============================================================


def test_start_run_generates_ava_owned_run_id() -> None:
    """RunService should generate the run identifier, not the caller."""

    async def scenario() -> None:
        agent = StubAgent()
        service = RunService(agent, run_repository=RunStore(), run_event_repository=RunEventStore())
        request = RunRequest(prompt="Summarize the document")

        response = await service.start_run(request)

        assert agent.captured_run_id is not None
        assert response.run_id == agent.captured_run_id
        UUID(agent.captured_run_id)  # must be a valid UUID string
        assert agent.captured_request is request

    asyncio.run(scenario())


def test_cancel_run_delegates_to_agent() -> None:
    """RunService should delegate cancellation for an active run.

    Cancellation of an active run must reach the agent adapter. An unknown
    run is a service-level no-op and never reaches the adapter.
    """

    async def scenario() -> None:
        agent = StubAgent(block_start=True)
        service = RunService(agent, run_repository=RunStore(), run_event_repository=RunEventStore())
        task = asyncio.create_task(service.start_run(RunRequest(prompt="Something")))
        await asyncio.sleep(0.01)
        assert agent.captured_run_id is not None

        response = await service.cancel_run(agent.captured_run_id)
        agent.release_start()
        start_response = await task

        assert response.run_id == agent.captured_run_id
        assert agent.cancelled_run_id == agent.captured_run_id
        assert response.status == RunStatus.CANCELLED
        assert start_response.status == RunStatus.CANCELLED

    asyncio.run(scenario())


def test_cancel_unknown_run_is_service_level_noop() -> None:
    """RunService should not delegate cancellation for an unknown run.

    An idempotent ``RunResponse(cancelled)`` is returned without ever
    reaching the agent adapter.
    """

    async def scenario() -> None:
        agent = StubAgent()
        service = RunService(agent, run_repository=RunStore(), run_event_repository=RunEventStore())

        response = await service.cancel_run("never-created")

        assert response.status == RunStatus.CANCELLED
        assert agent.cancelled_run_id is None

    asyncio.run(scenario())


# ============================================================
# END: Run Service Tests
# ============================================================


# ============================================================
# BEGIN: Run Service — Mock Adapter Integration
# ============================================================


def test_run_service_generates_uuid_and_delivers_to_mock_agent() -> None:
    """RunService should generate the AVA-owned UUID and hand it to the mock.

    This proves the full production path without an API layer:

        RunRequest → RunService → AVA-generated UUID → MockAgentAdapter
    """

    async def scenario() -> None:
        agent = MockAgentAdapter()
        service = RunService(agent, run_repository=RunStore(), run_event_repository=RunEventStore())
        request = RunRequest(prompt="Hello AVA")

        response = await service.start_run(request)

        assert response.status == RunStatus.COMPLETED
        UUID(response.run_id)  # AVA generated the identifier, not the adapter
        assert agent.final_status_for(response.run_id) == RunStatus.COMPLETED
        assert agent.response_for(response.run_id) == "AVA mock agent received: Hello AVA"

    asyncio.run(scenario())


def test_run_service_mock_cancellation_path() -> None:
    """RunService cancellation should reach the mock adapter's cancel logic."""

    async def scenario() -> None:
        adapter = MockAgentAdapter(run_delay=0.1)
        service = RunService(adapter, run_repository=RunStore(), run_event_repository=RunEventStore())

        task = asyncio.create_task(service.start_run(RunRequest(prompt="Cancel me")))
        await asyncio.sleep(0.01)  # let the run enter its in-progress window

        (run_id,) = adapter.active_run_ids()  # single AVA-generated run

        cancel_response = await service.cancel_run(run_id)
        start_response = await task

        assert cancel_response.status == RunStatus.CANCELLED
        assert start_response.status == RunStatus.CANCELLED
        assert adapter.final_status_for(run_id) == RunStatus.CANCELLED

    asyncio.run(scenario())


# ============================================================
# END: Run Service — Mock Adapter Integration
# ============================================================
