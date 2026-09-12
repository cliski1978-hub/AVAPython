"""Run service tests.

Verify that the run service owns run identifier generation and delegates
execution through the AgentPort rather than a concrete agent implementation.
"""

import asyncio
from uuid import UUID

from ava.agents.contracts import AgentPort
from ava.contracts.capabilities import CapabilityName
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.services.run_service import RunService

# ============================================================
# BEGIN: Stub Agent
# ============================================================


class StubAgent(AgentPort):
    """An in-memory AgentPort stub that records what it receives."""

    def __init__(self) -> None:
        self.captured_run_id: str | None = None
        self.captured_request: RunRequest | None = None
        self.cancelled_run_id: str | None = None

    def name(self) -> str:
        return "stub"

    async def start_run(self, run_id: str, request: RunRequest) -> RunResponse:
        self.captured_run_id = run_id
        self.captured_request = request
        return RunResponse(run_id=run_id, status=RunStatus.COMPLETED)

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
        service = RunService(agent)
        request = RunRequest(prompt="Summarize the document")

        response = await service.start_run(request)

        assert agent.captured_run_id is not None
        assert response.run_id == agent.captured_run_id
        UUID(agent.captured_run_id)  # must be a valid UUID string
        assert agent.captured_request is request

    asyncio.run(scenario())


def test_cancel_run_delegates_to_agent() -> None:
    """RunService should delegate cancellation to the agent adapter."""

    async def scenario() -> None:
        agent = StubAgent()
        service = RunService(agent)

        response = await service.cancel_run("run-1")

        assert agent.cancelled_run_id == "run-1"
        assert response.status == RunStatus.CANCELLED

    asyncio.run(scenario())


# ============================================================
# END: Run Service Tests
# ============================================================