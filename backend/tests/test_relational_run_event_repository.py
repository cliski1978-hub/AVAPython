"""Relational run-event repository tests (Step 4.6).

Mirror the in-memory ``RunEventStore`` semantics against the SQLite-backed
``RelationalRunEventRepository``: append order via an explicit sequence,
per-run isolation, the single-terminal-event idempotent invariant (backed by a
partial unique index), and payload/timestamp round-tripping.
"""

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
    assert event_repository.get_latest("r") == latest


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
    assert restored == event
    assert restored.payload == payload


def test_default_payload_and_timestamp_round_trip(
    repository: tuple[RelationalRunEventRepository, SqliteDatabase],
) -> None:
    event_repository, _ = repository
    event = RunEvent(event_id="e1", run_id="r", event_type=EventType.RUN_STARTED)
    event_repository.append(event)
    restored = event_repository.get_events("r")[0]
    assert restored == event
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