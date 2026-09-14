"""Run / event lifecycle tests.

Cover the sprint's in-memory run and event stores plus the normalized
lifecycle that ``RunService`` produces:

    Successful:   run_started → message_started → message_content → run_completed
    Cancelled:    run_started → run_cancelled (never message/completion events)
    Failed:       run_started → run_failed

Plus isolation between runs and snapshot retrieval semantics. No persistence,
streaming, SSE, or queue is introduced in this sprint.
"""

import asyncio
from uuid import UUID

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.contracts.events import EventType, RunEvent
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore

# ============================================================
# BEGIN: Run Store Unit Tests
# ============================================================


def test_run_store_create_and_get_record() -> None:
    """create() should produce a pending record retrievable by run id."""
    store = RunStore()
    record = store.create("run-1")

    assert record.run_id == "run-1"
    assert record.status == RunStatus.PENDING
    stored = store.get("run-1")
    assert stored is not None
    assert stored == record


def test_run_store_rejects_duplicate_create() -> None:
    """A run id must be unique; duplicate creation must fail loudly."""
    store = RunStore()
    store.create("run-1")

    try:
        store.create("run-1")
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("duplicate create did not raise ValueError")


def test_run_store_update_status_refreshes_record() -> None:
    """update_status() should switch status and advance updated_at."""
    store = RunStore()
    store.create("run-1")

    updated = store.update_status("run-1", RunStatus.COMPLETED)

    assert updated is not None
    assert updated.status == RunStatus.COMPLETED
    assert updated.updated_at >= updated.created_at
    assert store.get("run-1") is not None


def test_run_store_update_unknown_run_is_none() -> None:
    """Updating an unknown run should return None without error."""
    store = RunStore()
    assert store.update_status("ghost", RunStatus.COMPLETED) is None


def test_run_store_list_and_clear() -> None:
    """list_run_ids() returns insertion order; clear() empties the store."""
    store = RunStore()
    for run_id in ("a", "b", "c"):
        store.create(run_id)

    assert store.list_run_ids() == ["a", "b", "c"]

    store.clear()
    assert store.list_run_ids() == []


def test_run_store_records_are_immutable_snapshots() -> None:
    """A returned record must be a frozen snapshot, not live state."""
    store = RunStore()
    record = store.create("run-1")
    assert record.status == RunStatus.PENDING

    store.update_status("run-1", RunStatus.FAILED)
    # The earlier snapshot is unchanged.
    assert record.status == RunStatus.PENDING


# ============================================================
# END: Run Store Unit Tests
# ============================================================


# ============================================================
# BEGIN: Run Event Store Unit Tests
# ============================================================


def _event(run_id: str, event_type: EventType) -> RunEvent:
    return RunEvent(event_id="e", run_id=run_id, event_type=event_type)


def test_run_event_store_appends_in_order() -> None:
    """Appended events must be retrievable in original order."""
    store = RunEventStore()
    store.append(_event("run-1", EventType.RUN_STARTED))
    store.append(_event("run-1", EventType.RUN_COMPLETED))

    events = store.get_events("run-1")
    assert [e.event_type for e in events] == [
        EventType.RUN_STARTED,
        EventType.RUN_COMPLETED,
    ]


def test_run_event_store_latest_and_unknown_run() -> None:
    """get_latest() returns the newest event; unknown runs are empty."""
    store = RunEventStore()
    store.append(_event("run-1", EventType.RUN_STARTED))
    latest = store.get_latest("run-1")

    assert latest is not None
    assert latest.event_type == EventType.RUN_STARTED
    assert store.get_latest("ghost") is None
    assert store.get_events("ghost") == []


def test_run_event_store_clear() -> None:
    """clear() should remove all events from all runs."""
    store = RunEventStore()
    store.append(_event("run-1", EventType.RUN_STARTED))
    store.append(_event("run-2", EventType.RUN_STARTED))

    store.clear()

    assert store.get_events("run-1") == []
    assert store.get_events("run-2") == []


def test_run_event_store_enforces_single_terminal_event() -> None:
    """A run must never receive two terminal events.

    Once a terminal event exists, a second terminal event (completion,
    cancellation, or failure) is refused so lifecycles stay deterministic.
    """
    store = RunEventStore()
    store.append(_event("run-1", EventType.RUN_CANCELLED))

    store.append(_event("run-1", EventType.RUN_COMPLETED))
    store.append(_event("run-1", EventType.RUN_FAILED))
    store.append(_event("run-1", EventType.RUN_CANCELLED))

    events = store.get_events("run-1")
    assert [e.event_type for e in events] == [EventType.RUN_CANCELLED]


# ============================================================
# END: Run Event Store Unit Tests
# ============================================================


# ============================================================
# BEGIN: Successful Lifecycle
# ============================================================


def test_successful_run_emits_full_event_lifecycle() -> None:
    """A completed run should emit the canonical success sequence."""

    async def scenario() -> None:
        store = RunEventStore()
        service = RunService(MockAgentAdapter(), event_store=store)

        response = await service.start_run(RunRequest(prompt="Hello AVA"))

        events = store.get_events(response.run_id)
        types = [e.event_type for e in events]
        assert types == [
            EventType.RUN_STARTED,
            EventType.MESSAGE_STARTED,
            EventType.MESSAGE_CONTENT,
            EventType.RUN_COMPLETED,
        ]
        assert response.status == RunStatus.COMPLETED

    asyncio.run(scenario())


def test_successful_run_carries_assistant_message_content() -> None:
    """The assistant message events must share an AVA-generated message id."""

    async def scenario() -> None:
        store = RunEventStore()
        service = RunService(MockAgentAdapter(), event_store=store)

        response = await service.start_run(RunRequest(prompt="Hello AVA"))
        events = store.get_events(response.run_id)

        message_started = events[1]
        message_content = events[2]
        message_id = message_started.payload["message_id"]
        assert message_started.payload["role"] == "assistant"
        assert message_content.payload["content"] == "AVA mock agent received: Hello AVA"
        assert message_content.payload["message_id"] == message_id
        UUID(str(message_id))

    asyncio.run(scenario())


def test_runs_are_sealed_after_completion() -> None:
    """Once completed, no further events may be produced for the run."""

    async def scenario() -> None:
        store = RunEventStore()
        service = RunService(MockAgentAdapter(), event_store=store)

        response = await service.start_run(RunRequest(prompt="Done"))
        events = store.get_events(response.run_id)
        assert events[-1].event_type == EventType.RUN_COMPLETED

        # Redundant cancellation reports the recorded outcome without events.
        cancel = await service.cancel_run(response.run_id)
        assert cancel.status == RunStatus.COMPLETED
        assert len(store.get_events(response.run_id)) == len(events)

    asyncio.run(scenario())


# ============================================================
# END: Successful Lifecycle
# ============================================================


# ============================================================
# BEGIN: Cancellation Lifecycle
# ============================================================


def test_cancelled_run_emits_run_cancelled_only() -> None:
    """A cancelled run must emit run_started then run_cancelled — nothing else."""

    async def scenario() -> None:
        store = RunEventStore()
        adapter = MockAgentAdapter(run_delay=0.1)
        service = RunService(adapter, event_store=store)

        task = asyncio.create_task(service.start_run(RunRequest(prompt="Cancel me")))
        await asyncio.sleep(0.01)
        (run_id,) = adapter.active_run_ids()

        cancel_response = await service.cancel_run(run_id)
        start_response = await task

        events = store.get_events(run_id)
        assert [e.event_type for e in events] == [
            EventType.RUN_STARTED,
            EventType.RUN_CANCELLED,
        ]
        assert cancel_response.status == RunStatus.CANCELLED
        assert start_response.status == RunStatus.CANCELLED

    asyncio.run(scenario())


def test_cancellation_wins_over_completion() -> None:
    """Cancellation during the run must prevent any message/completion events."""

    async def scenario() -> None:
        store = RunEventStore()
        adapter = MockAgentAdapter(run_delay=0.1)
        service = RunService(adapter, event_store=store)

        task = asyncio.create_task(service.start_run(RunRequest(prompt="Cancel me")))
        await asyncio.sleep(0.01)
        (run_id,) = adapter.active_run_ids()

        await service.cancel_run(run_id)
        response = await task  # the resolved start must not write a completion

        assert response.status == RunStatus.CANCELLED
        types = [e.event_type for e in store.get_events(run_id)]
        assert types == [EventType.RUN_STARTED, EventType.RUN_CANCELLED]
        # The store enforces a single terminal event: no run_completed.
        terminals = [
            t
            for t in types
            if t in {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}
        ]
        assert terminals == [EventType.RUN_CANCELLED]

    asyncio.run(scenario())


# ============================================================
# END: Cancellation Lifecycle
# ============================================================


# ============================================================
# BEGIN: Failure Lifecycle
# ============================================================


def test_failed_run_emits_run_failed_with_payload() -> None:
    """A failed run should emit run_started then run_failed with a safe payload."""

    async def scenario() -> None:
        store = RunEventStore()
        adapter = MockAgentAdapter(fail_on_prompt="force failure")
        service = RunService(adapter, event_store=store)

        response = await service.start_run(RunRequest(prompt="force failure"))

        events = store.get_events(response.run_id)
        types = [e.event_type for e in events]
        assert types == [EventType.RUN_STARTED, EventType.RUN_FAILED]
        assert response.status == RunStatus.FAILED

        payload = events[-1].payload
        assert payload["error_code"] == "agent_failed"
        assert payload["message"]
        assert payload["recoverable"] is False

    asyncio.run(scenario())


# ============================================================
# END: Failure Lifecycle
# ============================================================


# ============================================================
# BEGIN: Isolation and Retrieval
# ============================================================


def test_runs_events_remain_isolated() -> None:
    """Concurrent runs must not interleave or share events."""

    async def scenario() -> None:
        store = RunEventStore()
        service = RunService(MockAgentAdapter(), event_store=store)

        first = await service.start_run(RunRequest(prompt="one"))
        second = await service.start_run(RunRequest(prompt="two"))

        first_events = store.get_events(first.run_id)
        second_events = store.get_events(second.run_id)

        assert first.run_id != second.run_id
        assert all(e.run_id == first.run_id for e in first_events)
        assert all(e.run_id == second.run_id for e in second_events)
        assert first_events[-1].event_type == EventType.RUN_COMPLETED
        assert second_events[-1].event_type == EventType.RUN_COMPLETED

    asyncio.run(scenario())


def test_get_run_returns_none_for_unknown() -> None:
    """Snapshot retrieval must signal unknown runs with None."""

    async def scenario() -> None:
        service = RunService(MockAgentAdapter())

        await service.start_run(RunRequest(prompt="known"))

        assert service.get_run("ghost") is None
        assert service.get_run_events("ghost") is None

    asyncio.run(scenario())


def test_get_run_returns_live_snapshot() -> None:
    """Snapshot retrieval should reflect the current recorded state."""

    async def scenario() -> None:
        adapter = MockAgentAdapter()
        store = RunEventStore()
        service = RunService(adapter, event_store=store)

        response = await service.start_run(RunRequest(prompt="Snapshot"))
        run = service.get_run(response.run_id)
        events = service.get_run_events(response.run_id)

        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert [e.event_type for e in events or []] == [
            EventType.RUN_STARTED,
            EventType.MESSAGE_STARTED,
            EventType.MESSAGE_CONTENT,
            EventType.RUN_COMPLETED,
        ]

    asyncio.run(scenario())


def test_run_store_and_event_store_are_independent_stores() -> None:
    """Every run gets a store-level history through the RunService path.

    ``RunService`` coordinates both stores; concrete agent internals must
    never leak into the normalized event sequence.
    """
    run_store = RunStore()
    event_store = RunEventStore()
    agent = MockAgentAdapter()
    service = RunService(agent, run_store=run_store, event_store=event_store)

    async def scenario() -> None:
        response = await service.start_run(RunRequest(prompt="Stores"))
        events = event_store.get_events(response.run_id)
        record = run_store.get(response.run_id)
        assert record is not None
        assert record.run_id == response.run_id
        assert record.status == RunStatus.COMPLETED
        assert len(events) == 4

    asyncio.run(scenario())


# ============================================================
# END: Isolation and Retrieval
# ============================================================