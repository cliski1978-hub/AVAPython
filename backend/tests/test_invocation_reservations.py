"""Durable tool lifecycle reservation and recovery contract tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ava.contracts.execution import ExecutionMode
from ava.infrastructure.persistence import SqliteDatabase, create_relational_repositories
from ava.infrastructure.persistence.errors import PersistenceError
from ava.infrastructure.persistence.repositories.invocation_reservation_repository import (
    RelationalInvocationReservationRepository,
)
from ava.repositories.invocation_reservation_repository import (
    InMemoryInvocationReservationRepository,
    InvocationReservation,
    InvocationReservationConflict,
)
from ava.repositories.invocation_reservation_repository import (
    InvocationReservationState as State,
)
from ava.services.run_store import RunStore
from ava.services.tool_execution_service import ToolExecutionService


def _record(invocation_id: str = "inv-1", **changes: object) -> InvocationReservation:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "invocation_id": invocation_id,
        "run_id": "run-1",
        "tool_id": "workspace.read_file",
        "tool_version": "1",
        "operation_fingerprint": "a" * 64,
        "workspace_id": "workspace-1",
        "execution_context_ref": "context-1",
        "authority_revision_ref": "authority-rev-2",
        "configuration_revision_ref": "tool-features:4",
        "execution_mode": ExecutionMode.AGENT.value,
        "state": State.RESERVED,
        "revision": 0,
        "created_at": now,
        "updated_at": now,
    }
    values.update(changes)
    return InvocationReservation(**values)


def _repository(path: Path) -> tuple[SqliteDatabase, RelationalInvocationReservationRepository]:
    repositories = create_relational_repositories(str(path))
    repositories.run_repository.create("run-1", execution_mode=ExecutionMode.AGENT)
    return repositories.database, repositories.invocation_reservation_repository


def test_reservation_cas_duplicate_and_terminal_immutability(tmp_path: Path) -> None:
    database, repository = _repository(tmp_path / "lifecycle.sqlite3")
    try:
        reserved = repository.reserve(_record())
        with pytest.raises(InvocationReservationConflict):
            repository.reserve(_record())
        executing = repository.transition(reserved.invocation_id, expected_revision=0, state=State.EXECUTING)
        assert executing.revision == 1 and executing.started_at is not None
        completed = repository.transition(
            executing.invocation_id,
            expected_revision=1,
            state=State.COMPLETED,
            result_status="completed",
        )
        assert completed.revision == 2 and completed.completed_at is not None
        with pytest.raises(InvocationReservationConflict):
            repository.transition(completed.invocation_id, expected_revision=2, state=State.FAILED)
        with pytest.raises(InvocationReservationConflict):
            repository.transition(executing.invocation_id, expected_revision=1, state=State.FAILED)
    finally:
        database.dispose()


def test_sqlite_reservation_is_unique_across_independent_connections(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.sqlite3"
    database, first = _repository(path)
    other_database = SqliteDatabase(str(path))
    second = RelationalInvocationReservationRepository(other_database)
    try:

        def reserve(repo: RelationalInvocationReservationRepository) -> bool:
            try:
                repo.reserve(_record())
                return True
            except InvocationReservationConflict:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(reserve, (first, second)))
        assert sorted(outcomes) == [False, True]
    finally:
        database.dispose()
        other_database.dispose()


def test_identity_cannot_be_rebound_and_history_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "restart.sqlite3"
    database, repository = _repository(path)
    repository.reserve(_record())
    repository.transition("inv-1", expected_revision=0, state=State.EXECUTING)
    database.dispose()

    reopened = SqliteDatabase(str(path))
    repository = RelationalInvocationReservationRepository(reopened)
    try:
        recovered = repository.get("inv-1")
        assert recovered is not None
        assert recovered.state == State.EXECUTING
        assert recovered.workspace_id == "workspace-1"
        assert recovered.operation_fingerprint == "a" * 64
        with pytest.raises(InvocationReservationConflict):
            repository.reserve(_record(operation_fingerprint="b" * 64))
        assert repository.get("inv-1") == recovered
    finally:
        reopened.dispose()


def test_corrupt_lifecycle_record_fails_closed(tmp_path: Path) -> None:
    database, repository = _repository(tmp_path / "corrupt.sqlite3")
    repository.reserve(_record())
    try:
        with database.connect() as connection:
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                "UPDATE tool_invocation_reservations SET state='unknown' WHERE invocation_id='inv-1'"
            )
        with pytest.raises(PersistenceError):
            repository.get("inv-1")
    finally:
        database.dispose()


def test_recovery_marks_reserved_as_not_started_and_executing_indeterminate(tmp_path: Path) -> None:
    runs = RunStore()
    runs.create("run-1", execution_mode=ExecutionMode.AGENT)
    database, repository = _repository(tmp_path / "recovery.sqlite3")
    # _repository uses its own run repository, while service reconciliation only
    # needs the same Run identity and the lifecycle repository.
    repository.reserve(_record("reserved"))
    repository.reserve(_record("active"))
    repository.transition("active", expected_revision=0, state=State.EXECUTING)
    service = ToolExecutionService(
        runs=runs,
        registry=None,
        features=None,
        policy=None,
        reservations=repository,  # type: ignore[arg-type]
    )
    try:
        outcomes = service.reconcile_interrupted_invocations()
        assert {r.invocation_id: r.state for r in outcomes} == {
            "reserved": State.FAILED,
            "active": State.INDETERMINATE,
        }
        assert service.reconcile_interrupted_invocations() == ()
    finally:
        database.dispose()


def test_recovery_fails_closed_on_run_mode_mismatch() -> None:
    runs = RunStore()
    runs.create("run-1", execution_mode=ExecutionMode.PLAN)
    reservations = InMemoryInvocationReservationRepository()
    reservations.reserve(_record("mismatch"))
    service = ToolExecutionService(
        runs=runs, registry=None, features=None, policy=None, reservations=reservations  # type: ignore[arg-type]
    )
    records = service.reconcile_interrupted_invocations()
    assert len(records) == 1
    assert records[0].state == State.FAILED
    assert records[0].error_code == "associated_run_mismatch_before_execution"


def test_history_queries_are_bounded_and_deterministic() -> None:
    repository = InMemoryInvocationReservationRepository()
    first = _record("inv-001")
    repository.reserve(first)
    for index in range(2, 6):
        repository.reserve(_record(f"inv-{index:03d}"))

    assert [row.invocation_id for row in repository.list_incomplete(limit=2)] == ["inv-001", "inv-002"]
    assert [row.invocation_id for row in repository.list_for_run("run-1", limit=2)] == ["inv-004", "inv-005"]
    with pytest.raises(ValueError):
        repository.list_for_run("run-1", limit=0)


def test_sqlite_recovery_query_respects_batch_limit(tmp_path: Path) -> None:
    database, repository = _repository(tmp_path / "bounded-recovery.sqlite3")
    try:
        for index in range(5):
            repository.reserve(_record(f"inv-{index:03d}"))
        assert [row.invocation_id for row in repository.list_incomplete(limit=2)] == ["inv-000", "inv-001"]
        assert [row.invocation_id for row in repository.list_for_run("run-1", limit=2)] == ["inv-003", "inv-004"]
    finally:
        database.dispose()
