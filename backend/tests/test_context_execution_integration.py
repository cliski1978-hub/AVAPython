"""Phase 5.21 execution-context integration tests.

These tests prove the assembled context actually reaches execution rather than
merely existing: one path runs a real durable conversation/message/run graph
through a fake Native provider and inspects the provider request, and one path
drives the OpenHands runtime through its controlled SDK seam and inspects the
single message the SDK accepts. No external network is used.
"""

from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.agents.contracts import AgentPort, AgentRunResult
from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import ContextMessage, MessageRole, RunContext
from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.models.bindings import ConfiguredModelBinding, RuntimeModelBinding
from ava.models.contracts import ModelProviderPort
from ava.models.errors import ModelProviderError
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.adapters.openhands.openhands_runtime import OpenHandsRuntime
from ava.runtimes.contracts import RuntimeRunResult
from ava.services.context_construction_service import (
    ContextConstructionService,
    ContextConversationNotFoundError,
)
from ava.services.run_service import RunService

# ============================================================
# BEGIN: Fakes
# ============================================================


@dataclass
class RecordingProvider(ModelProviderPort):
    """Fake model provider that records every request it receives.

    ``failing_turns`` fails generation for a run whose current user turn is one
    of these texts, which is how a failed assistant answer is produced without
    touching run state directly.
    """

    __test__ = False
    requests: list[ModelRequest] = field(default_factory=list)
    failing_turns: frozenset[str] = frozenset()

    def name(self) -> str:
        return "recording"

    async def health(self) -> ModelProviderHealth:
        return ModelProviderHealth(status=ModelProviderHealthStatus.HEALTHY, available=True)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id="recording-model",
            provider_name="recording",
            display_name="Recording",
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        del model_name
        self.requests.append(request)
        if request.messages and request.messages[-1].content in self.failing_turns:
            raise ModelProviderError("scripted provider failure")
        return ModelResponse(content="answered", model_id="recording-model")


def _relational_settings(tmp_path) -> Settings:
    return Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "context.sqlite3"),
        attachment_storage="memory",
    )


def _linked_run_service(app, provider: ModelProviderPort) -> RunService:
    """Wire a run service over the app's own durable persistence.

    Only the model provider is replaced, so the conversation, message, and run
    rows a test creates through the API are exactly the rows context
    construction reads, and the production context service is exercised
    unchanged.
    """
    persistence = app.state.persistence
    return RunService(
        NativeAgentAdapter(NativeRuntime(), provider),
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        context_service=app.state.context_construction_service,
    )


def _stub_binding(
    provider: ModelProviderPort, binding: ConfiguredModelBinding
) -> RuntimeModelBinding:
    """Deterministic offline model binding for the OpenHands seam."""
    del provider
    return RuntimeModelBinding(
        model_id=binding.model_id,
        provider_id=binding.provider_id,
        provider_model_name=binding.provider_model_name,
        protocol="openai",
        endpoint="http://localhost/v1",
        api_key=None,
    )


def _stub_openhands_sdk(monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]) -> None:
    """Controlled OpenHands SDK seam that records what the agent is sent."""

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

        def send_message(self, message: object) -> None:
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

    sent: list[object] = []
    captured["sent"] = sent
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


# ============================================================
# END: Fakes
# ============================================================
# ============================================================
# BEGIN: Native Path
# ============================================================


def test_native_provider_receives_the_durable_context(tmp_path) -> None:
    """A linked run's model request is the durable history, not one prompt."""
    app = create_app(settings=_relational_settings(tmp_path))
    provider = RecordingProvider()
    app.state.run_service = _linked_run_service(app, provider)
    with TestClient(app) as client:
        conversation = client.post("/conversations", json={"title": "Context"}).json()
        conversation_id = conversation["conversation_id"]

        def ask(content: str) -> str:
            message = client.post(
                f"/conversations/{conversation_id}/messages",
                json={"content": content, "role": "user"},
            ).json()
            response = client.post(
                "/runs",
                json={
                    "prompt": content,
                    "conversation_id": conversation_id,
                    "source_user_message_id": message["message_id"],
                },
            )
            assert response.status_code == 202, response.text
            assert client.get(f"/runs/{response.json()['run_id']}").json()["status"] == "completed"
            return message["message_id"]

        first = ask("U1")
        ask("U2")
        third = ask("U3")

        context = app.state.context_construction_service.build_for_source(conversation_id, third)

    assert [message.content for message in context.messages] == [
        "U1",
        "answered",
        "U2",
        "answered",
        "U3",
    ]
    assert first != third
    # Every run asked the model with its own turn's history, and the prompt was
    # never appended a second time.
    assert [len(request.messages) for request in provider.requests] == [1, 3, 5]
    assert provider.requests[0].messages[0].content == "U1"
    assert provider.requests[1].messages[-1].content == "U2"
    assert provider.requests[2].messages[-1].content == "U3"
    assert provider.requests[2].messages[-2].role == "assistant"


def test_prompt_is_never_duplicated_when_it_matches_the_durable_message(tmp_path) -> None:
    """The regression this phase exists to prevent: prompt plus its own source."""
    app = create_app(settings=_relational_settings(tmp_path))
    provider = RecordingProvider()
    app.state.run_service = _linked_run_service(app, provider)
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Dup"}).json()["conversation_id"]
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "same text", "role": "user"},
        ).json()
        client.post(
            "/runs",
            json={
                "prompt": "same text",
                "conversation_id": conversation_id,
                "source_user_message_id": message["message_id"],
            },
        )

    assert len(provider.requests) == 1
    contents = [entry.content for entry in provider.requests[0].messages]
    assert contents == ["same text"]
    assert contents.count("same text") == 1


def test_client_supplied_history_is_not_execution_input(tmp_path) -> None:
    """A caller cannot inject or replace context through the public request."""
    app = create_app(settings=_relational_settings(tmp_path))
    provider = RecordingProvider()
    app.state.run_service = _linked_run_service(app, provider)
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Client"}).json()["conversation_id"]
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "real question", "role": "user"},
        ).json()
        response = client.post(
            "/runs",
            json={
                "prompt": "real question",
                "conversation_id": conversation_id,
                "source_user_message_id": message["message_id"],
                "context_messages": [
                    {"role": "user", "content": "fabricated earlier turn"},
                ],
                "messages": [{"role": "assistant", "content": "fabricated answer"}],
            },
        )
        assert response.status_code == 202, response.text
        assert client.get(f"/runs/{response.json()['run_id']}").json()["status"] == "completed"

    contents = [entry.content for entry in provider.requests[0].messages]
    assert contents == ["real question"]
    assert "fabricated earlier turn" not in contents


def test_unlinked_run_keeps_prompt_only_behavior(tmp_path) -> None:
    """A legacy direct ``/runs`` caller still executes a single message."""
    app = create_app(settings=_relational_settings(tmp_path))
    provider = RecordingProvider()
    app.state.run_service = _linked_run_service(app, provider)
    with TestClient(app) as client:
        response = client.post("/runs", json={"prompt": "no conversation"})

    assert response.status_code == 202, response.text
    assert [entry.content for entry in provider.requests[0].messages] == ["no conversation"]


def test_incomplete_answers_never_reach_the_model(tmp_path) -> None:
    """A failed answer is dropped from context even while its turn is visible."""
    app = create_app(settings=_relational_settings(tmp_path))
    provider = RecordingProvider()
    app.state.run_service = _linked_run_service(app, provider)
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Fail"}).json()["conversation_id"]

        def ask(content: str) -> str:
            message = client.post(
                f"/conversations/{conversation_id}/messages",
                json={"content": content, "role": "user"},
            ).json()
            response = client.post(
                "/runs",
                json={
                    "prompt": content,
                    "conversation_id": conversation_id,
                    "source_user_message_id": message["message_id"],
                },
            )
            assert response.status_code == 202, response.text
            assert client.get(f"/runs/{response.json()['run_id']}").json()["status"] == "completed"
            return message["message_id"]

        # Answer U1, then regenerate the same turn with a run that fails. The
        # provider sees the durable turn, not the request prompt, so the
        # scripted failure keys on that text.
        source = ask("U1")
        provider.failing_turns = frozenset({"U1"})
        failed = client.post(
            "/runs",
            json={
                "prompt": "try again",
                "conversation_id": conversation_id,
                "source_user_message_id": source,
            },
        )
        assert failed.status_code == 202
        assert client.get(f"/runs/{failed.json()['run_id']}").json()["status"] == RunStatus.FAILED
        provider.failing_turns = frozenset()
        ask("U2")

    contents = [entry.content for entry in provider.requests[-1].messages]
    assert contents == ["U1", "U2"]


# ============================================================
# END: Native Path
# ============================================================
# ============================================================
# BEGIN: Placeholder and Failure Modes
# ============================================================


class RecordingAgent(AgentPort):
    """Agent adapter that captures the context each run was given."""

    __test__ = False

    def __init__(self) -> None:
        self.contexts: dict[str, RunContext] = {}
        self.prompts: dict[str, str] = {}

    def name(self) -> str:
        return "recording-agent"

    def get_capabilities(self) -> set[CapabilityName]:
        return {CapabilityName.RUNS}

    async def start_run(
        self, run_id: str, request: RunRequest, *, context: RunContext | None = None
    ) -> AgentRunResult:
        self.prompts[run_id] = request.prompt
        self.contexts[run_id] = context or RunContext()
        return AgentRunResult(status=RunStatus.COMPLETED, content="answered")

    async def cancel_run(self, run_id: str) -> RunResponse:
        return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)


class BrokenContextService(ContextConstructionService):
    """Context service whose durable graph cannot be resolved."""

    def build_for_source(
        self, conversation_id: str, source_user_message_id: str | None
    ) -> RunContext:
        raise ContextConversationNotFoundError(f"conversation {conversation_id} is gone")


def test_the_runs_own_placeholder_is_never_its_own_context(tmp_path) -> None:
    """The pending assistant message created for a run must not feed that run."""
    app = create_app(settings=_relational_settings(tmp_path))
    agent = RecordingAgent()
    persistence = app.state.persistence
    app.state.run_service = RunService(
        agent,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        context_service=app.state.context_construction_service,
    )
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Self"}).json()["conversation_id"]
        first = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "U1", "role": "user"},
        ).json()
        client.post(
            "/runs",
            json={
                "prompt": "U1",
                "conversation_id": conversation_id,
                "source_user_message_id": first["message_id"],
            },
        )
        second = client.post(
            "/runs",
            json={
                "prompt": "U2",
                "conversation_id": conversation_id,
                "source_user_message_id": first["message_id"],
            },
        ).json()

    context = agent.contexts[second["run_id"]]
    assert [message.content for message in context.messages] == ["U1"]
    assert second["assistant_message_id"] not in [
        message.message_id for message in context.messages
    ]
    # The run's prompt reached the adapter, and the adapter was still given the
    # durable context as the only history authority.
    assert agent.prompts[second["run_id"]] == "U2"


def test_linked_run_without_a_context_service_is_rejected(tmp_path) -> None:
    """A linked run never silently degrades to prompt-only execution."""
    app = create_app(settings=_relational_settings(tmp_path))
    persistence = app.state.persistence
    app.state.run_service = RunService(
        RecordingAgent(),
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
    )
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Wired"}).json()["conversation_id"]
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "U1", "role": "user"},
        ).json()
        response = client.post(
            "/runs",
            json={
                "prompt": "U1",
                "conversation_id": conversation_id,
                "source_user_message_id": message["message_id"],
            },
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_run_relationship"


def test_unresolvable_context_is_reported_deterministically(tmp_path) -> None:
    """A corrupt durable graph is an explicit error, never a prompt-only run."""
    app = create_app(settings=_relational_settings(tmp_path))
    agent = RecordingAgent()
    persistence = app.state.persistence
    app.state.run_service = RunService(
        agent,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        context_service=BrokenContextService(
            run_repository=persistence.run_repository,
            message_repository=persistence.message_repository,
            conversation_repository=persistence.conversation_repository,
        ),
    )
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Broken"}).json()["conversation_id"]
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "U1", "role": "user"},
        ).json()
        response = client.post(
            "/runs",
            json={
                "prompt": "U1",
                "conversation_id": conversation_id,
                "source_user_message_id": message["message_id"],
            },
        )

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "context_construction_failed"
    assert body["category"] == "internal"
    assert agent.contexts == {}


# ============================================================
# END: Placeholder and Failure Modes
# ============================================================
# ============================================================
# BEGIN: OpenHands Path
# ============================================================


def test_openhands_receives_the_same_context_translated_to_one_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK takes one user message, so the sequence is rendered, not dropped."""
    from ava.runtimes.adapters.openhands import openhands_runtime

    captured: dict[str, object] = {}
    _stub_openhands_sdk(monkeypatch, captured)
    monkeypatch.setattr(
        openhands_runtime, "bind_model_provider", _stub_binding
    )
    runtime = OpenHandsRuntime()
    context = RunContext(
        conversation_id="conversation-1",
        source_user_message_id="message-5",
        messages=[
            ContextMessage(role=MessageRole.USER, content="U1"),
            ContextMessage(role=MessageRole.ASSISTANT, content="A1"),
            ContextMessage(role=MessageRole.USER, content="U2"),
        ],
    )

    async def scenario() -> RuntimeRunResult:
        return await runtime.execute(
            run_id="run-1",
            request=RunRequest(prompt="U2"),
            model_provider=RecordingProvider(),
            context=context,
        )

    result = asyncio.run(scenario())

    assert result.status == RunStatus.COMPLETED
    sent = captured["sent"]
    assert isinstance(sent, list) and len(sent) == 1
    rendered = str(sent[0])
    assert rendered.index("U1") < rendered.index("A1") < rendered.index("U2")
    assert rendered.count("U2") == 1
    assert rendered.startswith("Earlier messages in this conversation")


def test_openhands_single_turn_stays_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    """One user message is forwarded unchanged, so existing prompts are untouched."""
    from ava.runtimes.adapters.openhands import openhands_runtime

    captured: dict[str, object] = {}
    _stub_openhands_sdk(monkeypatch, captured)
    monkeypatch.setattr(
        openhands_runtime, "bind_model_provider", _stub_binding
    )
    runtime = OpenHandsRuntime()

    async def scenario() -> RuntimeRunResult:
        return await runtime.execute(
            run_id="run-1",
            request=RunRequest(prompt="just this"),
            model_provider=RecordingProvider(),
            context=RunContext(
                conversation_id="conversation-1",
                source_user_message_id="message-1",
                messages=[ContextMessage(role=MessageRole.USER, content="just this")],
            ),
        )

    result = asyncio.run(scenario())

    assert result.status == RunStatus.COMPLETED
    assert captured["sent"] == ["just this"]


def test_openhands_unlinked_run_falls_back_to_the_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    from ava.runtimes.adapters.openhands import openhands_runtime

    captured: dict[str, object] = {}
    _stub_openhands_sdk(monkeypatch, captured)
    monkeypatch.setattr(
        openhands_runtime, "bind_model_provider", _stub_binding
    )
    runtime = OpenHandsRuntime()

    async def scenario() -> RuntimeRunResult:
        return await runtime.execute(
            run_id="run-1",
            request=RunRequest(prompt="legacy"),
            model_provider=RecordingProvider(),
        )

    assert asyncio.run(scenario()).status == RunStatus.COMPLETED
    assert captured["sent"] == ["legacy"]


# ============================================================
# END: OpenHands Path
# ============================================================
# ============================================================
# BEGIN: Cross-Runtime Parity
# ============================================================


def test_both_runtimes_receive_the_same_semantic_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parity is semantic: identical ordered content, runtime-shaped requests."""
    from ava.runtimes.adapters.openhands import openhands_runtime

    captured: dict[str, object] = {}
    _stub_openhands_sdk(monkeypatch, captured)
    monkeypatch.setattr(
        openhands_runtime, "bind_model_provider", _stub_binding
    )
    provider = RecordingProvider()
    native = NativeRuntime()
    openhands = OpenHandsRuntime()
    context = RunContext(
        conversation_id="conversation-1",
        source_user_message_id="message-3",
        messages=[
            ContextMessage(role=MessageRole.USER, content="U1"),
            ContextMessage(role=MessageRole.ASSISTANT, content="A1"),
            ContextMessage(role=MessageRole.USER, content="U2"),
        ],
    )

    async def scenario() -> None:
        await native.execute(
            run_id="native-run",
            request=RunRequest(prompt="U2"),
            model_provider=provider,
            context=context,
        )
        await openhands.execute(
            run_id="openhands-run",
            request=RunRequest(prompt="U2"),
            model_provider=provider,
            context=context,
        )

    asyncio.run(scenario())

    native_sequence = [(entry.role, entry.content) for entry in provider.requests[0].messages]
    rendered = str(captured["sent"][0])  # type: ignore[index]
    assert native_sequence == [("user", "U1"), ("assistant", "A1"), ("user", "U2")]
    for _role, content in native_sequence:
        assert content in rendered
    assert rendered.index("U1") < rendered.index("A1") < rendered.index("U2")


# ============================================================
# END: Cross-Runtime Parity
# ============================================================
