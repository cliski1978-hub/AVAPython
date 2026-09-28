"""Phase 5.25 SSE transport tests over persisted AVA run events."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.api.app import create_app
from ava.api.routes.runs import _run_event_stream, stream_run
from ava.contracts.events import EventType, RunEvent
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
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
