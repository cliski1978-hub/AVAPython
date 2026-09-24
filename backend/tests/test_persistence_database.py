"""SQLite database lifecycle and serialization tests (Step 4.6).

Covers the ``SqliteDatabase`` lifecycle — lazy in-memory schema bootstrap,
explicit transaction commit/rollback, dispose semantics — plus the shared
serialization helpers (UTC timestamps, deterministic JSON, execution
selection round-trip) that the relational adapters build on.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.models import ModelHostingMode
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import (
    dump_execution_selection,
    dump_json,
    load_execution_selection,
    load_json,
    parse_utc,
    row_to_run_event,
    to_utc_iso,
)

_SQLITE_TABLES = "SELECT name FROM sqlite_master WHERE type = 'table'"

# ============================================================
# BEGIN: Database lifecycle
# ============================================================


def test_schema_is_bootstrapped_on_first_connect() -> None:
    """A fresh database runs the initial migration when first connected."""
    database = SqliteDatabase(":memory:")
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute(_SQLITE_TABLES)}
    assert {
        "runs",
        "run_events",
        "conversations",
        "messages",
        "documents",
        "document_revisions",
        "attachments",
    } <= tables
    assert "ava_schema_migrations" in tables
    database.dispose()


def test_schema_bootstrap_is_idempotent() -> None:
    """ensure_schema() may run repeatedly without error or schema churn."""
    database = SqliteDatabase(":memory:")
    database.ensure_schema()
    database.ensure_schema()
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute(_SQLITE_TABLES)}
    assert {
        "runs",
        "run_events",
        "conversations",
        "messages",
        "documents",
        "document_revisions",
        "attachments",
    } <= tables
    assert connection.execute("SELECT COUNT(*) FROM ava_schema_migrations").fetchone()[0] == 3
    database.dispose()


def test_terminal_event_unique_index_guards_run_events() -> None:
    """The database enforces at most one terminal event per run."""
    import sqlite3

    database = SqliteDatabase(":memory:")
    insert = (
        "INSERT INTO run_events (event_id, run_id, event_type, seq, \"timestamp\", payload, contract_version) "
        "VALUES (?, ?, ?, ?, '2026-01-01T00:00:00+00:00', '{}', '1.0')"
    )
    with database.connect() as connection:
        connection.execute(insert, ("e1", "r", "run_completed", 1))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, ("e2", "r", "run_failed", 2))
        # A non-terminal duplicate is still allowed for a different event id.
        connection.execute(insert, ("e3", "r", "run_started", 3))
    database.dispose()


def test_transaction_commits_writes_on_normal_exit() -> None:
    database = SqliteDatabase(":memory:")
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO conversations (conversation_id, title, created_at, updated_at) "
            "VALUES ('c1', 'T', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
    database.dispose()


def test_transaction_rolls_back_on_error() -> None:
    database = SqliteDatabase(":memory:")
    with pytest.raises(RuntimeError), database.transaction() as connection:
        connection.execute(
            "INSERT INTO conversations (conversation_id, title, created_at, updated_at) "
            "VALUES ('c1', 'T', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        raise RuntimeError("boom")
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
    database.dispose()


def test_dispose_drops_in_memory_state() -> None:
    """Closing an in-memory database discards its state; a new connect restarts empty."""
    database = SqliteDatabase(":memory:")
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO conversations (conversation_id, title, created_at, updated_at) "
            "VALUES ('c1', 'T', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    database.dispose()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
    database.dispose()


def test_auto_migrate_flag_defers_schema_until_ensure_schema() -> None:
    """auto_migrate=False defers schema creation to an explicit ensure_schema()."""
    database = SqliteDatabase(":memory:", auto_migrate=False)
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute(_SQLITE_TABLES)}
    assert "runs" not in tables
    assert "ava_schema_migrations" not in tables
    database.ensure_schema()
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute(_SQLITE_TABLES)}
    assert "runs" in tables
    assert "ava_schema_migrations" in tables
    database.dispose()


def test_translate_database_error_maps_duplicates_to_value_error() -> None:
    exc = _make_duplicate_integrity_error()
    translated = translate_database_error(exc, entity="Run", key="run-1")
    assert isinstance(translated, ValueError)
    assert str(translated) == "Run already exists: run-1"


def test_translate_database_error_maps_other_failures_to_persistence_error() -> None:
    from ava.infrastructure.persistence.errors import PersistenceError

    translated = translate_database_error(_make_operational_error(), entity="Run", key="run-1")
    assert isinstance(translated, PersistenceError)
    assert isinstance(translated, Exception)


def _make_duplicate_integrity_error() -> Exception:
    import sqlite3

    database = SqliteDatabase(":memory:")
    with database.transaction() as connection, pytest.raises(sqlite3.IntegrityError) as exc_info:
        connection.execute(
            "INSERT INTO runs (run_id, status, created_at, updated_at) "
            "VALUES ('r', 'pending', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO runs (run_id, status, created_at, updated_at) "
            "VALUES ('r', 'pending', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    database.dispose()
    return exc_info.value


def _make_operational_error() -> Exception:
    import sqlite3

    database = SqliteDatabase(":memory:")
    with database.connect() as connection, pytest.raises(sqlite3.OperationalError) as exc_info:
        connection.execute("SELECT * FROM no_such_table")
    database.dispose()
    return exc_info.value


# ============================================================
# END: Database lifecycle
# ============================================================


# ============================================================
# BEGIN: Timestamp serialization
# ============================================================


def test_timestamp_round_trip_preserves_aware_utc() -> None:
    original = datetime.now(UTC).replace(microsecond=123456)
    restored = parse_utc(to_utc_iso(original))
    assert restored == original
    assert restored.tzinfo is not None
    assert restored.utcoffset() == timedelta(0)


def test_naive_timestamp_is_treated_as_utc() -> None:
    restored = parse_utc("2026-01-01T12:00:00")
    assert restored == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_non_utc_offset_is_normalized_to_utc() -> None:
    restored = parse_utc("2026-01-01T12:00:00+02:00")
    assert restored == datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


# ============================================================
# END: Timestamp serialization
# ============================================================


# ============================================================
# BEGIN: JSON serialization
# ============================================================


def test_deterministic_json_serialization() -> None:
    first = dump_json({"b": 2, "a": [1, {"x": True}], "c": None})
    second = dump_json({"c": None, "a": [1, {"x": True}], "b": 2})
    assert first == second
    assert load_json(first) == {"a": [1, {"x": True}], "b": 2, "c": None}
    assert load_json(second) == {"a": [1, {"x": True}], "b": 2, "c": None}


def test_execution_selection_round_trip() -> None:
    selection = RunExecutionSelection(
        runtime_id="runtime-a",
        model_provider_id="provider-a",
        model_id="model-a",
        hosting_mode=ModelHostingMode.LOCAL,
    )
    stored = dump_execution_selection(selection)
    assert stored is not None
    restored = load_execution_selection(stored)
    assert restored == selection
    assert restored.hosting_mode == ModelHostingMode.LOCAL


def test_execution_selection_none_round_trip() -> None:
    assert dump_execution_selection(None) is None
    assert load_execution_selection(None) is None


# ============================================================
# END: JSON serialization
# ============================================================


# ============================================================
# BEGIN: Row mapping
# ============================================================


def test_event_row_mapping_restores_full_run_event() -> None:
    database = SqliteDatabase(":memory:")
    original = RunEvent(
        event_id="e1",
        run_id="r1",
        event_type=EventType.MESSAGE_CONTENT,
        payload={"content": "hello", "ordinal": 2},
    )
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO run_events (event_id, run_id, event_type, seq, \"timestamp\", payload, contract_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                original.event_id,
                original.run_id,
                original.event_type.value,
                1,
                to_utc_iso(original.timestamp),
                dump_json(original.payload),
                original.contract_version,
            ),
        )
        database_row = connection.execute(
            "SELECT event_id, run_id, event_type, seq, \"timestamp\", payload, contract_version "
            "FROM run_events WHERE event_id = 'e1'"
        ).fetchone()
    restored = row_to_run_event(database_row)
    assert restored == original
    assert restored.timestamp == original.timestamp
    database.dispose()


# ============================================================
# END: Row mapping
# ============================================================