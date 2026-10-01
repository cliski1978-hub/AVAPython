"""Phase 5.25 SSE transport tests over persisted AVA run events."""

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.api.app import create_app
from ava.api.routes.runs import _run_event_stream, stream_run
from ava.contracts.events import EventType, RunEvent
from ava.contracts.failures import FailureCode
from ava.contracts.models import ModelCapabilities, ModelInfo
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.infrastructure.model_provider_factory import ConfiguredModelProviderFactory
from ava.models.contracts import (
    ModelProviderHealth,
    ModelRequest,
    ModelResponse,
)
from ava.models.errors import ModelProviderError
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore


def _events_from_sse(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for frame in body.split("\n\n"):
        data = next((line[6:] for line in frame.splitlines() if line.startswith("data: ")), None)
        if data is not None:
            events.append(json.loads(data))
    return events


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


async def _stream_events_after(service: RunService, run_id: str, after_sequence: int) -> list[dict[str, object]]:
    chunks = [
        chunk async for chunk in _run_event_stream(
            _ConnectedRequest(), service, run_id, after_sequence=after_sequence
        )
    ]
    return _events_from_sse("".join(chunks))


def _completed_app(*, fail: bool = False):
    app = create_app()
    service = RunService(
        MockAgentAdapter(fail_on_prompt="fail" if fail else None),
        run_repository=RunStore(),
        run_event_repository=RunEventStore(),
    )
    app.state.run_service = service
    result = asyncio.run(service.start_run(RunRequest(prompt="fail" if fail else "hello")))
    return app, result.run_id


def _cancelled_app():
    app = create_app()
    adapter = MockAgentAdapter(run_delay=0.05)
    service = RunService(adapter, run_repository=RunStore(), run_event_repository=RunEventStore())
    app.state.run_service = service

    async def cancel() -> str:
        task = asyncio.create_task(service.start_run(RunRequest(prompt="hello")))
        await asyncio.sleep(0)
        (run_id,) = adapter.active_run_ids()
        await service.cancel_run(run_id)
        await task
        return run_id

    return app, asyncio.run(cancel())


def test_stream_observes_one_completed_run_in_stable_persisted_order() -> None:
    app, run_id = _completed_app()
    with TestClient(app) as client, client.stream("GET", f"/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        events = _events_from_sse("".join(response.iter_text()))

    assert [event["event_type"] for event in events] == [
        "run_started", "message_started", "message_content", "run_completed",
    ]
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert {event["run_id"] for event in events} == {run_id}
    assert all(event["event_id"] for event in events)
    assert all(event["contract_version"] == "v1" for event in events)


def test_cursor_stream_replays_exclusively_through_terminal() -> None:
    app, run_id = _completed_app()
    service: RunService = app.state.run_service
    events = asyncio.run(_stream_events_after(service, run_id, 2))
    assert [event["sequence"] for event in events] == [3, 4]
    assert events[-1]["event_type"] == EventType.RUN_COMPLETED


def test_cursor_stream_observes_an_event_persisted_during_catch_up() -> None:
    runs, events = RunStore(), RunEventStore()
    service = RunService(MockAgentAdapter(), run_repository=runs, run_event_repository=events)
    service._lifecycle.create_run("race")
    service._lifecycle.start("race")

    async def observe() -> list[str]:
        stream = _run_event_stream(_ConnectedRequest(), service, "race")
        first = await anext(stream)
        events.append(RunEvent(
            event_id=str(uuid4()), run_id="race", event_type=EventType.MESSAGE_STARTED,
            payload={"message_id": "message-race", "role": "assistant"},
        ))
        second = await anext(stream)
        await stream.aclose()
        return _events_from_sse(first + second)

    observed = asyncio.run(observe())
    assert [event["sequence"] for event in observed] == [1, 2]


def test_ahead_cursor_is_rejected_before_opening_a_stuck_stream() -> None:
    app, run_id = _completed_app()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(run_service=app.state.run_service)))
    response = asyncio.run(stream_run(request, run_id, after_sequence=99))
    assert response.status_code == 409
    assert json.loads(response.body)["error_code"] == "invalid_resume_cursor"


def test_late_subscriptions_receive_failed_and_cancelled_terminal_facts() -> None:
    failed_app, failed_run = _completed_app(fail=True)
    with TestClient(failed_app) as client, client.stream("GET", f"/runs/{failed_run}/stream") as response:
        failed = _events_from_sse("".join(response.iter_text()))
    assert failed[-1]["event_type"] == EventType.RUN_FAILED

    app, cancelled_run = _cancelled_app()
    with TestClient(app) as client, client.stream("GET", f"/runs/{cancelled_run}/stream") as response:
        cancelled = _events_from_sse("".join(response.iter_text()))
    assert [event["event_type"] for event in cancelled] == [
        EventType.RUN_STARTED, EventType.MESSAGE_STARTED,
        EventType.RUN_CANCEL_REQUESTED, EventType.RUN_CANCELLED,
    ]


def test_stream_unknown_run_rejects_before_opening_an_sse_connection() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/runs/missing/stream")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error_code"] == "run_not_found"


def test_two_subscribers_observe_the_same_persisted_envelope_without_mutating_run() -> None:
    app, run_id = _completed_app()
    with TestClient(app) as client:
        first = _events_from_sse(client.get(f"/runs/{run_id}/stream").text)
        second = _events_from_sse(client.get(f"/runs/{run_id}/stream").text)
        status = client.get(f"/runs/{run_id}").json()["status"]
    assert first == second
    assert status == "completed"


def test_sse_and_cursor_replay_expose_the_same_persisted_facts() -> None:
    app, run_id = _completed_app()
    with TestClient(app) as client:
        live = _events_from_sse(client.get(f"/runs/{run_id}/stream").text)
        replay = client.get(f"/runs/{run_id}/events?after_sequence=0").json()
        later = client.get(f"/runs/{run_id}/events?after_sequence=2").json()
    assert [
        (event["event_id"], event["sequence"], event["event_type"], event["payload"])
        for event in live
    ] == [
        (event["event_id"], event["sequence"], event["event_type"], event["payload"])
        for event in replay
    ]
    assert [event["sequence"] for event in later] == [3, 4]


def test_partial_content_snapshots_have_sse_replay_and_subscriber_parity() -> None:
    app = create_app()
    service = RunService(
        MockAgentAdapter(content_snapshots=("Hel", "Hello", "Hello 🙂")),
        run_repository=RunStore(),
        run_event_repository=RunEventStore(),
    )
    app.state.run_service = service
    result = asyncio.run(service.start_run(RunRequest(prompt="hello")))
    with TestClient(app) as client:
        first = _events_from_sse(client.get(f"/runs/{result.run_id}/stream").text)
        second = _events_from_sse(client.get(f"/runs/{result.run_id}/stream").text)
        replay = client.get(f"/runs/{result.run_id}/events").json()
    assert first == second == replay
    content = [event for event in replay if event["event_type"] == EventType.MESSAGE_CONTENT]
    assert [event["payload"]["content"] for event in content] == ["Hel", "Hello", "Hello 🙂"]
    assert len({event["event_id"] for event in replay}) == len(replay)
    assert [event["sequence"] for event in replay] == list(range(1, len(replay) + 1))


def test_failed_and_cancelled_sse_match_replay_of_persisted_terminal_facts() -> None:
    for app, run_id, status in (*_completed_app(fail=True), "failed"), (*_cancelled_app(), "cancelled"):
        with TestClient(app) as client:
            live = _events_from_sse(client.get(f"/runs/{run_id}/stream").text)
            replay = client.get(f"/runs/{run_id}/events").json()
            snapshot = client.get(f"/runs/{run_id}").json()
        def semantic(event):
            return event["event_id"], event["sequence"], event["event_type"], event["payload"]

        assert [semantic(event) for event in live] == [semantic(event) for event in replay]
        assert replay[-1]["event_type"] == f"run_{status}"
        assert snapshot["status"] == status


def test_active_replay_returns_only_persisted_facts_without_terminal_synthesis() -> None:
    runs, events = RunStore(), RunEventStore()
    service = RunService(MockAgentAdapter(), run_repository=runs, run_event_repository=events)
    service._lifecycle.create_run("active")
    service._lifecycle.start("active")
    assert service.get_run("active").status.value == "running"
    replay = service.get_run_events("active")
    assert [event.event_type for event in replay] == [EventType.RUN_STARTED]
    assert not any(event.event_type in {
        EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.RUN_CANCELLED,
    } for event in replay)


def test_replay_does_not_synthesize_a_missing_fact_from_terminal_status() -> None:
    runs, events = RunStore(), RunEventStore()
    runs.create("crash-gap")
    runs.update_status("crash-gap", RunStatus.COMPLETED)
    service = RunService(MockAgentAdapter(), run_repository=runs, run_event_repository=events)
    assert service.get_run("crash-gap").status.value == "completed"
    assert service.get_run_events("crash-gap") == []


def test_post_run_returns_identity_before_the_stream_is_requested() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/runs", json={"prompt": "hello"})
        body = response.json()
    assert response.status_code == 202
    assert body["run_id"]
    assert body["conversation_id"] is None
    assert body["source_user_message_id"] is None
    assert body["assistant_message_id"] is None


# ============================================================
# BEGIN: Charter B - True Incremental Streaming End to End
# ============================================================


# A harness deadlock must fail in seconds, not hang until CI gives up.
_STEP_TIMEOUT = 10.0


class _StreamingModelProvider:
    """A provider that emits one delta per ``asyncio.sleep``, on demand.

    The gaps are the point: each ``next()`` blocks until the test releases it,
    so a consumer that can only act after the final delta deadlocks or is
    visibly late. That makes buffering detectable rather than merely unlikely.
    """

    def __init__(self, deltas: list[str], capabilities: ModelCapabilities | None = None) -> None:
        self._deltas = deltas
        self._release = asyncio.Event()
        self._ready = asyncio.Event()
        self._emitted = 0
        self._capabilities = capabilities or ModelCapabilities(chat=True, streaming=True)

    def release_next(self) -> None:
        """Permit exactly one more delta to be handed downstream."""
        self._release.set()

    async def wait_until_ready(self) -> None:
        """Block until the provider is parked waiting for a release.

        Releasing before this point is a lost wakeup: the provider clears its
        gate on the way in, so a pre-set flag would be wiped and the run would
        deadlock on the first delta.
        """
        await asyncio.wait_for(self._ready.wait(), timeout=_STEP_TIMEOUT)

    @property
    def pending(self) -> int:
        """Deltas not yet emitted.

        Counted at emission, not at generator resume: a counter that only moves
        when the consumer asks for the next delta never reaches zero, because
        the final ``yield`` is never resumed.
        """
        return len(self._deltas) - self._emitted

    @property
    def emitted(self) -> int:
        return self._emitted

    def name(self) -> str:
        return "streaming-test"

    def get_capabilities(self) -> ModelCapabilities:
        return self._capabilities

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        return ModelResponse(content="".join(self._deltas), model_id=model_name or "")

    async def stream(self, request: ModelRequest, *, model_name: str | None = None) -> AsyncIterator[str]:
        for delta in self._deltas:
            self._ready.clear()
            self._ready.set()
            await self._release.wait()
            self._release.clear()
            self._emitted += 1
            yield delta

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider_name=self.name(),
            model_id="stream-model",
            display_name="Stream Model",
            capabilities=self._capabilities,
        )

    async def health(self) -> ModelProviderHealth:
        return ModelProviderHealth(status="healthy")


def _native_streaming_app(
    provider: "_StreamingModelProvider",
) -> tuple[object, RunService, RunEventStore]:
    """Wire the real NativeAgent + NativeRuntime streaming path to a test provider."""
    app = create_app()
    store = RunEventStore()
    service = RunService(
        NativeAgentAdapter(NativeRuntime(), provider),
        run_repository=RunStore(),
        run_event_repository=store,
    )
    app.state.run_service = service
    return app, service, store


def test_declared_streaming_capability_reaches_the_provider_adapter() -> None:
    """The adapter is what answers "can this model stream?".

    The runtime branches on ``get_capabilities().streaming``. A factory that
    drops the configured model's declared capabilities makes every configured
    model look chat-only, and a streaming run silently completes in one shot.
    """
    provider = ConfiguredModelProviderFactory(
        installed_provider_ids=frozenset({"local"}), default_endpoint="http://localhost:11434/v1"
    ).create(
        provider_id="local",
        endpoint="http://localhost:11434/v1",
        model_name="qwen2.5-coder:7b",
        credential=None,
        capabilities=ModelCapabilities(chat=True, streaming=True),
    )
    assert provider.get_capabilities().streaming is True


def test_a_configured_model_without_declared_capabilities_stays_chat_only() -> None:
    """Conservative default is preserved when nothing is declared."""
    provider = ConfiguredModelProviderFactory(
        installed_provider_ids=frozenset({"local"}), default_endpoint="http://localhost:11434/v1"
    ).create(
        provider_id="local",
        endpoint="http://localhost:11434/v1",
        model_name="qwen2.5-coder:7b",
        credential=None,
    )
    assert provider.get_capabilities().streaming is False
    assert provider.get_capabilities().chat is True


async def _drain(stream) -> AsyncIterator[dict[str, object]]:
    """Yield every SSE event a consumer can observe from ``stream``."""
    async for chunk in stream:
        for event in _events_from_sse(chunk):
            yield event


def test_partial_content_reaches_an_sse_consumer_before_the_provider_finishes() -> None:
    """A buffered stream is a failure, not a slow stream.

    Each delta is released only after the consumer has observed the previous
    one, so "the provider still had deltas to emit" is an asserted fact rather
    than a timing guess. A run that buffered until completion, or that appended
    instead of replacing, cannot satisfy both assertions below.
    """
    deltas = ["Hel", "lo ", "world"]
    provider = _StreamingModelProvider(deltas)
    _app, service, store = _native_streaming_app(provider)

    async def scenario() -> list[tuple[str, int]]:
        received: list[tuple[str, int]] = []
        observed = asyncio.Event()

        async def consume() -> None:
            stream = _run_event_stream(_ConnectedRequest(), service, prepared.run_id)
            async for event in _drain(stream):
                if event["event_type"] == EventType.MESSAGE_CONTENT:
                    received.append((str(event["payload"]["content"]), provider.pending))
                    observed.set()

        prepared = service.prepare_run(RunRequest(prompt="hi"))
        consumer = asyncio.create_task(consume())
        runner = asyncio.create_task(service.execute_prepared_run(prepared))
        for _ in deltas:
            await provider.wait_until_ready()
            provider.release_next()
            await asyncio.wait_for(observed.wait(), timeout=_STEP_TIMEOUT)
            observed.clear()
        await asyncio.wait_for(runner, timeout=_STEP_TIMEOUT)
        await asyncio.wait_for(consumer, timeout=_STEP_TIMEOUT)
        return received

    received = asyncio.run(scenario())

    # One content event per delta, each replacing the previous snapshot.
    assert [content for content, _ in received] == ["Hel", "Hello ", "Hello world"]
    # Deltas still pending when each event was received. A buffered
    # implementation would report 0 for all three.
    assert [pending for _, pending in received] == [2, 1, 0]
    assert all(len(a[0]) < len(b[0]) for a, b in zip(received, received[1:], strict=False))


def test_the_durable_event_log_grows_before_the_run_completes() -> None:
    """Durable events are the refresh/replay source of truth, so they must grow."""
    deltas = ["Hel", "lo ", "world"]
    provider = _StreamingModelProvider(deltas)
    _app, service, store = _native_streaming_app(provider)

    async def scenario() -> tuple[str, list[str]]:
        seen: list[str] = []
        observed = asyncio.Event()

        async def consume() -> None:
            stream = _run_event_stream(_ConnectedRequest(), service, prepared.run_id)
            async for event in _drain(stream):
                if event["event_type"] == EventType.MESSAGE_CONTENT:
                    seen.append(str(event["payload"]["content"]))
                    observed.set()

        prepared = service.prepare_run(RunRequest(prompt="hi"))
        consumer = asyncio.create_task(consume())
        runner = asyncio.create_task(service.execute_prepared_run(prepared))
        for _ in deltas:
            await provider.wait_until_ready()
            provider.release_next()
            await asyncio.wait_for(observed.wait(), timeout=_STEP_TIMEOUT)
            observed.clear()
        await asyncio.wait_for(runner, timeout=_STEP_TIMEOUT)
        await asyncio.wait_for(consumer, timeout=_STEP_TIMEOUT)
        return prepared.run_id, seen

    run_id, seen = asyncio.run(scenario())

    assert seen == ["Hel", "Hello ", "Hello world"]
    # Sequence numbers stay dense and monotonic, so after_sequence replay from a
    # cursor can never skip or reorder a partial update.
    sequences = [
        event.sequence
        for event in store.get_events(run_id)
        if event.event_type == EventType.MESSAGE_CONTENT
    ]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == 3


def test_a_non_streaming_model_still_completes_in_one_persisted_snapshot() -> None:
    """Final-only compatibility: streaming=False must not be forced on."""
    provider = _StreamingModelProvider(["one ", "shot"])
    provider._capabilities = ModelCapabilities(chat=True, streaming=False)
    _app, service, store = _native_streaming_app(provider)

    async def scenario() -> list[dict[str, object]]:
        prepared = service.prepare_run(RunRequest(prompt="hi"))
        await asyncio.wait_for(
            service.execute_prepared_run(prepared), timeout=_STEP_TIMEOUT
        )
        chunks = [
            chunk
            async for chunk in _run_event_stream(
                _ConnectedRequest(), service, prepared.run_id
            )
        ]
        return _events_from_sse("".join(chunks))

    events = asyncio.run(scenario())
    contents = [e for e in events if e["event_type"] == EventType.MESSAGE_CONTENT]
    assert len(contents) == 1
    assert contents[0]["payload"]["content"] == "one shot"


def test_a_stream_failure_after_partial_content_keeps_the_partial_and_the_specific_code() -> None:
    """Defect G must survive streaming: the code is specific and content is kept."""

    class _FailingAfterFirst(_StreamingModelProvider):
        async def stream(self, request: ModelRequest, *, model_name: str | None = None) -> AsyncIterator[str]:
            yield "partial answer"
            raise ModelProviderError("gone", safe_code=FailureCode.PROVIDER_RATE_LIMITED)

    provider = _FailingAfterFirst(["unused"])
    _app, service, store = _native_streaming_app(provider)

    async def scenario() -> list[dict[str, object]]:
        prepared = service.prepare_run(RunRequest(prompt="hi"))
        await asyncio.wait_for(
            service.execute_prepared_run(prepared), timeout=_STEP_TIMEOUT
        )
        chunks = [
            chunk
            async for chunk in _run_event_stream(
                _ConnectedRequest(), service, prepared.run_id
            )
        ]
        return _events_from_sse("".join(chunks))

    events = asyncio.run(scenario())
    contents = [e for e in events if e["event_type"] == EventType.MESSAGE_CONTENT]
    failures = [e for e in events if e["event_type"] == EventType.RUN_FAILED]
    assert contents[0]["payload"]["content"] == "partial answer"
    assert failures[0]["payload"]["error_code"] == FailureCode.PROVIDER_RATE_LIMITED


# ============================================================
# END: Charter B - True Incremental Streaming End to End
# ============================================================
