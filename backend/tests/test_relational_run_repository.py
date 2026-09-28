"""Relational run repository tests (Step 4.6).

Mirror the in-memory ``RunStore`` semantics against the SQLite-backed
``RelationalRunRepository``: pending create, duplicate rejection via
``ValueError``, status/selection updates with refreshed ``updated_at``,
unknown-run ``None`` results, and aware-UTC timestamp round-tripping.
"""

from datetime import UTC, datetime

import pytest

from ava.contracts.execution import RunExecutionSelection
from ava.contracts.models import ModelHostingMode
from ava.contracts.responses import RunStatus
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import RelationalRunRepository


@pytest.fixture()
def repository() -> tuple[RelationalRunRepository, SqliteDatabase]:
    database = SqliteDatabase(":memory:")
    yield RelationalRunRepository(database=database), database
    database.dispose()


# ============================================================
# BEGIN: Create / get semantics
# ============================================================


def test_create_produces_pending_record(repository: tuple[RelationalRunRepository, SqliteDatabase]) -> None:
    run_repository, _ = repository
    record = run_repository.create("run-1")
    assert record.run_id == "run-1"
    assert record.status == RunStatus.PENDING
    assert record.execution_selection is None
    assert record.created_at.tzinfo is not None
    assert record.updated_at.tzinfo is not None


def test_get_returns_created_record(repository: tuple[RelationalRunRepository, SqliteDatabase]) -> None:
    run_repository, _ = repository
    created = run_repository.create("run-1")
    stored = run_repository.get("run-1")
    assert stored is not None
    assert stored == created


def test_create_persists_durable_conversation_and_source_message_ids(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    run_repository, _ = repository
    created = run_repository.create(
        "run-1", conversation_id="conversation-1", source_user_message_id="user-1"
    )
    assert created.conversation_id == "conversation-1"
    assert created.source_user_message_id == "user-1"
    assert created.assistant_message_id is None
    assert run_repository.get("run-1") == created


def test_get_unknown_run_is_none(repository: tuple[RelationalRunRepository, SqliteDatabase]) -> None:
    run_repository, _ = repository
    assert run_repository.get("ghost") is None


def test_duplicate_create_raises_value_error(repository: tuple[RelationalRunRepository, SqliteDatabase]) -> None:
    run_repository, _ = repository
    run_repository.create("run-1")
    with pytest.raises(ValueError, match="Run already exists: run-1"):
        run_repository.create("run-1")


# ============================================================
# END: Create / get semantics
# ============================================================


# ============================================================
# BEGIN: Update semantics
# ============================================================


def test_update_status_refreshes_record(repository: tuple[RelationalRunRepository, SqliteDatabase]) -> None:
    run_repository, _ = repository
    run_repository.create("run-1")
    updated = run_repository.update_status("run-1", RunStatus.COMPLETED)
    assert updated is not None
    assert updated.status == RunStatus.COMPLETED
    assert updated.updated_at >= updated.created_at
    assert run_repository.get("run-1") == updated


def test_update_status_unknown_run_is_none(repository: tuple[RelationalRunRepository, SqliteDatabase]) -> None:
    run_repository, _ = repository
    assert run_repository.update_status("ghost", RunStatus.COMPLETED) is None


def test_compare_and_set_status_applies_a_matching_guard(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    run_repository, _ = repository
    run_repository.create("run-1")
    updated = run_repository.compare_and_set_status(
        "run-1", expected_status=RunStatus.PENDING, status=RunStatus.RUNNING
    )
    assert updated is not None
    assert updated.status == RunStatus.RUNNING
    assert run_repository.get("run-1") == updated


def test_compare_and_set_status_refuses_a_stale_guard(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    """The guard lives in SQL, so a losing writer cannot overwrite the winner."""
    run_repository, _ = repository
    run_repository.create("run-1")
    run_repository.compare_and_set_status(
        "run-1", expected_status=RunStatus.PENDING, status=RunStatus.RUNNING
    )
    won = run_repository.compare_and_set_status(
        "run-1", expected_status=RunStatus.RUNNING, status=RunStatus.CANCELLED
    )
    assert won is not None

    lost = run_repository.compare_and_set_status(
        "run-1", expected_status=RunStatus.RUNNING, status=RunStatus.COMPLETED
    )
    assert lost is None
    current = run_repository.get("run-1")
    assert current is not None
    assert current.status == RunStatus.CANCELLED
    assert current.updated_at == won.updated_at


def test_compare_and_set_status_unknown_run_is_none(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    run_repository, _ = repository
    assert (
        run_repository.compare_and_set_status(
            "ghost", expected_status=RunStatus.RUNNING, status=RunStatus.COMPLETED
        )
        is None
    )


def test_set_execution_selection_round_trips(repository: tuple[RelationalRunRepository, SqliteDatabase]) -> None:
    run_repository, _ = repository
    run_repository.create("run-1")
    selection = RunExecutionSelection(
        runtime_id="runtime-a",
        model_provider_id="provider-a",
        model_id="model-a",
        hosting_mode=ModelHostingMode.LOCAL,
    )
    updated = run_repository.set_execution_selection("run-1", selection)
    assert updated is not None
    assert updated.execution_selection == selection
    assert run_repository.get("run-1").execution_selection == selection


def test_set_execution_selection_clears_to_none(repository: tuple[RelationalRunRepository, SqliteDatabase]) -> None:
    run_repository, _ = repository
    run_repository.create("run-1")
    run_repository.set_execution_selection("run-1", RunExecutionSelection(model_id="model-a"))
    cleared = run_repository.set_execution_selection("run-1", None)
    assert cleared is not None
    assert cleared.execution_selection is None


def test_set_execution_selection_unknown_run_is_none(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    run_repository, _ = repository
    assert run_repository.set_execution_selection("ghost", RunExecutionSelection()) is None


def test_set_assistant_message_id_round_trips_once(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    run_repository, _ = repository
    run_repository.create("run-1")
    updated = run_repository.set_assistant_message_id("run-1", "assistant-1")
    assert updated is not None
    assert updated.assistant_message_id == "assistant-1"
    assert run_repository.get("run-1") == updated


# ============================================================
# END: Update semantics
# ============================================================


# ============================================================
# BEGIN: Timestamps
# ============================================================


def test_timestamps_round_trip_as_aware_utc(repository: tuple[RelationalRunRepository, SqliteDatabase]) -> None:
    run_repository, _ = repository
    before = datetime.now(UTC)
    run_repository.create("run-1")
    stored = run_repository.get("run-1")
    assert stored is not None
    after = datetime.now(UTC)
    assert before <= stored.created_at <= after
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset().total_seconds() == 0
    assert stored.updated_at.tzinfo is not None


# ============================================================
# END: Timestamps
# ============================================================


# ============================================================
# BEGIN: Cancellation intent
# ============================================================


def _requested_at(minute: int = 1) -> datetime:
    return datetime(2026, 3, 4, 5, minute, tzinfo=UTC)


def test_a_new_run_has_no_cancellation_request(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    run_repository, _ = repository
    record = run_repository.create("run-1")
    assert record.cancellation_requested_at is None
    assert record.cancellation_requested is False


def test_an_active_run_records_a_cancellation_request(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    run_repository, _ = repository
    run_repository.create("run-1")

    updated = run_repository.request_cancellation("run-1", requested_at=_requested_at())

    assert updated is not None
    assert updated.status == RunStatus.PENDING
    assert updated.cancellation_requested_at == _requested_at()
    assert updated.cancellation_requested is True
    assert run_repository.get("run-1") == updated


def test_a_duplicate_request_keeps_the_first_timestamp(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    """Three clicks are one request, and the moment asked does not move."""
    run_repository, _ = repository
    run_repository.create("run-1")
    first = run_repository.request_cancellation("run-1", requested_at=_requested_at(1))
    assert first is not None

    for minute in (2, 3, 4):
        assert (
            run_repository.request_cancellation("run-1", requested_at=_requested_at(minute))
            is None
        )

    stored = run_repository.get("run-1")
    assert stored is not None
    assert stored.cancellation_requested_at == _requested_at(1)


@pytest.mark.parametrize(
    "terminal", [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED]
)
def test_a_settled_run_never_gains_a_cancellation_request(
    repository: tuple[RelationalRunRepository, SqliteDatabase], terminal: RunStatus
) -> None:
    """The request would have arrived too late to be true."""
    run_repository, _ = repository
    run_repository.create("run-1")
    run_repository.update_status("run-1", terminal)

    assert run_repository.request_cancellation("run-1", requested_at=_requested_at()) is None

    stored = run_repository.get("run-1")
    assert stored is not None
    assert stored.cancellation_requested_at is None


def test_a_request_survives_the_run_finishing_normally(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    """A completed run with a request timestamp is evidence, not a contradiction."""
    run_repository, _ = repository
    run_repository.create("run-1")
    run_repository.request_cancellation("run-1", requested_at=_requested_at())
    run_repository.update_status("run-1", RunStatus.COMPLETED)

    stored = run_repository.get("run-1")
    assert stored is not None
    assert stored.status == RunStatus.COMPLETED
    assert stored.cancellation_requested_at == _requested_at()


def test_a_lost_race_cannot_attach_a_request_to_a_settled_run(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    """The status guard is in the write, not in a read before it.

    The caller read ``pending``; by the time its guarded write runs the run has
    already completed. The request must not land.
    """
    run_repository, database = repository
    run_repository.create("run-1")
    connection_authoritative = run_repository.update_status("run-1", RunStatus.COMPLETED)
    assert connection_authoritative is not None

    assert run_repository.request_cancellation("run-1", requested_at=_requested_at()) is None
    assert database is not None


def test_a_request_for_an_unknown_run_is_none(
    repository: tuple[RelationalRunRepository, SqliteDatabase],
) -> None:
    run_repository, _ = repository
    assert run_repository.request_cancellation("ghost", requested_at=_requested_at()) is None


# ============================================================
# END: Cancellation intent
# ============================================================
