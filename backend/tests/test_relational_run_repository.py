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