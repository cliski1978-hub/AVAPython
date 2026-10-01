"""Phase 5.39 terminal-writer race hardening.

A run has exactly one terminal outcome, and that outcome has to survive being
contested. This module races the writers that can plausibly settle the same run
at the same time and asserts the properties that must hold no matter who wins:

* exactly one terminal transition lands;
* the loser cannot rewrite the winner, and observes the canonical result of
  losing — either a converged same-status read or
  ``InvalidRunTransitionError``;
* at most one terminal event is ever durable, and it matches the final status;
* cancellation *intent* stays separate from cancellation *outcome*, even when a
  request and a settlement race;
* recovery is an ordinary terminal writer, not a privileged one: if a normal
  execution settles a run first, recovery must leave that verdict alone.

Every race here is forced, not hoped for. The contested window in
``RunLifecycleService.transition`` is the gap between reading the current status
and the guarded write, so :class:`ContestedReads` parks both writers in exactly
that gap with a ``threading.Barrier`` before either may write. Both writers
therefore observe the same pre-race status, and which one wins is decided by the
database compare-and-set — never by thread scheduling luck.

Real relational persistence is used throughout: the guarantees under test are
SQL ``WHERE``-clause compare-and-set and transaction ordering, so a memory store
would be exercising the wrong code.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ava.contracts.events import EventType
from ava.contracts.responses import RunStatus
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import (
    RelationalRunEventRepository,
    RelationalRunRepository,
)
from ava.services.run_lifecycle_service import (
    InvalidRunTransitionError,
    RunLifecycleService,
)
from ava.services.run_recovery_service import (
    RESTART_INTERRUPTION_PAYLOAD,
    RunRecoveryService,
)

TERMINAL_FOR_STATUS = {
    RunStatus.COMPLETED: EventType.RUN_COMPLETED,
    RunStatus.FAILED: EventType.RUN_FAILED,
    RunStatus.CANCELLED: EventType.RUN_CANCELLED,
}

#: How many times the core races repeat. A forced race is already
#: deterministic, so this is belt-and-braces against an ordering that happens to
#: favour one side — and it stays cheap because each iteration is milliseconds.
ITERATIONS = 12


# ============================================================
# BEGIN: Deterministic race harness
# ============================================================


class ContestedReads:
    """Parks every writer inside the read-then-write gap, once per thread.

    ``RunLifecycleService.transition`` reads the current status and then writes
    it back under a guard. This proxy makes that gap the point where threads
    meet: the first ``get`` from every participating thread blocks on a shared
    barrier, so all of them read the same pre-race status and all of them then
    race the guarded write. Later ``get`` calls — the loser's canonical
    re-read — pass straight through, so a thread can never deadlock waiting for
    a second rendezvous it was not promised.
    """

    def __init__(self, inner: Any, *, threads: int) -> None:
        self._inner = inner
        self._barrier = threading.Barrier(threads)
        self._local = threading.local()

    def get(self, run_id: str) -> Any:
        if not getattr(self._local, "parked", False):
            self._local.parked = True
            self._barrier.wait()
        return self._inner.get(run_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _attempt(action: Any) -> str:
    """Run one writer and classify how it lost, or that it did not."""
    try:
        action()
    except InvalidRunTransitionError:
        return "rejected"
    return "won"


def _race(action_a: Any, action_b: Any) -> dict[str, str]:
    """Contest two writers inside the read-then-write gap.

    Returns the outcome label for each side. Exactly one must be ``won``; a
    ``converged`` label means the caller reached the same terminal status, which
    is the other truthful way a same-state race can resolve.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_attempt, (action_a, action_b)))
    return {"a": results[0], "b": results[1]}


class Race:
    """A relational run/event pair plus the lifecycle authority over it."""

    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database
        self.runs = RelationalRunRepository(database=database)
        self.events = RelationalRunEventRepository(database=database)
        self.lifecycle = RunLifecycleService(
            run_repository=self.runs, run_event_repository=self.events
        )
        self.recovery = RunRecoveryService(run_repository=self.runs, lifecycle=self.lifecycle)

    def seed(self, run_id: str = "r1", *, status: RunStatus = RunStatus.RUNNING) -> None:
        self.lifecycle.create_run(run_id)
        if status is not RunStatus.PENDING:
            self.lifecycle.start(run_id)
        if status is RunStatus.WAITING_FOR_APPROVAL:
            self.runs.update_status(run_id, RunStatus.WAITING_FOR_APPROVAL)

    def contested(self, *, threads: int) -> tuple[RunLifecycleService, RelationalRunRepository]:
        """Lifecycle + repositories whose status reads rendezvous on a barrier."""
        runs = ContestedReads(self.runs, threads=threads)
        events = ContestedReads(self.events, threads=threads)
        return RunLifecycleService(run_repository=runs, run_event_repository=events), runs

    def terminal_events(self, run_id: str) -> list[EventType]:
        return [
            event.event_type
            for event in self.events.get_events(run_id)
            if event.event_type in set(TERMINAL_FOR_STATUS.values())
        ]

    def event_types(self, run_id: str) -> list[EventType]:
        return [event.event_type for event in self.events.get_events(run_id)]


def _assert_single_truthful_terminal(race: Race, run_id: str) -> RunStatus:
    """The status/event pair must agree, and exactly one terminal fact may exist."""
    record = race.runs.get(run_id)
    assert record is not None
    assert record.status in TERMINAL_FOR_STATUS, f"{run_id} did not settle: {record.status}"

    terminals = race.terminal_events(run_id)
    assert len(terminals) == 1, f"expected one terminal event, got {terminals}"
    assert terminals[0] is TERMINAL_FOR_STATUS[record.status], (
        f"status {record.status.value} contradicts event {terminals[0].value}"
    )

    sequences = [event.sequence for event in race.events.get_events(run_id)]
    assert sequences == list(range(1, len(sequences) + 1)), sequences
    assert len({event.event_id for event in race.events.get_events(run_id)}) == len(sequences)
    return record.status


@pytest.fixture
def race(tmp_path):
    database = SqliteDatabase(str(tmp_path / "lifecycle-race.sqlite3"))
    try:
        yield Race(database)
    finally:
        database.dispose()


# ============================================================
# END: Deterministic race harness
# ============================================================
# ============================================================
# BEGIN: Completion vs cancellation
# ============================================================


@pytest.mark.parametrize("iteration", range(ITERATIONS))
def test_completion_racing_cancellation_settles_exactly_one_terminal_outcome(race, iteration) -> None:
    """Completion and cancellation of the same running run: one winner, one fact.

    Both writers are forced to read ``running`` before either writes, so this is
    the genuine contended case rather than a sequential lucky one. Whichever
    side wins, the run must carry exactly one terminal status and exactly one
    matching terminal event.
    """
    run_id = f"r-complete-{iteration}"
    race.seed(run_id)
    lifecycle, _ = race.contested(threads=2)

    outcomes = _race(
        lambda: lifecycle.complete(run_id),
        lambda: lifecycle.cancel(run_id),
    )

    assert sorted(outcomes.values()).count("won") == 1, outcomes
    assert sorted(outcomes.values()).count("rejected") == 1, outcomes

    status = _assert_single_truthful_terminal(race, run_id)
    assert status in (RunStatus.COMPLETED, RunStatus.CANCELLED)
    # A completed run was never cancelled on purpose, and a cancelled run never
    # claimed to have finished: exactly one of the two terminal facts exists and
    # the other was never appended.
    appended = set(race.event_types(run_id))
    if status is RunStatus.COMPLETED:
        assert EventType.RUN_CANCELLED not in appended
    else:
        assert EventType.RUN_COMPLETED not in appended


# ============================================================
# END: Completion vs cancellation
# ============================================================
# ============================================================
# BEGIN: Failure vs cancellation
# ============================================================


@pytest.mark.parametrize("iteration", range(ITERATIONS))
def test_failure_racing_cancellation_settles_exactly_one_terminal_outcome(race, iteration) -> None:
    """Failure and cancellation cannot both become the winning terminal fact.

    This is the race where the two losers are easiest to confuse: a user asked
    to stop a run that was already failing. The durable record must still say
    exactly one of them happened.
    """
    run_id = f"r-failure-{iteration}"
    race.seed(run_id)
    lifecycle, _ = race.contested(threads=2)

    outcomes = _race(
        lambda: lifecycle.fail(run_id, payload={"error_code": "agent_failed", "message": "boom"}),
        lambda: lifecycle.cancel(run_id),
    )

    assert sorted(outcomes.values()).count("won") == 1, outcomes
    assert sorted(outcomes.values()).count("rejected") == 1, outcomes

    status = _assert_single_truthful_terminal(race, run_id)
    assert status in (RunStatus.FAILED, RunStatus.CANCELLED)

    appended = set(race.event_types(run_id))
    assert not {EventType.RUN_FAILED, EventType.RUN_CANCELLED} - {TERMINAL_FOR_STATUS[status]} & appended
    assert appended & {EventType.RUN_FAILED, EventType.RUN_CANCELLED} == {
        TERMINAL_FOR_STATUS[status]
    }


# ============================================================
# END: Failure vs cancellation
# ============================================================
# ============================================================
# BEGIN: Two terminal writers
# ============================================================


def test_complete_and_fail_racing_leaves_the_winners_verdict_intact(race) -> None:
    """The loser's classification must not overwrite the winner's payload."""
    race.seed("r-cf")
    lifecycle, _ = race.contested(threads=2)

    outcomes = _race(
        lambda: lifecycle.complete("r-cf"),
        lambda: lifecycle.fail("r-cf", payload={"error_code": "agent_failed", "message": "boom"}),
    )
    assert sorted(outcomes.values()).count("won") == 1, outcomes
    status = _assert_single_truthful_terminal(race, "r-cf")
    assert status in (RunStatus.COMPLETED, RunStatus.FAILED)


def test_all_three_terminal_writers_racing_yield_one_winner(race) -> None:
    """Three simultaneous terminal claims: still exactly one of them lands."""
    race.seed("r-three")
    lifecycle, _ = race.contested(threads=3)

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(
            pool.map(
                _attempt,
                (
                    lambda: lifecycle.complete("r-three"),
                    lambda: lifecycle.fail("r-three", payload={"error_code": "agent_failed"}),
                    lambda: lifecycle.cancel("r-three"),
                ),
            )
        )
    assert outcomes.count("won") == 1, outcomes
    assert outcomes.count("rejected") == 2, outcomes
    _assert_single_truthful_terminal(race, "r-three")


def test_a_lost_race_cannot_rewrite_the_winners_terminal_status(race) -> None:
    """The loser's follow-up write is a no-op, not a correction.

    After the race, forcing the losing transition again must not move anything:
    the run is terminal forever.
    """
    race.seed("r-frozen")
    lifecycle, _ = race.contested(threads=2)
    _race(
        lambda: lifecycle.complete("r-frozen"),
        lambda: lifecycle.fail("r-frozen", payload={"error_code": "agent_failed"}),
    )
    settled = race.runs.get("r-frozen")
    assert settled is not None
    before = list(race.events.get_events("r-frozen"))
    winner_status = settled.status

    # The repeats go through the uncontested authority: this checks that a
    # terminal run is frozen, not that a barrier can be satisfied.
    #
    # A repeat of the *same* terminal status is idempotent — it returns the
    # record and writes nothing. A repeat of a *different* terminal status is
    # rejected outright, because "terminal" means the status is never reopened.
    # Neither form may move the run or append a fact.
    lifecycle = race.lifecycle
    repeats = {
        RunStatus.COMPLETED: lifecycle.complete,
        RunStatus.FAILED: lambda run_id: lifecycle.fail(run_id, payload={"error_code": "x"}),
        RunStatus.CANCELLED: lifecycle.cancel,
    }
    for status, repeat in repeats.items():
        if status is winner_status:
            repeat("r-frozen")
        else:
            with pytest.raises(InvalidRunTransitionError):
                repeat("r-frozen")
    assert race.runs.get("r-frozen").status is winner_status
    after = list(race.events.get_events("r-frozen"))
    assert [(e.event_id, e.sequence, e.event_type) for e in after] == [
        (e.event_id, e.sequence, e.event_type) for e in before
    ]


# ============================================================
# END: Two terminal writers
# ============================================================
# ============================================================
# BEGIN: Recovery races
# ============================================================


@pytest.mark.parametrize("iteration", range(ITERATIONS))
def test_recovery_racing_completion_keeps_exactly_one_terminal_verdict(race, iteration) -> None:
    """Recovery is a terminal writer, not a privileged one.

    Phase 5.38 certified that recovery settles a stranded active run. What it
    did not certify is what happens when a normal execution settles that same
    run at the same moment — for instance when a runtime acknowledgement lands
    just as a cold-start sweep runs. Recovery must not win by fiat, and a
    completion must not be overwritten by an interruption verdict.
    """
    run_id = f"r-recover-complete-{iteration}"
    race.seed(run_id)
    runs = ContestedReads(race.runs, threads=2)
    events = ContestedReads(race.events, threads=2)
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    recovery = RunRecoveryService(run_repository=race.runs, lifecycle=lifecycle)

    outcomes = _race(
        lambda: recovery.recover_stranded_runs(),
        lambda: lifecycle.complete(run_id),
    )
    # The recovery call may legitimately find nothing left to settle if the
    # completion landed first, so "won" is not required of it — only that at
    # most one verdict survives and both sides terminate.
    assert outcomes["a"] in ("won", "rejected"), outcomes

    status = _assert_single_truthful_terminal(race, run_id)
    assert status in (RunStatus.COMPLETED, RunStatus.FAILED)
    if status is RunStatus.FAILED:
        # If recovery settled it, the interruption classification is the one
        # that persisted, with its safe wording.
        failure = [
            event
            for event in race.events.get_events(run_id)
            if event.event_type is EventType.RUN_FAILED
        ][0]
        assert failure.payload == RESTART_INTERRUPTION_PAYLOAD
    else:
        assert EventType.RUN_FAILED not in race.event_types(run_id)


@pytest.mark.parametrize("iteration", range(ITERATIONS))
def test_recovery_racing_failure_keeps_the_first_durable_classification(race, iteration) -> None:
    """When both sides fail, the first durable classification stays authoritative.

    Both writers agreeing on ``failed`` is the easy case, but it is exactly where
    a lost write would quietly rewrite the reason. Whichever verdict commits
    first, the second must not restate it with its own code.
    """
    run_id = f"r-recover-failure-{iteration}"
    race.seed(run_id)
    runs = ContestedReads(race.runs, threads=2)
    events = ContestedReads(race.events, threads=2)
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    recovery = RunRecoveryService(run_repository=race.runs, lifecycle=lifecycle)

    _race(
        lambda: recovery.recover_stranded_runs(),
        lambda: lifecycle.fail(run_id, payload={"error_code": "agent_failed", "message": "boom"}),
    )

    status = _assert_single_truthful_terminal(race, run_id)
    assert status is RunStatus.FAILED
    failures = [
        event
        for event in race.events.get_events(run_id)
        if event.event_type is EventType.RUN_FAILED
    ]
    assert len(failures) == 1
    # Whichever code won is one of the two real verdicts, and it is not a blend.
    assert failures[0].payload.get("error_code") in (
        "execution_interrupted",
        "agent_failed",
    )
    if failures[0].payload.get("error_code") == "execution_interrupted":
        assert failures[0].payload == RESTART_INTERRUPTION_PAYLOAD
    else:
        assert failures[0].payload == {"error_code": "agent_failed", "message": "boom"}


def test_recovery_racing_a_cancellation_request_never_infers_cancellation(race) -> None:
    """Cancellation intent can win the field while the outcome stays failed.

    The request is durable and the settlement is durable, and they are different
    claims. A run whose user asked to stop it and which then lost its process
    still failed for the honest reason: there was no runtime left to acknowledge
    anything.
    """
    race.seed("r-recover-cancel")
    runs = ContestedReads(race.runs, threads=2)
    events = ContestedReads(race.events, threads=2)
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    recovery = RunRecoveryService(run_repository=race.runs, lifecycle=lifecycle)
    requested_at = datetime.now(UTC)

    _race(
        lambda: recovery.recover_stranded_runs(),
        lambda: lifecycle.request_cancellation("r-recover-cancel", requested_at=requested_at),
    )

    record = race.runs.get("r-recover-cancel")
    assert record is not None
    types = race.event_types("r-recover-cancel")
    # The invariant that matters either way: a cancellation request is never
    # turned into a cancellation. Only an acknowledged settlement may say
    # `cancelled`, and nothing acknowledged anything here.
    assert record.status is not RunStatus.CANCELLED, "intent was read as an outcome"
    assert EventType.RUN_CANCELLED not in types
    _assert_single_truthful_terminal(race, "r-recover-cancel")

    if record.status is RunStatus.FAILED:
        # Either write may land first.  When recovery wins, the request is too
        # late and no intent is stored.  When the request wins, its durable
        # intent survives the later recovery failure; it still must never be
        # confused with a cancelled outcome.
        if record.cancellation_requested_at is None:
            assert EventType.RUN_CANCEL_REQUESTED not in types
        else:
            assert record.cancellation_requested_at == requested_at
            assert types.count(EventType.RUN_CANCEL_REQUESTED) == 1
    else:
        raise AssertionError(f"unreachable status {record.status}")


def test_a_second_recovery_after_a_race_settles_nothing_further(race) -> None:
    """Once the race is over, recovery is a no-op — no second failure fact."""
    race.seed("r-once")
    lifecycle, _ = race.contested(threads=2)
    _race(
        lambda: lifecycle.complete("r-once"),
        lambda: lifecycle.fail("r-once", payload={"error_code": "agent_failed"}),
    )
    before = list(race.events.get_events("r-once"))

    summary = race.recovery.recover_stranded_runs()
    assert (summary.active_found, summary.settled_failed) == (0, 0)
    after = list(race.events.get_events("r-once"))
    assert [(e.event_id, e.sequence) for e in after] == [
        (e.event_id, e.sequence) for e in before
    ]


# ============================================================
# END: Recovery races
# ============================================================
# ============================================================
# BEGIN: Cancellation request concurrency
# ============================================================


@pytest.mark.parametrize("iteration", range(ITERATIONS))
def test_concurrent_cancellation_requests_record_intent_exactly_once(race, iteration) -> None:
    """Three clicks are one request.

    Concurrent requests must agree on a single durable ``cancellation_requested_at``
    — the moment the user first asked — and produce one intent fact. Intent is
    not a status, so the run stays active afterwards and is still cancellable.
    """
    run_id = f"r-cancel-intent-{iteration}"
    race.seed(run_id)
    runs = ContestedReads(race.runs, threads=4)
    events = ContestedReads(race.events, threads=4)
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    base = datetime.now(UTC)

    def request(offset: int) -> None:
        lifecycle.request_cancellation(run_id, requested_at=base + timedelta(seconds=offset))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(request, range(4)))

    record = race.runs.get(run_id)
    assert record is not None
    # Still running: a request is intent, not an outcome.
    assert record.status is RunStatus.RUNNING
    assert record.cancellation_requested_at is not None
    assert base <= record.cancellation_requested_at <= base + timedelta(seconds=4)

    requested_events = [
        event for event in race.events.get_events(run_id)
        if event.event_type is EventType.RUN_CANCEL_REQUESTED
    ]
    assert len(requested_events) == 1, requested_events
    # A request fact is not a terminal fact.
    assert not any(event.event_type in set(TERMINAL_FOR_STATUS.values()) for event in race.events.get_events(run_id))

    # A later request never moves the moment the user first asked. This goes
    # through the uncontested authority: the barrier is already satisfied.
    later = base + timedelta(minutes=5)
    race.lifecycle.request_cancellation(run_id, requested_at=later)
    assert race.runs.get(run_id).cancellation_requested_at == record.cancellation_requested_at
    assert len([
        event for event in race.events.get_events(run_id)
        if event.event_type is EventType.RUN_CANCEL_REQUESTED
    ]) == 1


def test_a_cancellation_request_racing_a_settlement_lands_on_the_settled_run(race) -> None:
    """A request that arrives after the run settled is too late to be true.

    The run must not be retroactively marked as having been cancelled on
    purpose. A late request returns the settled record untouched and writes no
    intent at all.
    """
    race.seed("r-late-cancel")
    race.lifecycle.complete("r-late-cancel")  # uncontested: a settled run first
    before = list(race.events.get_events("r-late-cancel"))

    record = race.lifecycle.request_cancellation(
        "r-late-cancel", requested_at=datetime.now(UTC)
    )
    assert record.status is RunStatus.COMPLETED
    stored = race.runs.get("r-late-cancel")
    assert stored.status is RunStatus.COMPLETED
    assert stored.cancellation_requested_at is None
    after = list(race.events.get_events("r-late-cancel"))
    assert [(e.event_id, e.sequence) for e in after] == [
        (e.event_id, e.sequence) for e in before
    ]


# ============================================================
# END: Cancellation request concurrency
# ============================================================
# ============================================================
# BEGIN: Same-state idempotence under contention
# ============================================================


def test_concurrent_identical_transitions_converge_without_duplicate_events(race) -> None:
    """Two writers asking for the same state is idempotent, not a race.

    Without a forced rendezvous this would pass trivially; with one, both
    writers read ``running``, both attempt the same guarded write, and exactly
    one fact may exist.
    """
    race.seed("r-same")
    lifecycle, _ = race.contested(threads=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _run: _attempt(lambda: lifecycle.complete("r-same")), range(2)))

    # Same-state convergence is the documented outcome: the loser reports the
    # state the winner already reached rather than raising.
    assert "rejected" not in results, results
    _assert_single_truthful_terminal(race, "r-same")
    assert len(race.terminal_events("r-same")) == 1


# ============================================================
# END: Same-state idempotence under contention
# ============================================================
