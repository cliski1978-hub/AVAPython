"""Phase 5.23 run-lifecycle integration tests.

These tests drive the real run path — a durable conversation/message/run graph
over relational persistence, the real ``RunService``, the real lifecycle
authority, and fake model providers — to pin the observable ordering, the
failure mappings, the cancellation baseline Phase 5.24 will build on, regenerate
independence, and what survives a restart. No network is used.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.agents.contracts import AgentPort, AgentRunResult
from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.conversations import MessageRole
from ava.contracts.events import EventType
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
from ava.contracts.responses import RunResponse, RunStatus
from ava.execution.selector import ExecutionSelector, ResolvedExecution
from ava.models.bindings import ModelBindingResolver
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.registry import RuntimeRegistry
from ava.runtimes.resolver import RuntimeResolver
from ava.services.run_lifecycle_service import RunLifecycleService
from ava.services.run_service import RunService

_TINY_LIMIT = 1_024

# ============================================================
# BEGIN: Fakes
# ============================================================


@dataclass
class RecordingProvider(ModelProviderPort):
    """Fake provider that records every request it is asked to answer."""

    __test__ = False
    provider_id: str
    context_limit: int | None = None
    fail_with: Exception | None = None
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
        if self.fail_with is not None:
            raise self.fail_with
        return ModelResponse(content="answered", model_id=self.provider_id)


class ModelProviderError(Exception):
    """Stand-in for a provider SDK error raised inside the runtime."""


@dataclass
class ControllableAgent(AgentPort):
    """Agent whose outcome the test decides, including a cancel race.

    ``outcome`` is what ``start_run`` returns. ``cancel_status`` is what
    ``cancel_run`` reports, which is how a cancellation that wins a race against
    a completing run is simulated: the service observes an already-terminal run
    after the agent returns.
    """

    __test__ = False
    outcome: RunStatus = RunStatus.COMPLETED
    content: str = "answered"
    cancel_status: RunStatus = RunStatus.CANCELLED
    before_return: object = None

    def name(self) -> str:
        return "controllable"

    def get_capabilities(self) -> set:
        return set()

    async def start_run(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: object = None,
        resolved_execution: ResolvedExecution | None = None,
    ) -> AgentRunResult:
        del context, resolved_execution
        if self.before_return is not None:
            self.before_return(run_id)  # type: ignore[operator]
        return AgentRunResult(status=self.outcome, content=self.content)

    async def cancel_run(self, run_id: str) -> RunResponse:
        del run_id
        return RunResponse(run_id="run", status=self.cancel_status)


class _BlockingAgent(AgentPort):
    """Agent that stays in flight until it is released or cancelled."""

    __test__ = False

    def __init__(self) -> None:
        self.run_id: str | None = None
        self._cancelled = False

    def name(self) -> str:
        return "blocking"

    def get_capabilities(self) -> set:
        return set()

    async def start_run(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: object = None,
        resolved_execution: ResolvedExecution | None = None,
    ) -> AgentRunResult:
        del request, context, resolved_execution
        self.run_id = run_id
        while not self._cancelled:
            await asyncio.sleep(0)
        return AgentRunResult(status=RunStatus.CANCELLED)

    async def cancel_run(self, run_id: str) -> RunResponse:
        self._cancelled = True
        return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "lifecycle.sqlite3"),
        attachment_storage="memory",
    )


def _provider_agent(provider: ModelProviderPort) -> NativeAgentAdapter:
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
    runtimes = RuntimeRegistry()
    runtimes.register("native", NativeRuntime())
    return NativeAgentAdapter(
        ExecutionSelector(
            runtime_resolver=RuntimeResolver(runtimes),
            model_provider_resolver=ModelProviderResolver(provider_registry),
            model_binding_resolver=ModelBindingResolver(
                model_registry, default_model_id=model_registry.list()[0].model_id
            ),
            default_runtime_id="native",
            default_model_provider_id=provider.name(),
        )
    )


def _app(tmp_path: Path, agent: AgentPort):
    app = create_app(settings=_settings(tmp_path))
    persistence = app.state.persistence
    app.state.run_service = RunService(
        agent,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        context_service=app.state.context_construction_service,
    )
    app.state.lifecycle = RunLifecycleService(
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )
    return app


def _lifecycle(app) -> RunLifecycleService:
    return app.state.lifecycle


def _linked_run(client: TestClient, *, content: str = "hello", title: str = "Lifecycle"):
    """Create a conversation, a user message, and return the request to run it."""
    conversation_id = client.post("/conversations", json={"title": title}).json()[
        "conversation_id"
    ]
    message = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content, "role": "user"},
    ).json()
    request = {
        "prompt": content,
        "conversation_id": conversation_id,
        "source_user_message_id": message["message_id"],
    }
    return conversation_id, message["message_id"], request


def _messages(client: TestClient, conversation_id: str) -> list[dict]:
    response = client.get(f"/conversations/{conversation_id}/messages").json()
    return list(response["messages"])


def _event_types(client: TestClient, run_id: str) -> list[EventType]:
    return [event["event_type"] for event in client.get(f"/runs/{run_id}/events").json()]


# ============================================================
# END: Fakes
# ============================================================
# ============================================================
# BEGIN: Creation and Start
# ============================================================


def test_a_run_starts_pending_running_and_records_run_started(tmp_path) -> None:
    """The placeholder exists and the run is running before execution ends."""
    app = _app(tmp_path, ControllableAgent())
    with TestClient(app) as client:
        conversation_id, source, request = _linked_run(client)
        # Observe the run the moment it is created, before the agent returns.
        observed: list[tuple[str, RunStatus]] = []
        app.state.run_service._agent.before_return = lambda run_id: observed.append(  # type: ignore[attr-defined]
            (run_id, app.state.lifecycle.get(run_id).status)
        )

        run = client.post("/runs", json=request).json()

        assert observed and observed[0][1] is RunStatus.RUNNING
        record = app.state.lifecycle.get(run["run_id"])
        assert record.status is RunStatus.COMPLETED
        assert record.conversation_id == conversation_id
        assert record.source_user_message_id == source
        assert record.assistant_message_id is not None
        assert _event_types(client, run["run_id"]) == [
            "run_started",
            "message_started",
            "message_content",
            "run_completed",
        ]


def test_the_assistant_placeholder_exists_before_the_run_is_running(tmp_path) -> None:
    """The durable assistant row is linked to the run before execution starts."""
    app = _app(tmp_path, ControllableAgent())
    with TestClient(app) as client:
        conversation_id, _, request = _linked_run(client)
        seen: list[str | None] = []
        app.state.run_service._agent.before_return = lambda run_id: seen.append(  # type: ignore[attr-defined]
            app.state.lifecycle.get(run_id).assistant_message_id
        )

        client.post("/runs", json=request)

        assert seen and seen[0] is not None
        rows = _messages(client, conversation_id)
        assistant = next(row for row in rows if row["role"] == "assistant")
        assert assistant["message_id"] == seen[0]
        assert assistant["status"] == "complete"


# ============================================================
# END: Creation and Start
# ============================================================
# ============================================================
# BEGIN: Completion Ordering
# ============================================================


def test_completion_persists_content_before_the_terminal_status(tmp_path) -> None:
    """A completed run can never be missing its final response.

    The write order is observed through a spying message repository: assistant
    content first, then the terminal status, then the completion fact.
    """
    app = _app(tmp_path, ControllableAgent(content="final answer"))
    order: list[str] = []
    runs = app.state.persistence.run_repository
    messages = app.state.persistence.message_repository
    events = app.state.persistence.run_event_repository
    original_guarded_write = runs.compare_and_set_status
    original_update_content = messages.update_content
    original_append = events.append

    def compare_and_set_status(run_id: str, *, expected_status, status: RunStatus):
        order.append(f"status:{status.value}")
        return original_guarded_write(
            run_id, expected_status=expected_status, status=status
        )

    def update_content(conversation_id: str, message_id: str, content: str):
        order.append("assistant_content")
        return original_update_content(conversation_id, message_id, content)

    def append(event):
        order.append(f"event:{event.event_type.value}")
        return original_append(event)

    runs.compare_and_set_status = compare_and_set_status  # type: ignore[method-assign]
    messages.update_content = update_content  # type: ignore[method-assign]
    events.append = append  # type: ignore[method-assign]

    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        run = client.post("/runs", json=request).json()

    assert run["status"] == "running"
    assert order == [
        "status:running",
        "event:run_started",
        "event:message_started",
        "assistant_content",
        "event:message_content",
        "status:completed",
        "event:run_completed",
    ]


def test_a_completed_run_reports_its_persisted_content_and_status(tmp_path) -> None:
    """Content, links, and status agree from the outside as well."""
    app = _app(tmp_path, ControllableAgent(content="the answer"))
    with TestClient(app) as client:
        conversation_id, _, request = _linked_run(client)
        run = client.post("/runs", json=request).json()

        stored = client.get(f"/runs/{run['run_id']}").json()
        assistant = next(
            row for row in _messages(client, conversation_id) if row["role"] == "assistant"
        )
        assert run["status"] == "running"
        assert stored["status"] == "completed"
        assert assistant["status"] == "complete"
        assert assistant["content"] == "the answer"
        assert stored["assistant_message_id"] == assistant["message_id"]


# ============================================================
# END: Completion Ordering
# ============================================================
# ============================================================
# BEGIN: Failure Ordering
# ============================================================


def _assert_failed_run(client: TestClient, app, body: dict, *, run_id: str | None = None) -> None:
    run_id = run_id or body["run_id"]
    assert body["status"] == "running"
    record = app.state.lifecycle.get(run_id)
    assert record is not None and record.status is RunStatus.FAILED
    assert _event_types(client, run_id) == ["run_started", "message_started", "run_failed"]
    conversation_id = record.conversation_id
    if conversation_id:
        assistant = next(
            row for row in _messages(client, conversation_id) if row["role"] == "assistant"
        )
        assert assistant["status"] == "failed"
        assert assistant["content"] == ""


def test_a_context_window_overflow_fails_the_run_without_calling_the_provider(
    tmp_path,
) -> None:
    """A 5.22 context-window rejection is an ordinary, terminal failure."""
    provider = RecordingProvider("tiny-model", context_limit=_TINY_LIMIT)
    app = _app(tmp_path, _provider_agent(provider))
    with TestClient(app) as client:
        conversation_id = client.post("/conversations", json={"title": "Too big"}).json()[
            "conversation_id"
        ]
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "q" * 8_000, "role": "user"},
        ).json()
        body = client.post(
            "/runs",
            json={
                "prompt": "q" * 8_000,
                "conversation_id": conversation_id,
                "source_user_message_id": message["message_id"],
            },
        ).json()
        _assert_failed_run(client, app, body)

    assert provider.requests == [], "the provider must never be invoked"


def test_an_unresolvable_execution_configuration_fails_the_run(tmp_path) -> None:
    """A 5.16/5.17 selection failure is the same terminal state, not a new one."""
    app = _app(tmp_path, _provider_agent(RecordingProvider("only-model")))
    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        body = client.post(
            "/runs",
            json={**request, "execution": {"model_id": "model-that-does-not-exist"}},
        ).json()
        _assert_failed_run(client, app, body)


def test_a_provider_exception_fails_the_run(tmp_path) -> None:
    """A provider SDK error becomes an AVA failure, never a leaked exception."""
    provider = RecordingProvider("boom-model", fail_with=ModelProviderError("vendor blew up"))
    app = _app(tmp_path, _provider_agent(provider))
    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        body = client.post("/runs", json=request).json()
        _assert_failed_run(client, app, body)

    assert len(provider.requests) == 1


def test_a_failed_run_emits_one_failure_fact_with_the_stable_error_code(tmp_path) -> None:
    """The failure event body is AVA's, not the provider's."""
    app = _app(tmp_path, ControllableAgent(outcome=RunStatus.FAILED, content="nope"))
    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        run = client.post("/runs", json=request).json()
        events = client.get(f"/runs/{run['run_id']}/events").json()

    failure = events[-1]
    assert failure["event_type"] == "run_failed"
    assert failure["payload"]["error_code"] == "agent_failed"
    assert failure["payload"]["recoverable"] is False
    assert "nope" not in str(failure["payload"])


# ============================================================
# END: Failure Ordering
# ============================================================
# ============================================================
# BEGIN: Cancellation Boundary
# ============================================================


def test_cancelling_a_run_in_flight_records_cancelled(tmp_path) -> None:
    """The 5.24 baseline, exercised while the agent is genuinely still running.

    The agent blocks until it is released or cancelled, so the cancellation
    lands on a real ``running`` run rather than on a fixture that pretends to.
    """
    app = _app(tmp_path, _BlockingAgent())
    service = app.state.run_service
    lifecycle = _lifecycle(app)

    async def scenario() -> tuple:
        started = asyncio.create_task(service.start_run(RunRequest(prompt="hello")))
        for _ in range(100):
            if service._agent.run_id:  # type: ignore[attr-defined]
                break
            await asyncio.sleep(0)
        run_id = service._agent.run_id  # type: ignore[attr-defined]
        assert lifecycle.get(run_id).status is RunStatus.RUNNING
        cancelled = await service.cancel_run(run_id)
        result = await started
        return run_id, cancelled, result

    run_id, cancelled, result = asyncio.run(scenario())
    assert cancelled.status is RunStatus.CANCELLED
    assert result.status is RunStatus.CANCELLED
    assert lifecycle.get(run_id).status is RunStatus.CANCELLED


def test_cancelling_a_terminal_run_reports_it_unchanged(tmp_path) -> None:
    """A late cancellation never rewrites a completed run."""
    app = _app(tmp_path, ControllableAgent())
    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        run = client.post("/runs", json=request).json()
        events_before = _event_types(client, run["run_id"])

        cancelled = client.post(f"/runs/{run['run_id']}/cancel").json()

        assert cancelled["status"] == "completed"
        assert _event_types(client, run["run_id"]) == events_before
        assert app.state.lifecycle.get(run["run_id"]).status is RunStatus.COMPLETED


def test_cancelling_an_unknown_run_is_hidden_from_the_caller(tmp_path) -> None:
    """Unknown Runs are indistinguishable from Runs the caller cannot access."""
    app = _app(tmp_path, ControllableAgent())
    with TestClient(app) as client:
        response = client.post("/runs/does-not-exist/cancel")
        assert response.status_code == 404
        assert app.state.lifecycle.get("does-not-exist") is None


def test_cancelling_twice_records_one_cancellation_fact(tmp_path) -> None:
    """Duplicate cancellation is idempotent at the lifecycle level."""
    app = _app(tmp_path, ControllableAgent(outcome=RunStatus.CANCELLED))
    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        run = client.post("/runs", json=request).json()
        assert run["status"] == "running"

        again = client.post(f"/runs/{run['run_id']}/cancel").json()

        assert again["status"] == "cancelled"
        assert _event_types(client, run["run_id"]) == [
            "run_started", "message_started", "run_cancelled",
        ]


# ============================================================
# END: Cancellation Boundary
# ============================================================
# ============================================================
# BEGIN: Terminal Races
# ============================================================


def test_cancellation_winning_the_race_beats_a_late_completion(tmp_path) -> None:
    """Exactly one terminal state is persisted when cancel and complete race.

    The agent cancels the run just before it returns success. The run's own
    record is the authority, so the request answers ``cancelled``, no message or
    completion events are emitted, and the persisted status is not rewritten.
    """
    app = _app(tmp_path, ControllableAgent())
    with TestClient(app) as client:
        conversation_id, _, request = _linked_run(client)
        service = app.state.run_service
        agent = service._agent  # type: ignore[attr-defined]

        async def cancel_then_complete(run_id: str, request, *, context=None):
            del request, context
            await agent.cancel_run(run_id)
            # Simulate a cancellation request landing while the run is active.
            service._lifecycle.cancel(run_id)
            return AgentRunResult(status=RunStatus.COMPLETED, content="too late")

        agent.start_run = cancel_then_complete  # type: ignore[method-assign]
        run = client.post("/runs", json=request).json()

        assert run["status"] == "running"
        assert _event_types(client, run["run_id"]) == [
            "run_started", "message_started", "run_cancelled",
        ]
        assert app.state.lifecycle.get(run["run_id"]).status is RunStatus.CANCELLED
        assistant = next(
            row for row in _messages(client, conversation_id) if row["role"] == "assistant"
        )
        assert assistant["status"] == "cancelled"
        assert assistant["content"] == ""


def test_completion_winning_the_race_is_not_overwritten_by_cancellation(tmp_path) -> None:
    """A completed run stays completed when a cancel request arrives after."""
    app = _app(tmp_path, ControllableAgent())
    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        run = client.post("/runs", json=request).json()
        cancelled = client.post(f"/runs/{run['run_id']}/cancel").json()

        assert cancelled["status"] == "completed"
        assert app.state.lifecycle.get(run["run_id"]).status is RunStatus.COMPLETED
        assert _event_types(client, run["run_id"])[-1] == "run_completed"


def test_a_cancel_reported_completion_gains_its_missing_fact(tmp_path) -> None:
    """A terminal status an agent reports for an active run gets its event.

    The run finished between the service's status read and the agent's cancel
    call. Before 5.23 the status was written without a ``run_completed`` event;
    the lifecycle authority now writes the fact with the status.
    """
    app = _app(tmp_path, ControllableAgent())
    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        service = app.state.run_service
        run_holder: list[str] = []
        agent = service._agent  # type: ignore[attr-defined]
        original = agent.start_run

        async def hold_then_cancel(run_id: str, request, *, context=None):
            run_holder.append(run_id)
            # The run settles out of band while the agent is still in flight,
            # exactly as a runtime finishing first would.
            service._lifecycle.complete(run_id)
            return await original(run_id, request, context=context)

        agent.start_run = hold_then_cancel  # type: ignore[method-assign]
        client.post("/runs", json=request)

        assert run_holder
        record = app.state.lifecycle.get(run_holder[0])
        assert record is not None and record.status is RunStatus.COMPLETED
        assert _event_types(client, run_holder[0]).count("run_completed") == 1


# ============================================================
# END: Terminal Races
# ============================================================
# ============================================================
# BEGIN: Regenerate
# ============================================================


def test_regenerated_runs_stay_independent_and_terminal(tmp_path) -> None:
    """Three attempts produce three completed runs; none mutates another."""
    app = _app(tmp_path, ControllableAgent())
    with TestClient(app) as client:
        conversation_id, source, request = _linked_run(client)
        attempts = [
            client.post("/runs", json=request).json() for _ in range(3)
        ]
        run_ids = [attempt["run_id"] for attempt in attempts]
        assert len(set(run_ids)) == 3

        for run_id in run_ids:
            assert app.state.lifecycle.get(run_id).status is RunStatus.COMPLETED
        for attempt in attempts:
            assert attempt["status"] == "running"
            assert attempt["assistant_message_id"] is not None

        rows = _messages(client, conversation_id)
        # The source message is one; every attempt owns its own assistant
        # message, and each projects the status of the run that produced it.
        assert [row["role"] for row in rows] == ["user"] + ["assistant"] * 3
        assert all(row["status"] == "complete" for row in rows if row["role"] == "assistant")
        assert all(row["message_id"] == source for row in rows if row["role"] == "user")
        assert len({row["message_id"] for row in rows if row["role"] == "assistant"}) == 3
        assert {
            row["source_run_id"] for row in rows if row["role"] == "assistant"
        } == set(run_ids)
        # A rerun of the same turn never sees an answer to that turn, so the
        # attempts cannot contaminate each other's context.
        history = app.state.context_construction_service.build_for_source(conversation_id, source)
        assert history is not None
        assert [
            message.content
            for message in history.messages
            if message.role == MessageRole.ASSISTANT
        ] == []


def test_a_regenerated_run_keeps_its_own_terminal_timestamp(tmp_path) -> None:
    """Older runs are history: their status and timestamps never move again."""
    app = _app(tmp_path, ControllableAgent())
    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        first = client.post("/runs", json=request).json()
        first_record = app.state.lifecycle.get(first["run_id"])
        assert first_record is not None
        first_created = first_record.created_at

        second = client.post("/runs", json=request).json()
        second_record = app.state.lifecycle.get(second["run_id"])
        assert second_record is not None

        after = app.state.lifecycle.get(first["run_id"])
        assert after == first_record
        assert after.created_at == first_created
        assert after.run_id != second_record.run_id


# ============================================================
# END: Regenerate
# ============================================================
# ============================================================
# BEGIN: Restart Durability
# ============================================================

_REPRESENTATIVE_STATUSES = [
    RunStatus.PENDING,
    RunStatus.RUNNING,
    RunStatus.WAITING_FOR_APPROVAL,
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
]


def _persistence(settings: Settings):
    from ava.infrastructure.composition import create_application_persistence

    return create_application_persistence(settings)


def _dispose(persistence) -> None:
    persistence.dispose()


def _record(persistence, run_id: str):
    return persistence.run_repository.get(run_id)


def test_every_status_survives_a_restart_bit_for_bit(tmp_path) -> None:
    """Persisted statuses and timestamps are exactly what a fresh process reads.

    Active statuses are deliberately *not* converted on startup: recovering a
    stranded run is Phase 5.30's job, and 5.23 must not quietly change state.
    """
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "restart.sqlite3"),
        attachment_storage="memory",
    )
    persistence = _persistence(settings)
    lifecycle = RunLifecycleService(
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )
    for status in _REPRESENTATIVE_STATUSES:
        run_id = f"run-{status.value}"
        lifecycle.create_run(run_id)
        if status in (RunStatus.PENDING,):
            continue
        lifecycle.transition(run_id, RunStatus.RUNNING)
        if status is RunStatus.WAITING_FOR_APPROVAL:
            # Reachable through the table from ``pending``; a waiting run is
            # modelled by restarting it from the state before it began.
            persistence.run_repository.update_status(run_id, RunStatus.PENDING)
            lifecycle.transition(run_id, RunStatus.WAITING_FOR_APPROVAL)
        elif status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            lifecycle.transition(run_id, status)

    before = {
        f"run-{status.value}": _record(persistence, f"run-{status.value}")
        for status in _REPRESENTATIVE_STATUSES
    }
    assert all(record is not None for record in before.values())
    _dispose(persistence)

    reopened = _persistence(settings)
    try:
        after = {
            f"run-{status.value}": _record(reopened, f"run-{status.value}")
            for status in _REPRESENTATIVE_STATUSES
        }
        assert {key: value.status for key, value in after.items() if value} == {
            key: value.status for key, value in before.items() if value
        }
        for key, record in after.items():
            assert record is not None
            original = before[key]
            assert original is not None
            assert record.created_at == original.created_at
            assert record.updated_at == original.updated_at
        # Active statuses are persisted exactly as they were left.
        assert after["run-pending"].status is RunStatus.PENDING  # type: ignore[union-attr]
        assert after["run-running"].status is RunStatus.RUNNING  # type: ignore[union-attr]
        # The durable lifecycle facts survived alongside the statuses.
        assert [event.event_type for event in reopened.run_event_repository.get_events("run-completed")] == [
            EventType.RUN_STARTED,
            EventType.RUN_COMPLETED,
        ]
    finally:
        _dispose(reopened)


def test_a_restarted_run_converges_to_failed_and_keeps_its_history(tmp_path) -> None:
    """A ``running`` run with no execution owner becomes a truthful ``failed``.

    Phase 5.30 replaced the earlier "startup does nothing" behavior. A process
    restart cannot be silent about lost work: the run is settled through the
    lifecycle authority with a recovery-time fact, while its created time and
    the facts that preceded the loss are left alone.
    """
    database = tmp_path / "stranded.sqlite3"
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(database),
        attachment_storage="memory",
    )
    first = _persistence(settings)
    lifecycle = RunLifecycleService(
        run_repository=first.run_repository,
        run_event_repository=first.run_event_repository,
    )
    lifecycle.create_run("stranded-run")
    lifecycle.transition("stranded-run", RunStatus.RUNNING)
    before = first.run_repository.get("stranded-run")
    _dispose(first)

    app = create_app(settings=settings)
    with TestClient(app) as client:
        stored = client.get("/runs/stranded-run")
        events = client.get("/runs/stranded-run/events")
    recovered = app.state.persistence.run_repository.get("stranded-run")
    app.state.persistence.dispose()

    assert before is not None
    assert before.status is RunStatus.RUNNING
    assert recovered is not None and recovered.status is RunStatus.FAILED
    assert stored.status_code == 404
    assert events.status_code == 404
    # The failure is recorded when recovery observed it, not backdated.
    recovery_events = app.state.persistence.run_event_repository.list_for_run("stranded-run")
    assert recovery_events[-1].timestamp >= before.created_at


# ============================================================
# END: Restart Durability
# ============================================================
# ============================================================
# BEGIN: Execution Semantics
# ============================================================


def test_omitted_and_explicit_execution_remain_distinct(tmp_path) -> None:
    """Lifecycle normalization does not collapse execution selection."""
    provider = RecordingProvider("only-model")
    app = _app(tmp_path, _provider_agent(provider))
    with TestClient(app) as client:
        _, _, request = _linked_run(client)
        omitted = client.post("/runs", json=request).json()
        explicit = client.post(
            "/runs", json={**request, "execution": {"model_id": "only-model"}}
        ).json()

    assert omitted["run_id"] != explicit["run_id"]
    for run in (omitted, explicit):
        assert run["status"] == "running"
        assert app.state.lifecycle.get(run["run_id"]).execution_selection is not None
    assert len(provider.requests) == 2


# ============================================================
# END: Execution Semantics
# ============================================================
