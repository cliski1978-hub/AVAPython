"""Phase 5.22 context-window integration tests.

These tests drive the real execution path: a durable conversation/message/run
graph over relational persistence, the real ``ExecutionSelector`` and
``NativeAgentAdapter``, and fake model providers that report different context
windows. They prove the budget follows the *selected* model, that both runtimes
receive the same bounded context before their own translation, and that an
impossible request fails before any provider is invoked. No external network is
used.
"""

from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.conversations import ContextMessage, MessageRole, RunContext
from ava.contracts.models import (
    ModelCapabilities,
    ModelHostingMode,
    ModelInfo,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.execution.context_window import (
    DEFAULT_OUTPUT_RESERVE_TOKENS,
    ContextWindowManager,
    DeterministicTokenEstimator,
    input_budget_for,
)
from ava.execution.selector import ExecutionSelector
from ava.models.bindings import ModelBindingResolver
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.adapters.openhands.openhands_runtime import OpenHandsRuntime
from ava.runtimes.registry import RuntimeRegistry
from ava.runtimes.resolver import RuntimeResolver
from ava.services.run_service import RunService

_LARGE_LIMIT = 200_000
_SMALL_LIMIT = 4_000

# ============================================================
# BEGIN: Fakes
# ============================================================


@dataclass
class LimitedProvider(ModelProviderPort):
    """Fake provider that reports a context window and records every request."""

    __test__ = False
    provider_id: str
    context_limit: int | None = None
    requests: list[ModelRequest] = field(default_factory=list)

    def name(self) -> str:
        return self.provider_id

    async def health(self) -> ModelProviderHealth:
        return ModelProviderHealth(status=ModelProviderHealthStatus.HEALTHY, available=True)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self.provider_id,
            provider_name=self.provider_id,
            display_name=self.provider_id,
            context_limit=self.context_limit,
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        del model_name
        self.requests.append(request)
        return ModelResponse(content="answered", model_id=self.provider_id)


def _runtime_registry() -> RuntimeRegistry:
    registry = RuntimeRegistry()
    registry.register("native", NativeRuntime())
    registry.register("openhands", OpenHandsRuntime())
    return registry


def _agent(provider: ModelProviderPort) -> NativeAgentAdapter:
    """Compose the real agent over the real selector for one provider."""
    provider_registry = ModelProviderRegistry()
    provider_registry.register(provider.name(), provider)
    model_registry = ModelRegistry(
        [
            ModelProfile(
                model_id=provider.name(),
                display_name=provider.name(),
                provider_id=provider.name(),
                provider_model_name=provider.name(),
                hosting_mode=ModelHostingMode.LOCAL,
                capabilities=ModelCapabilities(chat=True),
            )
        ]
    )
    return NativeAgentAdapter(
        ExecutionSelector(
            runtime_resolver=RuntimeResolver(_runtime_registry()),
            model_provider_resolver=ModelProviderResolver(provider_registry),
            model_binding_resolver=ModelBindingResolver(
                model_registry, default_model_id=model_registry.list()[0].model_id
            ),
            default_runtime_id="native",
            default_model_provider_id=provider.name(),
        )
    )


def _two_model_agent(large: LimitedProvider, small: LimitedProvider) -> NativeAgentAdapter:
    """Compose one agent over two configured models with different windows."""
    provider_registry = ModelProviderRegistry()
    provider_registry.register(large.name(), large)
    provider_registry.register(small.name(), small)
    model_registry = ModelRegistry(
        [
            ModelProfile(
                model_id=large.name(),
                display_name=large.name(),
                provider_id=large.name(),
                provider_model_name=large.name(),
                hosting_mode=ModelHostingMode.LOCAL,
                capabilities=ModelCapabilities(chat=True),
            ),
            ModelProfile(
                model_id=small.name(),
                display_name=small.name(),
                provider_id=small.name(),
                provider_model_name=small.name(),
                hosting_mode=ModelHostingMode.LOCAL,
                capabilities=ModelCapabilities(chat=True),
            ),
        ]
    )
    return NativeAgentAdapter(
        ExecutionSelector(
            runtime_resolver=RuntimeResolver(_runtime_registry()),
            model_provider_resolver=ModelProviderResolver(provider_registry),
            model_binding_resolver=ModelBindingResolver(
                model_registry, default_model_id=large.name()
            ),
            default_runtime_id="native",
            default_model_provider_id=large.name(),
        )
    )


def _offline_binding(provider, binding) -> object:
    del provider
    from ava.models.bindings import RuntimeModelBinding

    return RuntimeModelBinding(
        model_id=binding.model_id,
        provider_id=binding.provider_id,
        provider_model_name=binding.provider_model_name,
        protocol="openai",
        endpoint="http://localhost/v1",
        api_key=None,
    )


def _settings(tmp_path) -> Settings:
    return Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "window.sqlite3"),
        attachment_storage="memory",
    )


def _run_service(app, agent) -> RunService:
    persistence = app.state.persistence
    return RunService(
        agent,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        context_service=app.state.context_construction_service,
    )


def _stub_openhands_sdk(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Controlled OpenHands SDK seam that records the single message it receives."""

    class _Part:
        def __init__(self, text: str) -> None:
            self.text = text

    class _LLMMessage:
        def __init__(self, text: str) -> None:
            self.content = [_Part(text)]

    class _Event:
        source = "agent"
        llm_message = _LLMMessage("OpenHands answer")

    class _State:
        events = [_Event()]

    class _Conversation:
        def __init__(self, agent: object, workspace: str) -> None:
            self.agent = agent
            self.workspace = workspace
            self.state = _State()

        def send_message(self, message: str) -> None:
            sent.append(message)

        def run(self) -> None:
            return None

    class _Agent:
        def __init__(self, llm: object, tools: list[object], include_default_tools: list[str]) -> None:
            self.llm = llm
            self.tools = tools

    class _LLM:
        def __init__(self, model: str, base_url: str, api_key: str) -> None:
            self.model = model
            self.base_url = base_url
            self.api_key = api_key

    sent: list[str] = []
    stub = types.ModuleType("openhands.sdk")
    stub.LLM = _LLM  # type: ignore[attr-defined]
    stub.Agent = _Agent  # type: ignore[attr-defined]
    stub.Conversation = _Conversation  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openhands.sdk", stub)
    controlled = types.ModuleType("ava.runtimes.adapters.openhands.conversation")
    controlled.ControlledAgent = _Agent  # type: ignore[attr-defined]
    controlled.ControlledConversation = lambda **kwargs: _Conversation(  # type: ignore[attr-defined]
        agent=kwargs["agent"], workspace=kwargs["workspace"]
    )
    monkeypatch.setitem(sys.modules, controlled.__name__, controlled)
    return {"sent": sent}


# ============================================================
# END: Fakes
# ============================================================
# ============================================================
# BEGIN: Selected Model Determines The Budget
# ============================================================


def _seed_turns(client, conversation_id: str, turns: int, *, size: int = 3_000) -> str:
    """Create answered turns, then return the id of a fresh current message."""
    for number in range(1, turns + 1):
        content = f"U{number} " + "x" * size
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": content, "role": "user"},
        ).json()
        client.post(
            "/runs",
            json={
                "prompt": content,
                "conversation_id": conversation_id,
                "source_user_message_id": message["message_id"],
            },
        )
    current = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "current question", "role": "user"},
    ).json()
    return current["message_id"]


def test_the_selected_model_decides_how_much_context_fits(tmp_path) -> None:
    """The same conversation is bounded differently by two configured models.

    This is the proof that the budget is not a global constant: both runs use one
    context, one window manager, and one estimator, and only the selected
    model's reported context window differs.
    """
    large = LimitedProvider("large-model", context_limit=_LARGE_LIMIT)
    small = LimitedProvider("small-model", context_limit=_SMALL_LIMIT)
    app = create_app(settings=_settings(tmp_path))
    app.state.run_service = _run_service(app, _two_model_agent(large, small))
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Window"}).json()[
            "conversation_id"
        ]
        source = _seed_turns(client, conversation_id, 4)
        request = {
            "prompt": "current question",
            "conversation_id": conversation_id,
            "source_user_message_id": source,
        }
        big_run = client.post("/runs", json=request).json()
        small_run = client.post(
            "/runs",
            json={
                **request,
                "execution": {
                    "model_id": "small-model",
                    "model_provider_id": "small-model",
                    "runtime_id": "native",
                },
            },
        ).json()
        big_run = client.get(f"/runs/{big_run['run_id']}").json()
        small_run = client.get(f"/runs/{small_run['run_id']}").json()

    # The default model reports a window large enough to keep every turn.
    assert len(large.requests) == 5
    assert len(large.requests[-1].messages) == 9
    # The smaller model must have dropped old turns, never the current question.
    small_messages = small.requests[-1].messages
    assert 1 < len(small_messages) < 9
    assert small_messages[-1].content.startswith("current question")
    assert big_run["status"] == "completed"
    assert small_run["status"] == "completed"


def test_execution_override_changes_the_budget_only_by_selecting_another_model(tmp_path) -> None:
    """Omitted and explicit execution differ by the model they select, nothing else.

    The window policy is not re-derived from the override payload: selecting the
    same model explicitly produces the same bounded context as omitting execution
    entirely, while selecting a different model produces a different one.
    """
    provider = LimitedProvider("only-model", context_limit=_SMALL_LIMIT)
    app = create_app(settings=_settings(tmp_path))
    app.state.run_service = _run_service(app, _agent(provider))
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Override"}).json()[
            "conversation_id"
        ]
        source = _seed_turns(client, conversation_id, 4)
        request = {
            "prompt": "current question",
            "conversation_id": conversation_id,
            "source_user_message_id": source,
        }
        client.post("/runs", json=request)
        client.post(
            "/runs",
            json={**request, "execution": {"model_id": "only-model"}},
        )

    assert len(provider.requests) == 6
    omitted = [entry.content for entry in provider.requests[-2].messages]
    explicit = [entry.content for entry in provider.requests[-1].messages]
    assert omitted == explicit


def test_unknown_model_limit_executes_with_the_full_eligible_context(tmp_path) -> None:
    """A model reporting no context window keeps legacy behavior."""
    provider = LimitedProvider("unbounded-model", context_limit=None)
    app = create_app(settings=_settings(tmp_path))
    app.state.run_service = _run_service(app, _agent(provider))
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Unknown"}).json()[
            "conversation_id"
        ]
        source = _seed_turns(client, conversation_id, 3)
        response = client.post(
            "/runs",
            json={
                "prompt": "current question",
                "conversation_id": conversation_id,
                "source_user_message_id": source,
            },
        )

    assert response.status_code == 202
    with TestClient(app) as client:
        assert client.get(f"/runs/{response.json()['run_id']}").json()["status"] == "completed"
    assert len(provider.requests[-1].messages) == 7


# ============================================================
# END: Selected Model Determines The Budget
# ============================================================
# ============================================================
# BEGIN: Failure Before Provider Invocation
# ============================================================


def test_an_impossible_request_fails_before_the_provider_is_called(tmp_path) -> None:
    """A current turn larger than the whole window is a deterministic failure."""
    provider = LimitedProvider("tiny-model", context_limit=1_024)
    app = create_app(settings=_settings(tmp_path))
    app.state.run_service = _run_service(app, _agent(provider))
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Too big"}).json()[
            "conversation_id"
        ]
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "q" * 8_000, "role": "user"},
        ).json()
        response = client.post(
            "/runs",
            json={
                "prompt": "q" * 8_000,
                "conversation_id": conversation_id,
                "source_user_message_id": message["message_id"],
            },
        )

        assert response.status_code == 202
        body = response.json()
        body = client.get(f"/runs/{body['run_id']}").json()
        assert body["status"] == "failed"
        run_events = client.get(f"/runs/{body['run_id']}/events").json()

    assert provider.requests == [], "the provider must never be invoked"
    assert [event["event_type"] for event in run_events] == [
        "run_started", "message_started", "run_failed",
    ]
    assert run_events[-1]["payload"]["error_code"] == "context_window_exceeded"


def test_an_oversized_old_turn_is_dropped_instead_of_failing(tmp_path) -> None:
    """Old history is droppable; only the current turn is mandatory."""
    provider = LimitedProvider("small-model", context_limit=_SMALL_LIMIT)
    app = create_app(settings=_settings(tmp_path))
    app.state.run_service = _run_service(app, _agent(provider))
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Big old"}).json()[
            "conversation_id"
        ]
        source = _seed_turns(client, conversation_id, 3, size=4_000)
        response = client.post(
            "/runs",
            json={
                "prompt": "current question",
                "conversation_id": conversation_id,
                "source_user_message_id": source,
            },
        )

    assert response.status_code == 202
    with TestClient(app) as client:
        assert client.get(f"/runs/{response.json()['run_id']}").json()["status"] == "completed"
    contents = [entry.content for entry in provider.requests[-1].messages]
    assert contents[-1] == "current question"
    assert not any(content.startswith("U1 ") for content in contents)


# ============================================================
# END: Failure Before Provider Invocation
# ============================================================
# ============================================================
# BEGIN: Runtime Parity
# ============================================================


def test_both_runtimes_receive_the_same_bounded_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Native and OpenHands are handed one bounded sequence, then translate it.

    AVA windows before the runtime boundary, so neither runtime can trim
    differently: the Native provider request and the rendered OpenHands message
    carry the same retained turns.
    """
    from ava.runtimes.adapters.openhands import openhands_runtime

    captured = _stub_openhands_sdk(monkeypatch)
    monkeypatch.setattr(
        openhands_runtime,
        "bind_model_provider",
        _offline_binding,
    )
    provider = LimitedProvider("bounded-model", context_limit=_SMALL_LIMIT)
    manager = ContextWindowManager()
    history: list[ContextMessage] = []
    for number in range(1, 7):
        history.append(
            ContextMessage(role=MessageRole.USER, content=f"U{number} " + "x" * 2_000)
        )
        history.append(
            ContextMessage(role=MessageRole.ASSISTANT, content=f"A{number} " + "y" * 2_000)
        )
    history.append(ContextMessage(role=MessageRole.USER, content="current question"))
    full = RunContext(
        conversation_id="conversation-1",
        source_user_message_id="message-13",
        messages=history,
    )
    bounded = manager.fit(
        full.messages,
        model_context_limit=_SMALL_LIMIT,
        model_id="bounded-model",
    ).messages
    context = full.model_copy(update={"messages": bounded})
    assert len(bounded) < len(full.messages), "the fixture must require trimming"

    native = NativeRuntime()
    openhands = OpenHandsRuntime()

    async def scenario() -> None:
        await native.execute(
            run_id="native-run",
            request=RunRequest(prompt="current question"),
            model_provider=provider,
            context=context,
        )
        await openhands.execute(
            run_id="openhands-run",
            request=RunRequest(prompt="current question"),
            model_provider=provider,
            context=context,
        )

    asyncio.run(scenario())

    native_sequence = [entry.content for entry in provider.requests[-1].messages]
    rendered = captured["sent"][0]
    # A whole-turn suffix reaches both runtimes, newest first is preserved.
    assert native_sequence[-1] == "current question"
    assert len(bounded) < len(full.messages), "the fixture must require trimming"
    assert bounded == history[-5:], "the retained context is a whole-turn suffix"
    assert bounded[-1].content == "current question"
    for content in native_sequence:
        assert content in rendered
    # The dropped turns are absent from both runtimes, so neither runtime can
    # reintroduce history the window already removed.
    assert "U1 " + "x" * 2_000 not in rendered
    assert not any(content.startswith("U1 ") for content in native_sequence)


def test_selecting_the_openhands_runtime_still_bounds_the_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The bounding call site is above the runtime boundary, not inside a runtime.

    Running the same conversation through the OpenHands runtime with a small
    selected model produces a prompt with old turns already removed, which only
    happens if AVA windowed the context before dispatch.
    """
    from ava.runtimes.adapters.openhands import openhands_runtime

    captured = _stub_openhands_sdk(monkeypatch)
    monkeypatch.setattr(openhands_runtime, "bind_model_provider", _offline_binding)
    provider = LimitedProvider("small-model", context_limit=_SMALL_LIMIT)
    app = create_app(settings=_settings(tmp_path))
    app.state.run_service = _run_service(app, _agent(provider))
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "OH"}).json()[
            "conversation_id"
        ]
        source = _seed_turns(client, conversation_id, 4)
        response = client.post(
            "/runs",
            json={
                "prompt": "current question",
                "conversation_id": conversation_id,
                "source_user_message_id": source,
                "execution": {
                    "runtime_id": "openhands",
                    "model_id": "small-model",
                    "model_provider_id": "small-model",
                },
            },
        )

    assert response.status_code == 202
    with TestClient(app) as client:
        assert client.get(f"/runs/{response.json()['run_id']}").json()["status"] == "completed"
    rendered = captured["sent"][0]
    assert rendered.endswith("current question")
    assert "U1 " + "x" * 3_000 not in rendered
    # One message reached the SDK, carrying only the retained turns.
    assert len(captured["sent"]) == 1
    assert rendered.count("current question") == 1


# ============================================================
# END: Runtime Parity
# ============================================================
# ============================================================
# BEGIN: Context Construction Layering
# ============================================================


def test_windowing_never_reintroduces_a_superseded_answer(tmp_path) -> None:
    """Regenerate semantics survive windowing: one visible answer per turn."""
    provider = LimitedProvider("regen-model", context_limit=_SMALL_LIMIT)
    app = create_app(settings=_settings(tmp_path))
    app.state.run_service = _run_service(app, _agent(provider))
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Regen"}).json()[
            "conversation_id"
        ]
        first = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "U1 " + "x" * 1_000, "role": "user"},
        ).json()
        for _attempt in range(3):
            client.post(
                "/runs",
                json={
                    "prompt": "U1 " + "x" * 1_000,
                    "conversation_id": conversation_id,
                    "source_user_message_id": first["message_id"],
                },
            )
        second = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "U2 " + "x" * 1_000, "role": "user"},
        ).json()
        client.post(
            "/runs",
            json={
                "prompt": "U2 " + "x" * 1_000,
                "conversation_id": conversation_id,
                "source_user_message_id": second["message_id"],
            },
        )

    contents = [entry.content for entry in provider.requests[-1].messages]
    # Three durable answers to U1 collapse to one visible answer before windowing.
    assert contents.count("answered") == 1
    assert [entry.role for entry in provider.requests[-1].messages] == [
        "user",
        "assistant",
        "user",
    ]


def test_the_unlinked_prompt_path_is_still_windowed_and_unchanged(tmp_path) -> None:
    """A legacy direct ``/runs`` caller keeps its single-prompt behavior."""
    provider = LimitedProvider("prompt-model", context_limit=_LARGE_LIMIT)
    app = create_app(settings=_settings(tmp_path))
    app.state.run_service = _run_service(app, _agent(provider))
    with TestClient(app) as client:
        response = client.post("/runs", json={"prompt": "just this"})

    assert response.status_code == 202
    assert [entry.content for entry in provider.requests[-1].messages] == ["just this"]


def test_budget_accounting_matches_the_manager_and_the_provider_request(tmp_path) -> None:
    """The estimate the manager used describes the request that was sent."""
    provider = LimitedProvider("accounting-model", context_limit=_SMALL_LIMIT)
    app = create_app(settings=_settings(tmp_path))
    app.state.run_service = _run_service(app, _agent(provider))
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Books"}).json()[
            "conversation_id"
        ]
        source = _seed_turns(client, conversation_id, 5)
        client.post(
            "/runs",
            json={
                "prompt": "current question",
                "conversation_id": conversation_id,
                "source_user_message_id": source,
            },
        )

    sent = provider.requests[-1].messages
    budget = input_budget_for(_SMALL_LIMIT)
    assert budget == _SMALL_LIMIT - min(
        DEFAULT_OUTPUT_RESERVE_TOKENS, int(_SMALL_LIMIT * 0.25)
    )
    estimator = DeterministicTokenEstimator()
    translated = [
        ContextMessage(role=MessageRole(entry.role), content=entry.content) for entry in sent
    ]
    assert estimator.estimate_messages(translated) <= budget
    # The full eligible context was larger, which is why trimming happened.
    full = app.state.context_construction_service.build_for_source(conversation_id, source)
    assert estimator.estimate_messages(full.messages) > budget


# ============================================================
# END: Context Construction Layering
# ============================================================
