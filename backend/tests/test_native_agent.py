"""Offline native-agent contract and run lifecycle tests."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.api.app import create_app
from ava.contracts.capabilities import CapabilityName
from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelProviderHealth,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.models.contracts import ModelProviderPort
from ava.models.errors import ModelProviderError
from ava.models.registry import ModelProviderRegistry
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore


class TestProvider(ModelProviderPort):
    """Controllable port; metadata calls fail to detect agent introspection."""

    __test__ = False

    def __init__(self, error: Exception | None = None, *, block: bool = False) -> None:
        self.error = error
        self.block = block
        self.started = asyncio.Event()
        self.cancelled = False
        self.requests: list[ModelRequest] = []

    def name(self) -> str:
        return "test"

    async def health(self) -> ModelProviderHealth:
        raise AssertionError("Unexpected health call")

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id="test",
            provider_name="test",
            display_name="Test",
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        del model_name
        self.requests.append(request)
        self.started.set()
        if self.block:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.error is not None:
            raise self.error
        return ModelResponse(content="Native answer", model_id="provider-owned")


@pytest.mark.parametrize("error", [None, ModelProviderError("secret URL"), RuntimeError("secret key")])
def test_result_translation_cleanup_and_terminal_cancel(error: Exception | None) -> None:
    async def scenario() -> None:
        provider = TestProvider(error)
        agent = NativeAgentAdapter(NativeRuntime(), provider)
        _agent_runtime = agent._selector._runtime
        result = await agent.start_run("run", RunRequest(prompt="  Hello\nAVA  "))
        request = provider.requests[0]
        assert [(m.role, m.content) for m in request.messages] == [("user", "  Hello\nAVA  ")]
        assert request.temperature is None
        assert request.max_output_tokens is None
        expected = RunStatus.FAILED if error else RunStatus.COMPLETED
        assert result.status == expected
        assert result.content == ("Model provider request failed" if error else "Native answer")
        assert _agent_runtime._run_tasks == {}
        assert (await agent.cancel_run("run")).status == expected
        assert (await agent.cancel_run("unknown")).status == RunStatus.CANCELLED
        assert (await agent.cancel_run("unknown")).status == RunStatus.CANCELLED
        assert agent.name() == "native"
        assert agent.get_capabilities() == {CapabilityName.RUNS, CapabilityName.CANCELLATION}

    asyncio.run(scenario())


@pytest.mark.parametrize("external_cancel", [False, True])
def test_cancellation_and_single_terminal_lifecycle(external_cancel: bool) -> None:
    async def scenario() -> None:
        provider = TestProvider(block=True)
        agent = NativeAgentAdapter(NativeRuntime(), provider)
        _agent_runtime = agent._selector._runtime
        service = RunService(
            agent, run_repository=RunStore(), run_event_repository=RunEventStore()
        )
        start = asyncio.create_task(service.start_run(RunRequest(prompt="Cancel")))
        await asyncio.wait_for(provider.started.wait(), 1)
        (run_id,) = _agent_runtime._run_tasks
        if external_cancel:
            start.cancel()
        else:
            assert (await service.cancel_run(run_id)).status == RunStatus.CANCELLED
            assert (await service.cancel_run(run_id)).status == RunStatus.CANCELLED
        assert (await asyncio.wait_for(start, 1)).status == RunStatus.CANCELLED
        assert provider.cancelled
        assert _agent_runtime._run_tasks == {}
        assert (await agent.cancel_run(run_id)).status == RunStatus.CANCELLED
        events = service.get_run_events(run_id)
        assert events is not None
        assert [e.event_type for e in events] == ["run_started", "run_cancelled"]
        assert service.get_run(run_id).status == RunStatus.CANCELLED

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [None, ModelProviderError("secret URL"), RuntimeError("secret key")])
def test_http_native_lifecycle(monkeypatch: pytest.MonkeyPatch, error: Exception | None) -> None:
    provider = TestProvider(error)
    registry = ModelProviderRegistry()
    registry.register("local", provider)
    monkeypatch.setenv("AVA_AGENT_PROVIDER", "native")
    monkeypatch.setenv("AVA_MODEL_PROVIDER", "local")
    monkeypatch.setattr("ava.configuration.settings._settings", None)
    monkeypatch.setattr("ava.api.app.create_model_provider_registry", lambda settings: registry)
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/runs", json={"prompt": "Hello"})
        assert response.status_code == 200
        run = response.json()
        assert run["status"] == ("failed" if error else "completed")
        assert client.get(f"/runs/{run['run_id']}").json() == run
        events_response = client.get(f"/runs/{run['run_id']}/events")
        events = events_response.json()
        assert "secret" not in events_response.text
        if error:
            assert [e["event_type"] for e in events] == ["run_started", "run_failed"]
            assert events[-1]["payload"]["error_code"] == "agent_failed"
        else:
            assert [e["event_type"] for e in events] == [
                "run_started", "message_started", "message_content", "run_completed",
            ]
            assert events[1]["payload"]["role"] == "assistant"
            assert events[2]["payload"]["content"] == "Native answer"
        assert app.state.runtime_resolver.resolve("native")._run_tasks == {}


def test_concurrent_runs_cancel_only_target_and_keep_instances_isolated() -> None:
    async def scenario() -> None:
        provider = TestProvider(block=True)
        agent = NativeAgentAdapter(NativeRuntime(), provider)
        _agent_runtime = agent._selector._runtime
        other = NativeAgentAdapter(NativeRuntime(), TestProvider())
        _other_runtime = other._selector._runtime
        first = asyncio.create_task(agent.start_run("first", RunRequest(prompt="one")))
        second = asyncio.create_task(agent.start_run("second", RunRequest(prompt="two")))
        await asyncio.wait_for(provider.started.wait(), 1)
        assert set(_agent_runtime._run_tasks) == {"first", "second"}
        assert _other_runtime._run_tasks == {}
        await agent.cancel_run("first")
        assert (await asyncio.wait_for(first, 1)).status == RunStatus.CANCELLED
        assert not second.done()
        assert set(_agent_runtime._run_tasks) == {"second"}
        await agent.cancel_run("second")
        assert (await asyncio.wait_for(second, 1)).status == RunStatus.CANCELLED
        assert _agent_runtime._run_tasks == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("fail_after_cancel", [False, True])
def test_cancel_wins_when_provider_suppresses_cancellation(fail_after_cancel: bool) -> None:
    class SuppressingProvider(TestProvider):
        async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
            try:
                return await super().generate(request, model_name=model_name)
            except asyncio.CancelledError:
                if fail_after_cancel:
                    raise ModelProviderError("cleanup failure") from None
                return ModelResponse(content="Too late", model_id="test")

    async def scenario() -> None:
        provider = SuppressingProvider(block=True)
        agent = NativeAgentAdapter(NativeRuntime(), provider)
        _agent_runtime = agent._selector._runtime
        task = asyncio.create_task(agent.start_run("run", RunRequest(prompt="Cancel")))
        await asyncio.wait_for(provider.started.wait(), 1)
        await agent.cancel_run("run")
        await agent.cancel_run("run")
        result = await asyncio.wait_for(task, 1)
        assert result.status == RunStatus.CANCELLED
        assert result.content is None
        assert _agent_runtime._run_tasks == {}

    asyncio.run(scenario())
