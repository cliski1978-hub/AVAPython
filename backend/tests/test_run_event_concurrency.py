"""Phase 5.39 concurrent run-event writer stress.

Phase 5.26 certified that the relational event repository allocates a
contiguous, unique sequence per run under light contention. This module takes
that to the scale where a sequence allocator, a single shared connection, or a
savepoint would actually break, and it stresses several runs at once so that
allocation for one run cannot be allowed to consume or corrupt another's.

Everything runs against real file-backed SQLite. Sequence allocation is
``SELECT COALESCE(MAX(seq), 0) + 1`` inside a transaction, so uniqueness depends
on the transaction actually being atomic — which is precisely the property under
test. The write path is forced to overlap with a ``threading.Barrier`` so every
appender reaches the repository together rather than trickling in.

The failure modes this guards against are concrete and were all observed as real
bugs during Phase 5.38/5.39 work: ``cannot start a transaction within a
transaction``, ``database is locked``, savepoint corruption from a nested
transaction believing it was the outermost, sequence collisions, and — the
subtlest — a read that returned no row for a row that durably existed, which
happened when several threads shared one ``sqlite3.Connection`` unguarded.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ava.contracts.events import EventType, RunEvent
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import (
    RelationalRunEventRepository,
    RelationalRunRepository,
)
from ava.services.run_lifecycle_service import RunLifecycleService

#: Concurrent appends aimed at a single run. High enough that a non-atomic
#: ``MAX(seq) + 1`` would visibly collide, low enough to stay fast.
SINGLE_RUN_APPENDS = 100
#: Independent runs written simultaneously, each with its own appends.
CONCURRENT_RUNS = 4
APPENDS_PER_RUN = 40
#: Terminal facts raced at once, to confirm the storage-level seal holds under
#: real contention rather than in a sequential test.
CONCURRENT_TERMINALS = 20


class _RollbackError(Exception):
    """Raised inside a transaction to prove the rollback path is clean."""


def _event(event_id: str, run_id: str, event_type: EventType) -> RunEvent:
    return RunEvent(event_id=event_id, run_id=run_id, event_type=event_type, payload={})


def _barrier_appender(repository: RelationalRunEventRepository, run_id: str, barrier: threading.Barrier):
    """An appender that joins a common rendezvous, then appends one event.

    The barrier sits at the start of the unit of work so the appends are issued
    together; ordering is then decided by the database, not by the test.
    """

    def append(number: int) -> None:
        event = _event(f"{run_id}-{number}", run_id, EventType.MESSAGE_STARTED)
        barrier.wait()
        repository.append(event)

    return append


def test_one_hundred_concurrent_appends_allocate_one_contiguous_sequence(tmp_path) -> None:
    """100 simultaneous appends to one run produce sequences 1..100, no more, no less."""
    database = SqliteDatabase(str(tmp_path / "single-run-stress.sqlite3"))
    try:
        repository = RelationalRunEventRepository(database=database)
        run_id = "hot-run"
        append = _barrier_appender(repository, run_id, threading.Barrier(SINGLE_RUN_APPENDS))

        with ThreadPoolExecutor(max_workers=SINGLE_RUN_APPENDS) as pool:
            list(pool.map(append, range(SINGLE_RUN_APPENDS)))

        events = repository.get_events(run_id)
        assert len(events) == SINGLE_RUN_APPENDS
        sequences = [event.sequence for event in events]
        assert sequences == list(range(1, SINGLE_RUN_APPENDS + 1)), sequences
        assert len(set(sequences)) == SINGLE_RUN_APPENDS
        # Every write is present and every identity is unique.
        assert {event.event_id for event in events} == {
            f"{run_id}-{number}" for number in range(SINGLE_RUN_APPENDS)
        }
        assert len({event.event_id for event in events}) == len(events)
    finally:
        database.dispose()


def test_concurrent_appends_to_several_runs_keep_independent_sequences(tmp_path) -> None:
    """Concurrent writes to several runs do not consume or corrupt each other's sequences.

    Each run must own a complete, contiguous ``1..N`` history even though every
    appender for every run is in flight at the same time. This is the property
    that makes per-run replay cursors safe.
    """
    database = SqliteDatabase(str(tmp_path / "multi-run-stress.sqlite3"))
    try:
        repository = RelationalRunEventRepository(database=database)
        run_ids = [f"run-{index}" for index in range(CONCURRENT_RUNS)]
        total = CONCURRENT_RUNS * APPENDS_PER_RUN
        barrier = threading.Barrier(total)
        appenders = [
            _barrier_appender(repository, run_id, barrier) for run_id in run_ids
        ]

        work = [
            (appenders[run_index], number)
            for run_index in range(CONCURRENT_RUNS)
            for number in range(APPENDS_PER_RUN)
        ]
        with ThreadPoolExecutor(max_workers=total) as pool:
            futures = [pool.submit(append, number) for append, number in work]
            for future in futures:
                future.result()

        for run_id in run_ids:
            sequences = [event.sequence for event in repository.get_events(run_id)]
            assert sequences == list(range(1, APPENDS_PER_RUN + 1)), (
                f"{run_id} sequence corrupted under concurrent load: {sequences}"
            )
    finally:
        database.dispose()


def test_concurrent_terminal_appends_seal_at_exactly_one_fact(tmp_path) -> None:
    """Racing terminal appends cannot produce two terminal facts for one run.

    The repository refuses a second terminal event for a run that already has
    one. Under real contention that refusal is what keeps a resumed client from
    ever seeing two terminal events for a single run.
    """
    database = SqliteDatabase(str(tmp_path / "terminal-seal.sqlite3"))
    try:
        repository = RelationalRunEventRepository(database=database)
        run_id = "sealed-run"
        repository.append(_event(f"{run_id}-start", run_id, EventType.RUN_STARTED))
        barrier = threading.Barrier(CONCURRENT_TERMINALS)
        terminal_types = [
            EventType.RUN_COMPLETED,
            EventType.RUN_FAILED,
            EventType.RUN_CANCELLED,
        ]

        def append_terminal(number: int) -> None:
            event = _event(
                f"terminal-{number}", run_id, terminal_types[number % len(terminal_types)]
            )
            barrier.wait()
            repository.append(event)

        with ThreadPoolExecutor(max_workers=CONCURRENT_TERMINALS) as pool:
            list(pool.map(append_terminal, range(CONCURRENT_TERMINALS)))

        events = repository.get_events(run_id)
        terminals = [
            event
            for event in events
            if event.event_type in {EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.RUN_CANCELLED}
        ]
        assert len(terminals) == 1, [event.event_type for event in terminals]
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    finally:
        database.dispose()


def test_concurrent_reads_and_appends_never_corrupt_each_other(tmp_path) -> None:
    """Interleaved reads and appends on one database stay consistent.

    This is the regression guard for the shared-connection defect Phase 5.39
    found: reads that returned *no row* for a row that durably existed, and
    ``InterfaceError`` from the driver. A reader must observe a run that exists,
    every time, no matter how many writers are appending to it.
    """
    database = SqliteDatabase(str(tmp_path / "read-write-mix.sqlite3"))
    try:
        runs = RelationalRunRepository(database=database)
        events = RelationalRunEventRepository(database=database)
        for index in range(5):
            runs.create(f"run-{index}")

        reads_per_thread = 60
        appends_per_run = 25
        barrier = threading.Barrier(10)
        errors: list[str] = []
        guard = threading.Lock()

        def reader(index: int) -> None:
            barrier.wait()
            for _ in range(reads_per_thread):
                record = runs.get(f"run-{index}")
                if record is None:
                    with guard:
                        errors.append(f"run-{index} read back as missing")
                    return

        def appender(index: int) -> None:
            barrier.wait()
            for number in range(appends_per_run):
                events.append(
                    _event(f"run-{index}-{number}", f"run-{index}", EventType.MESSAGE_STARTED)
                )

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(reader, index) for index in range(5)]
            futures += [pool.submit(appender, index) for index in range(5)]
            for future in futures:
                future.result()

        assert errors == [], errors
        for index in range(5):
            sequences = [event.sequence for event in events.get_events(f"run-{index}")]
            assert sequences == list(range(1, appends_per_run + 1)), (index, sequences)
            assert runs.get(f"run-{index}") is not None
    finally:
        database.dispose()


def test_a_nested_transaction_participates_without_corrupting_the_enclosing_one(tmp_path) -> None:
    """A repository write inside a caller's transaction joins it as a savepoint.

    The event repository opens its own transaction. When it is invoked inside an
    enclosing one, it must nest rather than try to start a second real
    transaction — otherwise the failure is the classic ``cannot start a
    transaction within a transaction`` and the outer unit of work is broken.
    """
    database = SqliteDatabase(str(tmp_path / "nested.sqlite3"))
    try:
        events = RelationalRunEventRepository(database=database)
        run_id = "nested-run"
        events.append(_event("outer-1", run_id, EventType.RUN_STARTED))

        with database.transaction():
            events.append(_event("outer-2", run_id, EventType.MESSAGE_STARTED))
            # Nested again, one level deeper, still inside the same unit of work.
            with database.transaction():
                events.append(_event("outer-3", run_id, EventType.MESSAGE_STARTED))

        assert [event.sequence for event in events.get_events(run_id)] == [1, 2, 3]

        # A failure inside the enclosing transaction still rolls back cleanly,
        # so savepoint handling did not leave a partial history behind.
        with pytest.raises(_RollbackError), database.transaction():
            events.append(_event("doomed", run_id, EventType.MESSAGE_STARTED))
            raise _RollbackError()

        assert [event.sequence for event in events.get_events(run_id)] == [1, 2, 3]
    finally:
        database.dispose()


def test_a_racing_rollback_does_not_corrupt_another_threads_writes(tmp_path) -> None:
    """One writer's rollback must not erase or renumber a concurrent writer's work.

    A rollback releases savepoints on the shared connection. If that were not
    properly scoped, a concurrent appender could find its sequence range
    clobbered by an unrelated failure.
    """
    database = SqliteDatabase(str(tmp_path / "rollback-race.sqlite3"))
    try:
        events = RelationalRunEventRepository(database=database)
        run_id = "rollback-run"
        barrier = threading.Barrier(2)
        committed: list[int] = []
        failure_raised = threading.Event()

        def good_writer() -> None:
            barrier.wait()
            for number in range(15):
                events.append(_event(f"good-{number}", run_id, EventType.MESSAGE_STARTED))
                committed.append(number)

        def bad_writer() -> None:
            barrier.wait()
            try:
                with database.transaction():
                    for number in range(5):
                        events.append(
                            _event(f"bad-{number}", run_id, EventType.MESSAGE_STARTED)
                        )
                    raise _RollbackError()
            except _RollbackError:
                failure_raised.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(good_writer), pool.submit(bad_writer)]
            for future in futures:
                future.result()

        assert failure_raised.is_set()
        events_after = events.get_events(run_id)
        assert {event.event_id for event in events_after} == {
            f"good-{number}" for number in committed
        }
        sequences = [event.sequence for event in events_after]
        assert sequences == list(range(1, len(committed) + 1)), sequences
    finally:
        database.dispose()


def test_lifecycle_transitions_under_load_keep_status_and_event_in_agreement(tmp_path) -> None:
    """Concurrent lifecycle traffic leaves no run whose status contradicts its facts."""
    database = SqliteDatabase(str(tmp_path / "lifecycle-load.sqlite3"))
    try:
        runs = RelationalRunRepository(database=database)
        events = RelationalRunEventRepository(database=database)
        lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
        run_count = 25
        for index in range(run_count):
            lifecycle.create_run(f"load-{index}")
            lifecycle.start(f"load-{index}")

        def settle(index: int) -> None:
            run_id = f"load-{index}"
            if index % 2 == 0:
                lifecycle.complete(run_id)
            else:
                lifecycle.fail(run_id, payload={"error_code": "agent_failed", "message": "boom"})

        with ThreadPoolExecutor(max_workers=run_count) as pool:
            list(pool.map(settle, range(run_count)))

        for index in range(run_count):
            run_id = f"load-{index}"
            record = runs.get(run_id)
            assert record is not None
            terminal_events = [
                event
                for event in events.get_events(run_id)
                if event.event_type
                in {EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.RUN_CANCELLED}
            ]
            assert len(terminal_events) == 1, (run_id, terminal_events)
            expected = (
                EventType.RUN_COMPLETED if record.status.value == "completed" else EventType.RUN_FAILED
            )
            assert terminal_events[0].event_type is expected, run_id
            # A fresh event id per lifecycle fact, never a reused identity.
            all_ids = [event.event_id for event in events.get_events(run_id)]
            assert len(set(all_ids)) == len(all_ids)
    finally:
        database.dispose()


def test_a_replayed_event_identity_is_rejected_rather_than_duplicated(tmp_path) -> None:
    """Re-applying a durable fact is refused, so a reconnect cannot double history.

    A client that reconnects may see an event it already applied. The durable log
    is keyed by event id, and a duplicate id is a port-level ``ValueError`` — the
    write is refused outright rather than becoming a second copy of the same
    fact. Rejection is stronger than silent ignoring: a caller that miscounted
    learns about it instead of quietly widening the log.
    """
    database = SqliteDatabase(str(tmp_path / "replay.sqlite3"))
    try:
        events = RelationalRunEventRepository(database=database)
        run_id = "replay-run"
        events.append(_event("stable-id", run_id, EventType.MESSAGE_STARTED))

        with pytest.raises(ValueError, match="already exists"):
            events.append(_event("stable-id", run_id, EventType.MESSAGE_STARTED))

        history = events.get_events(run_id)
        assert [event.event_id for event in history] == ["stable-id"]
        assert [event.sequence for event in history] == [1]
    finally:
        database.dispose()


def test_repeated_concurrent_sequences_never_reuse_an_identity(tmp_path) -> None:
    """Across many rounds, no two events ever share an identity."""
    database = SqliteDatabase(str(tmp_path / "identity.sqlite3"))
    try:
        events = RelationalRunEventRepository(database=database)
        run_id = "identity-run"
        rounds = 4
        per_round = 25
        for round_index in range(rounds):
            barrier = threading.Barrier(per_round)
            append = _barrier_appender(events, run_id, barrier)
            with ThreadPoolExecutor(max_workers=per_round) as pool:
                list(pool.map(append, range(round_index * per_round, (round_index + 1) * per_round)))

        history = events.get_events(run_id)
        assert len(history) == rounds * per_round
        assert [event.sequence for event in history] == list(range(1, len(history) + 1))
        assert len({event.event_id for event in history}) == len(history)
    finally:
        database.dispose()
