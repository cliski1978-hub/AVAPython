"""Mock agent adapter tests.

Verify the deterministic, provider-neutral mock implementation of
``AgentPort``: identity, truthful capabilities, deterministic output,
AVA-owned run identity, request handling, independent runs, cancellation,
unknown-run behavior, and the explicit test-only failure trigger.
"""

import asyncio

import pytest

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.agents.contracts import AgentRunResult
from ava.api.app import create_app
from ava.contracts.capabilities import CapabilityName
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.infrastructure.composition import create_agent_adapter

# ============================================================
# BEGIN: Identity
# ============================================================


def test_mock_agent_name_matches_provider_configuration() -> None:
    """The adapter name should align with ``agent_provider = mock``."""
    assert MockAgentAdapter().name() == "mock"


# ============================================================
# END: Identity
# ============================================================


# ============================================================
# BEGIN: Capabilities
# ============================================================


def test_mock_agent_reports_only_supported_capabilities() -> None:
    """The mock should advertise runs and cancellation, nothing more."""
    capabilities = MockAgentAdapter().get_capabilities()
    assert CapabilityName.RUNS in capabilities
    assert CapabilityName.CANCELLATION in capabilities
    assert set(capabilities) == {CapabilityName.RUNS, CapabilityName.CANCELLATION}


def test_mock_agent_does_not_claim_unsupported_capabilities() -> None:
    """Capabilities that the mock cannot perform must stay unreported."""
    unsupported = {
        CapabilityName.STREAMING,
        CapabilityName.TOOL_CALLING,
        CapabilityName.STRUCTURED_OUTPUT,
        CapabilityName.APPROVALS,
        CapabilityName.DOCUMENT_OPERATIONS,
        CapabilityName.LOCAL_MODEL,
    }
    assert not (MockAgentAdapter().get_capabilities() & unsupported)


# ============================================================
# END: Capabilities
# ============================================================


# ============================================================
# BEGIN: Deterministic Response Behavior
# ============================================================


def test_mock_agent_produces_deterministic_completion() -> None:
    """A given prompt should always produce the exact same output."""

    async def scenario() -> None:
        agent = MockAgentAdapter()
        request = RunRequest(prompt="Hello AVA")

        first = await agent.start_run(run_id="run-1", request=request)
        second = await agent.start_run(run_id="run-2", request=request)

        assert first.status == RunStatus.COMPLETED
        assert second.status == RunStatus.COMPLETED
        assert agent.response_for("run-1") == "AVA mock agent received: Hello AVA"
        assert agent.response_for("run-2") == "AVA mock agent received: Hello AVA"

    asyncio.run(scenario())


# ============================================================
# END: Deterministic Response Behavior
# ============================================================


# ============================================================
# BEGIN: Run Identity
# ============================================================


def test_mock_agent_uses_ava_generated_run_id() -> None:
    """The adapter must accept the AVA-supplied run_id without inventing one.

    ``AgentRunResult`` is port-boundary internal: it carries status and
    generic content only — never a run identifier, which stays AVA-owned.
    """

    async def scenario() -> None:
        agent = MockAgentAdapter()
        supplied_id = "SDK-supplied-run-001"

        result = await agent.start_run(
            run_id=supplied_id, request=RunRequest(prompt="Run me")
        )

        assert result.status == RunStatus.COMPLETED
        assert agent.final_status_for(supplied_id) == RunStatus.COMPLETED

    asyncio.run(scenario())


# ============================================================
# END: Run Identity
# ============================================================


# ============================================================
# BEGIN: Request Handling
# ============================================================


def test_mock_agent_respects_run_request_content() -> None:
    """The deterministic output should reflect the request prompt verbatim."""

    async def scenario() -> None:
        agent = MockAgentAdapter()

        await agent.start_run(run_id="run-1", request=RunRequest(prompt="Alpha"))
        await agent.start_run(run_id="run-2", request=RunRequest(prompt="Beta"))

        assert agent.response_for("run-1") == "AVA mock agent received: Alpha"
        assert agent.response_for("run-2") == "AVA mock agent received: Beta"

    asyncio.run(scenario())


def test_mock_agent_result_is_port_boundary_internal() -> None:
    """start_run should produce an AgentRunResult carrying generic output.

    The mock's returned result carries status and content only; the public
    ``RunResponse`` wire contract is produced by the run service, never by
    the adapter.
    """

    async def scenario() -> None:
        agent = MockAgentAdapter()
        result = await agent.start_run(
            run_id="run-1", request=RunRequest(prompt="Echo")
        )
        assert isinstance(result, AgentRunResult)
        assert result.status == RunStatus.COMPLETED
        assert result.content == "AVA mock agent received: Echo"

    asyncio.run(scenario())


# ============================================================
# END: Request Handling
# ============================================================


# ============================================================
# BEGIN: Multiple Runs
# ============================================================


def test_mock_agent_runs_remain_independent() -> None:
    """Runs must not share state or cross-contaminate outputs."""

    async def scenario() -> None:
        agent = MockAgentAdapter()
        prompts = {"r1": "one", "r2": "two", "r3": "three"}

        for run_id, prompt in prompts.items():
            response = await agent.start_run(
                run_id=run_id, request=RunRequest(prompt=prompt)
            )
            assert response.status == RunStatus.COMPLETED

        for run_id, prompt in prompts.items():
            assert agent.response_for(run_id) == f"AVA mock agent received: {prompt}"
            assert agent.final_status_for(run_id) == RunStatus.COMPLETED

    asyncio.run(scenario())


# ============================================================
# END: Multiple Runs
# ============================================================


# ============================================================
# BEGIN: Cancellation
# ============================================================


def test_mock_agent_cancel_while_in_progress() -> None:
    """Cancelling during the deterministic run window should stop the run."""

    async def scenario() -> None:
        agent = MockAgentAdapter(run_delay=0.1)
        run_id = "cancel-1"
        task = asyncio.create_task(
            agent.start_run(run_id=run_id, request=RunRequest(prompt="Cancel me"))
        )
        # Give the coroutine a chance to register the run and enter its
        # in-progress window, then cancel before it completes.
        await asyncio.sleep(0.01)

        cancel_response = await agent.cancel_run(run_id)
        start_response = await task

        assert cancel_response.status == RunStatus.CANCELLED
        assert start_response.status == RunStatus.CANCELLED
        assert agent.final_status_for(run_id) == RunStatus.CANCELLED
        assert agent.response_for(run_id) == "AVA mock agent run cancelled: cancel-1"

    asyncio.run(scenario())


def test_mock_agent_cancel_after_completion_is_idempotent() -> None:
    """Cancelling a finished run should report its recorded outcome."""

    async def scenario() -> None:
        agent = MockAgentAdapter()
        run_id = "finished-1"
        await agent.start_run(run_id=run_id, request=RunRequest(prompt="Done"))

        response = await agent.cancel_run(run_id)

        assert response.status == RunStatus.COMPLETED
        assert agent.response_for(run_id) == "AVA mock agent received: Done"

    asyncio.run(scenario())


def test_mock_agent_cancel_unknown_run_is_a_no_op() -> None:
    """Cancelling an unknown run should behave predictably and without error."""

    async def scenario() -> None:
        agent = MockAgentAdapter()

        response = await agent.cancel_run("never-started")

        assert response.status == RunStatus.RUNNING
        assert response.run_id == "never-started"
        assert agent.final_status_for("never-started") is None
        assert agent.response_for("never-started") is None

    asyncio.run(scenario())


# ============================================================
# END: Cancellation
# ============================================================


# ============================================================
# BEGIN: Error Behavior
# ============================================================


def test_mock_agent_failure_trigger_is_config_driven() -> None:
    """The explicit test-only failure prompt must be exact and documented."""

    async def scenario() -> None:
        agent = MockAgentAdapter(fail_on_prompt="force failure")

        failed = await agent.start_run(
            run_id="fail-1", request=RunRequest(prompt="force failure")
        )
        normal = await agent.start_run(
            run_id="ok-1", request=RunRequest(prompt="normal request")
        )

        assert failed.status == RunStatus.FAILED
        assert agent.response_for("fail-1") == "AVA mock agent failed: force failure"
        assert agent.final_status_for("fail-1") == RunStatus.FAILED
        # Normal prompts are unaffected unless explicitly configured.
        assert normal.status == RunStatus.COMPLETED
        assert agent.response_for("ok-1") == "AVA mock agent received: normal request"

    asyncio.run(scenario())


def test_mock_agent_has_no_implicit_failure_trigger_by_default() -> None:
    """Without configuration, no prompt should ever trigger a failure."""

    async def scenario() -> None:
        agent = MockAgentAdapter()
        response = await agent.start_run(
            run_id="run-1", request=RunRequest(prompt="force failure")
        )
        assert response.status == RunStatus.COMPLETED

    asyncio.run(scenario())


# ============================================================
# END: Error Behavior
# ============================================================


# ============================================================
# BEGIN: Composition
# ============================================================


def test_create_agent_adapter_resolves_mock_provider() -> None:
    """Configuration value ``agent_provider = mock`` should yield the mock."""
    adapter = create_agent_adapter("mock")
    assert isinstance(adapter, MockAgentAdapter)
    assert adapter.name() == "mock"


def test_create_agent_adapter_rejects_unknown_provider() -> None:
    """Unrecognized provider names should fail loudly, not silently."""
    with pytest.raises(ValueError, match="Unknown agent provider"):
        create_agent_adapter("not-a-provider")


def test_create_app_composes_mock_agent_port() -> None:
    """The FastAPI composition root should expose the mock agent by default.

    Confirms ``agent_provider = mock`` resolves to a working adapter known
    to the application without exposing any run endpoint.
    """
    app = create_app()
    agent = app.state.agent_port
    assert agent.name() == "mock"
    assert isinstance(agent, MockAgentAdapter)


# ============================================================
# END: Composition
# ============================================================