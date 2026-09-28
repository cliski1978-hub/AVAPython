"""Relational run-event repository tests (Step 4.6).

Mirror the in-memory ``RunEventStore`` semantics against the SQLite-backed
``RelationalRunEventRepository``: append order via an explicit sequence,
per-run isolation, the single-terminal-event idempotent invariant (backed by a
partial unique index), and payload/timestamp round-tripping.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from ava.contracts.events import EventType, RunEvent
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import RelationalRunEventRepository


@pytest.fixture()
def repository() -> tuple[RelationalRunEventRepository, SqliteDatabase]:
    database = SqliteDatabase(":memory:")
    yield RelationalRunEventRepository(database=database), database
    database.dispose()


def _event(event_id: str, run_id: str, event_type: EventType, **kwargs: object) -> RunEvent:
    return RunEvent(event_id=event_id, run_id=run_id, event_type=event_type, **kwargs)


# ============================================================
# BEGIN: Append ordering
# ============================================================


def test_append_preserves_original_order(repository: tuple[RelationalRunEventRepository, SqliteDatabase]) -> None:
    event_repository, _ = repository
    events = [
        _event("e1", "r", EventType.RUN_STARTED),
        _event("e2", "r", EventType.MESSAGE_STARTED),
        _event("e3", "r", EventType.MESSAGE_CONTENT, payload={"content": "hi"}),
        _event("e4", "r", EventType.RUN_COMPLETED),
    ]
    for event in events:
        event_repository.append(event)
    assert [e.event_id for e in event_repository.get_events("r")] == ["e1", "e2", "e3", "e4"]


def test_get_latest_returns_most_recent(repository: tuple[RelationalRunEventRepository, SqliteDatabase]) -> None:
    event_repository, _ = repository
    event_repository.append(_event("e1", "r", EventType.RUN_STARTED))
    latest = _event("e2", "r", EventType.MESSAGE_STARTED)
    event_repository.append(latest)
    assert event_repository.get_latest("r") == latest.model_copy(update={"sequence": 2})


def test_unknown_run_yields_empty_results(repository: tuple[RelationalRunEventRepository, SqliteDatabase]) -> None:
    event_repository, _ = repository
    assert event_repository.get_events("ghost") == []
    assert event_repository.get_latest("ghost") is None


def test_events_are_isolated_per_run(repository: tuple[RelationalRunEventRepository, SqliteDatabase]) -> None:
    event_repository, _ = repository
    event_repository.append(_event("e1", "a", EventType.RUN_STARTED))
    event_repository.append(_event("e2", "b", EventType.RUN_STARTED))
    assert [e.event_id for e in event_repository.get_events("a")] == ["e1"]
    assert [e.event_id for e in event_repository.get_events("b")] == ["e2"]


def test_replay_cursor_is_exclusive_and_sequence_orders_timestamp_ties(
    repository: tuple[RelationalRunEventRepository, SqliteDatabase],
) -> None:
    event_repository, _ = repository
    timestamp = datetime(2026, 9, 27, tzinfo=UTC)
    for number in range(1, 6):
        event_repository.append(_event(f"e{number}", "r", EventType.MESSAGE_STARTED, timestamp=timestamp))
    assert [event.sequence for event in event_repository.list_after_sequence("r", 0)] == [1, 2, 3, 4, 5]
    assert [event.sequence for event in event_repository.list_after_sequence("r", 2)] == [3, 4, 5]
    assert [event.sequence for event in event_repository.list_after_sequence("r", 5)] == []
    assert event_repository.list_after_sequence("r", 99) == []


def test_sequence_continues_after_file_backed_database_restart(tmp_path) -> None:
    path = str(tmp_path / "events.sqlite3")
    database = SqliteDatabase(path)
    repository = RelationalRunEventRepository(database=database)
    for number in range(1, 4):
        repository.append(_event(f"e{number}", "r", EventType.MESSAGE_STARTED))
    database.dispose()
    reopened = SqliteDatabase(path)
    repository = RelationalRunEventRepository(database=reopened)
    repository.append(_event("e4", "r", EventType.MESSAGE_CONTENT, payload={"content": "four"}))
    all_events = repository.list_after_sequence("r", 0)
    events = repository.list_after_sequence("r", 1)
    assert [(event.event_id, event.sequence) for event in all_events] == [
        ("e1", 1), ("e2", 2), ("e3", 3), ("e4", 4),
    ]
    assert [(event.event_id, event.sequence) for event in events] == [("e2", 2), ("e3", 3), ("e4", 4)]
    assert repository.list_after_sequence("r", 4) == []
    assert all_events[-1].payload == {"content": "four"}
    reopened.dispose()


def test_concurrent_same_run_appends_allocate_contiguous_sequences(tmp_path) -> None:
    database = SqliteDatabase(str(tmp_path / "concurrent.sqlite3"))
    repository = RelationalRunEventRepository(database=database)

    def append(number: int) -> None:
        repository.append(_event(f"same-{number}", "same", EventType.MESSAGE_STARTED))

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(20)))
    events = repository.get_events("same")
    assert len(events) == 20
    assert {event.event_id for event in events} == {f"same-{number}" for number in range(20)}
    assert [event.sequence for event in events] == list(range(1, 21))
    database.dispose()


def test_concurrent_separate_runs_keep_independent_sequences(tmp_path) -> None:
    database = SqliteDatabase(str(tmp_path / "concurrent-runs.sqlite3"))
    repository = RelationalRunEventRepository(database=database)

    def append(run_id: str, number: int) -> None:
        repository.append(_event(f"{run_id}-{number}", run_id, EventType.MESSAGE_STARTED))

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(append, run_id, number) for run_id in ("a", "b") for number in range(10)]
        for future in futures:
            future.result()
    assert [event.sequence for event in repository.get_events("a")] == list(range(1, 11))
    assert [event.sequence for event in repository.get_events("b")] == list(range(1, 11))
    database.dispose()


# ============================================================
# END: Append ordering
# ============================================================


# ============================================================
# BEGIN: Terminal-event invariant
# ============================================================


def test_second_terminal_event_for_terminal_run_is_ignored(
    repository: tuple[RelationalRunEventRepository, SqliteDatabase],
) -> None:
    event_repository, _ = repository
    event_repository.append(_event("e1", "r", EventType.RUN_STARTED))
    event_repository.append(_event("e2", "r", EventType.RUN_COMPLETED))
    ignored = _event("e3", "r", EventType.RUN_FAILED)
    returned = event_repository.append(ignored)
    assert returned == ignored
    assert [e.event_id for e in event_repository.get_events("r")] == ["e1", "e2"]
    assert event_repository.get_latest("r").event_type == EventType.RUN_COMPLETED


@pytest.mark.parametrize(
    "terminal",
    [EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED],
)
def test_each_terminal_type_ends_the_run(repository, terminal) -> None:
    event_repository, _ = repository
    event_repository.append(_event("e1", "r", terminal))
    event_repository.append(
        _event(
            "e2",
            "r",
            next(t for t in (EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED) if t != terminal),
        )
    )
    assert [e.event_id for e in event_repository.get_events("r")] == ["e1"]


def test_non_terminal_event_after_terminal_is_appended(
    repository: tuple[RelationalRunEventRepository, SqliteDatabase],
) -> None:
    """Parity with the in-memory store: only terminal-after-terminal is stopped."""
    event_repository, _ = repository
    event_repository.append(_event("e1", "r", EventType.RUN_COMPLETED))
    event_repository.append(_event("e2", "r", EventType.MESSAGE_CONTENT))
    assert [e.event_id for e in event_repository.get_events("r")] == ["e1", "e2"]


# ============================================================
# END: Terminal-event invariant
# ============================================================


# ============================================================
# BEGIN: Payload / timestamp round-tripping
# ============================================================


def test_payload_round_trips_nested_json(repository: tuple[RelationalRunEventRepository, SqliteDatabase]) -> None:
    event_repository, _ = repository
    payload: dict[str, object] = {
        "content": "préservé ✓",
        "nested": {"list": [1, 2, 3], "flag": True, "nil": None},
        "ordinal": 42,
    }
    event = _event("e1", "r", EventType.MESSAGE_CONTENT, payload=payload)
    event_repository.append(event)
    restored = event_repository.get_events("r")[0]
    assert restored == event.model_copy(update={"sequence": 1})
    assert restored.payload == payload


def test_default_payload_and_timestamp_round_trip(
    repository: tuple[RelationalRunEventRepository, SqliteDatabase],
) -> None:
    event_repository, _ = repository
    event = RunEvent(event_id="e1", run_id="r", event_type=EventType.RUN_STARTED)
    event_repository.append(event)
    restored = event_repository.get_events("r")[0]
    assert restored == event.model_copy(update={"sequence": 1})
    assert restored.payload == {}
    assert restored.timestamp == event.timestamp
    assert restored.contract_version == event.contract_version


def test_explicit_timestamp_is_preserved(repository: tuple[RelationalRunEventRepository, SqliteDatabase]) -> None:
    from datetime import UTC, datetime

    event_repository, _ = repository
    explicit = datetime(2026, 9, 18, 12, 30, 15, 123456, tzinfo=UTC)
    event = RunEvent(
        event_id="e1",
        run_id="r",
        event_type=EventType.TOOL_STARTED,
        timestamp=explicit,
    )
    event_repository.append(event)
    restored = event_repository.get_events("r")[0]
    assert restored.timestamp == explicit


def test_duplicate_non_terminal_event_id_raises_value_error(
    repository: tuple[RelationalRunEventRepository, SqliteDatabase],
) -> None:
    event_repository, _ = repository
    event_repository.append(_event("e1", "r", EventType.RUN_STARTED))
    with pytest.raises(ValueError, match="Run event already exists: e1"):
        event_repository.append(_event("e1", "r", EventType.MESSAGE_STARTED))


# ============================================================
# END: Payload / timestamp round-tripping
# ============================================================
