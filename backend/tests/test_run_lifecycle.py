"""Phase 5.23 run-lifecycle tests: the state machine as a pure policy.

The lifecycle authority is exercised directly here, over the real repository
ports (in-memory and relational), so every allowed edge, every illegal edge,
every timestamp rule, and the idempotence decision are pinned without an agent,
a provider, or a network. Integration behavior (ordering, races, failures,
regenerate, restart) lives in ``test_run_lifecycle_integration.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from ava.contracts.events import EventType
from ava.contracts.responses import ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES, RunStatus
from ava.repositories.run_event_repository import TERMINAL_EVENT_TYPES
from ava.services.run_event_store import RunEventStore
from ava.services.run_lifecycle_service import (
    ALLOWED_TRANSITIONS,
    LIFECYCLE_EVENT_FOR_STATUS,
    InvalidRunTransitionError,
    RunLifecycleService,
    UnknownRunError,
)
from ava.services.run_store import RunStore

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ============================================================
# BEGIN: Helpers
# ============================================================


@dataclass
class _Lifecycle:
    """A lifecycle authority over in-memory stores, with call-order capture."""

    service: RunLifecycleService
    runs: RunStore
    events: RunEventStore


def _lifecycle() -> _Lifecycle:
    runs = RunStore()
    events = RunEventStore()
    return _Lifecycle(
        service=RunLifecycleService(run_repository=runs, run_event_repository=events),
        runs=runs,
        events=events,
    )


def _run(lifecycle: _Lifecycle, run_id: str = "run-1") -> None:
    lifecycle.service.create_run(run_id)


def _drive(lifecycle: _Lifecycle, run_id: str, path: list[RunStatus]) -> None:
    """Apply a legal status path, asserting every step is accepted."""
    for status in path:
        lifecycle.service.transition(run_id, status)


def _all_statuses() -> list[RunStatus]:
    return list(RunStatus)


# ============================================================
# END: Helpers
# ============================================================
# ============================================================
# BEGIN: Table Shape
# ============================================================


def test_every_status_has_a_transition_rule() -> None:
    """A new status cannot be added without deciding what it may do."""
    assert set(ALLOWED_TRANSITIONS) == set(RunStatus)


def test_terminal_statuses_have_no_way_out() -> None:
    """Completion, failure, and cancellation are final by construction."""
    for status in TERMINAL_RUN_STATUSES:
        assert ALLOWED_TRANSITIONS[status] == frozenset(), status


def test_every_active_status_can_still_reach_a_terminal_state() -> None:
    """An active run must be able to finish; no state can be a dead end."""
    for status in ACTIVE_RUN_STATUSES:
        allowed = ALLOWED_TRANSITIONS[status]
        assert allowed, status
        assert allowed & TERMINAL_RUN_STATUSES, status


def test_active_and_terminal_partition_the_vocabulary() -> None:
    """The two central definitions are exact complements, never overlapping."""
    assert frozenset() == ACTIVE_RUN_STATUSES & TERMINAL_RUN_STATUSES
    assert frozenset(RunStatus) == ACTIVE_RUN_STATUSES | TERMINAL_RUN_STATUSES


@pytest.mark.parametrize("status", list(RunStatus))
def test_status_classification_matches_the_table(status: RunStatus) -> None:
    """``is_terminal``/``is_active`` are derived, so they cannot drift."""
    assert status.is_terminal == (status in TERMINAL_RUN_STATUSES)
    assert status.is_active == (status in ACTIVE_RUN_STATUSES)
    assert status.is_terminal != status.is_active


def test_terminal_statuses_map_onto_terminal_lifecycle_events() -> None:
    """Each terminal status owns exactly one terminal event, and vice versa."""
    mapped = {
        status: LIFECYCLE_EVENT_FOR_STATUS[status]
        for status in TERMINAL_RUN_STATUSES
    }
    assert mapped == {
        RunStatus.COMPLETED: EventType.RUN_COMPLETED,
        RunStatus.FAILED: EventType.RUN_FAILED,
        RunStatus.CANCELLED: EventType.RUN_CANCELLED,
    }
    assert {event for event in mapped.values()} == set(TERMINAL_EVENT_TYPES)


def test_only_running_and_terminal_statuses_emit_lifecycle_events() -> None:
    """``pending`` and the approval gate have no event in this vocabulary yet."""
    assert LIFECYCLE_EVENT_FOR_STATUS[RunStatus.PENDING] is None
    assert LIFECYCLE_EVENT_FOR_STATUS[RunStatus.WAITING_FOR_APPROVAL] is None
    assert LIFECYCLE_EVENT_FOR_STATUS[RunStatus.RUNNING] == EventType.RUN_STARTED


# ============================================================
# END: Table Shape
# ============================================================
# ============================================================
# BEGIN: Allowed Transitions
# ============================================================

#: Every legal edge, spelled out so a behavior change is visible as a data
#: change rather than as a silently altered table.
LEGAL_EDGES: list[tuple[RunStatus, RunStatus]] = [
    (RunStatus.PENDING, RunStatus.WAITING_FOR_APPROVAL),
    (RunStatus.PENDING, RunStatus.RUNNING),
    (RunStatus.PENDING, RunStatus.FAILED),
    (RunStatus.PENDING, RunStatus.CANCELLED),
    (RunStatus.WAITING_FOR_APPROVAL, RunStatus.RUNNING),
    (RunStatus.WAITING_FOR_APPROVAL, RunStatus.FAILED),
    (RunStatus.WAITING_FOR_APPROVAL, RunStatus.CANCELLED),
    (RunStatus.RUNNING, RunStatus.COMPLETED),
    (RunStatus.RUNNING, RunStatus.FAILED),
    (RunStatus.RUNNING, RunStatus.CANCELLED),
]


def test_the_legal_edge_list_is_the_table() -> None:
    """The spelled-out edges and the table are the same set of moves."""
    from_table = {
        (source, target)
        for source, targets in ALLOWED_TRANSITIONS.items()
        for target in targets
    }
    assert from_table == set(LEGAL_EDGES)


@pytest.mark.parametrize(
    ("source", "target"),
    LEGAL_EDGES,
    ids=[f"{source.value}-to-{target.value}" for source, target in LEGAL_EDGES],
)
def test_every_legal_transition_is_accepted(source: RunStatus, target: RunStatus) -> None:
    """A legal edge moves the run and records the fact that belongs to it."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [target for _, target in _path_to(source)])

    record = lifecycle.service.transition("run-1", target)

    assert record.status is target
    assert lifecycle.runs.get("run-1").status is target
    expected_event = LIFECYCLE_EVENT_FOR_STATUS[target]
    recorded = [event.event_type for event in lifecycle.events.get_events("run-1")]
    if expected_event is None:
        assert recorded == _events_for(_path_to(source))
    else:
        assert recorded == [*_events_for(_path_to(source)), expected_event]


def _path_to(status: RunStatus) -> list[tuple[RunStatus, RunStatus]]:
    """The canonical way to reach ``status`` from creation."""
    if status is RunStatus.PENDING:
        return []
    if status is RunStatus.WAITING_FOR_APPROVAL:
        return [(RunStatus.PENDING, RunStatus.WAITING_FOR_APPROVAL)]
    if status is RunStatus.RUNNING:
        return [(RunStatus.PENDING, RunStatus.RUNNING)]
    return [(RunStatus.PENDING, RunStatus.RUNNING), (RunStatus.RUNNING, status)]


def _events_for(path: list[tuple[RunStatus, RunStatus]]) -> list[EventType]:
    return [
        event
        for _, target in path
        if (event := LIFECYCLE_EVENT_FOR_STATUS[target]) is not None
    ]


def test_a_run_can_walk_pending_to_completed() -> None:
    """The whole successful path is legal and leaves one fact per move."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [RunStatus.RUNNING, RunStatus.COMPLETED])

    assert [event.event_type for event in lifecycle.events.get_events("run-1")] == [
        EventType.RUN_STARTED,
        EventType.RUN_COMPLETED,
    ]
    assert lifecycle.service.is_terminal("run-1")
    assert not lifecycle.service.is_active("run-1")


def test_a_run_can_wait_for_approval_and_then_run() -> None:
    """The approval gate is a real non-terminal state in the machine."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    lifecycle.service.transition("run-1", RunStatus.WAITING_FOR_APPROVAL)
    assert lifecycle.service.is_active("run-1")
    lifecycle.service.transition("run-1", RunStatus.RUNNING)
    assert lifecycle.runs.get("run-1").status is RunStatus.RUNNING


# ============================================================
# END: Allowed Transitions
# ============================================================
# ============================================================
# BEGIN: Illegal Transitions
# ============================================================

ILLEGAL_EDGES: list[tuple[RunStatus, RunStatus]] = [
    (source, target)
    for source in RunStatus
    for target in RunStatus
    if source is not target and target not in ALLOWED_TRANSITIONS[source]
]

#: The escapes the phase brief calls out explicitly, pinned by name.
NAMED_ILLEGAL_EDGES: list[tuple[RunStatus, RunStatus]] = [
    (RunStatus.COMPLETED, RunStatus.RUNNING),
    (RunStatus.COMPLETED, RunStatus.FAILED),
    (RunStatus.FAILED, RunStatus.RUNNING),
    (RunStatus.FAILED, RunStatus.COMPLETED),
    (RunStatus.CANCELLED, RunStatus.RUNNING),
    (RunStatus.CANCELLED, RunStatus.COMPLETED),
]


def test_the_illegal_edge_set_covers_every_escape() -> None:
    """Every terminal state is escapeless, which is most of the illegal set."""
    named = set(NAMED_ILLEGAL_EDGES)
    assert named <= set(ILLEGAL_EDGES)
    for status in TERMINAL_RUN_STATUSES:
        for target in RunStatus:
            if target is not status:
                assert (status, target) in set(ILLEGAL_EDGES)


@pytest.mark.parametrize(
    ("source", "target"),
    ILLEGAL_EDGES,
    ids=[f"{source.value}-to-{target.value}" for source, target in ILLEGAL_EDGES],
)
def test_every_illegal_transition_is_rejected(source: RunStatus, target: RunStatus) -> None:
    """An illegal move raises a typed error and changes nothing."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [target for _, target in _path_to(source)])
    before = lifecycle.runs.get("run-1")
    events_before = list(lifecycle.events.get_events("run-1"))

    with pytest.raises(InvalidRunTransitionError) as raised:
        lifecycle.service.transition("run-1", target)

    assert raised.value.run_id == "run-1"
    assert raised.value.from_status is source
    assert raised.value.to_status is target
    assert str(raised.value) == (
        f"Run 'run-1' cannot move from {source.value!r} to {target.value!r}"
    )
    assert lifecycle.runs.get("run-1") == before
    assert list(lifecycle.events.get_events("run-1")) == events_before


def test_an_illegal_transition_error_carries_no_execution_payload() -> None:
    """The rejection is safe to log: identifiers only."""
    error = InvalidRunTransitionError(
        run_id="run-7", from_status=RunStatus.COMPLETED, to_status=RunStatus.RUNNING
    )
    assert set(vars(error)) == {"run_id", "from_status", "to_status"}


def test_a_pending_run_cannot_jump_straight_to_completed() -> None:
    """There is no edge that skips execution."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    with pytest.raises(InvalidRunTransitionError) as raised:
        lifecycle.service.complete("run-1")
    assert raised.value.from_status is RunStatus.PENDING
    assert lifecycle.runs.get("run-1").status is RunStatus.PENDING


def test_a_completed_run_cannot_be_cancelled() -> None:
    """Late cancellation is rejected; completion stands."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [RunStatus.RUNNING, RunStatus.COMPLETED])

    with pytest.raises(InvalidRunTransitionError):
        lifecycle.service.cancel("run-1")

    assert lifecycle.runs.get("run-1").status is RunStatus.COMPLETED


# ============================================================
# END: Illegal Transitions
# ============================================================
# ============================================================
# BEGIN: Idempotence
# ============================================================


@pytest.mark.parametrize("status", list(RunStatus))
def test_repeating_a_status_is_an_idempotent_no_op(status: RunStatus) -> None:
    """Re-requesting the recorded state writes nothing and appends nothing.

    Idempotence is what a duplicated cancellation or a losing race needs: the
    outcome is already recorded, so the second request must not produce a second
    write, a second event, or a new ``updated_at``.
    """
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [target for _, target in _path_to(status)])
    before = lifecycle.runs.get("run-1")
    events_before = list(lifecycle.events.get_events("run-1"))

    record = lifecycle.service.transition("run-1", status)

    assert record == before
    assert lifecycle.runs.get("run-1") == before
    assert list(lifecycle.events.get_events("run-1")) == events_before


def test_repeated_cancellation_records_one_fact() -> None:
    """Two cancellation requests produce one ``run_cancelled`` event."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [RunStatus.RUNNING])

    lifecycle.service.cancel("run-1")
    lifecycle.service.cancel("run-1")

    terminal_events = [
        event
        for event in lifecycle.events.get_events("run-1")
        if event.event_type in TERMINAL_EVENT_TYPES
    ]
    assert [event.event_type for event in terminal_events] == [EventType.RUN_CANCELLED]


# ============================================================
# END: Idempotence
# ============================================================
# ============================================================
# BEGIN: Timestamps
# ============================================================


def test_created_at_is_written_once_and_never_rewritten() -> None:
    """Creation time is historical fact, not a "last touched" value."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    created = lifecycle.runs.get("run-1").created_at

    _drive(lifecycle, "run-1", [RunStatus.RUNNING, RunStatus.COMPLETED])
    lifecycle.runs.set_execution_selection("run-1", None)

    record = lifecycle.runs.get("run-1")
    assert record.created_at == created
    assert record.updated_at >= created


def test_each_accepted_transition_refreshes_updated_at() -> None:
    """``updated_at`` tracks the lifecycle, and only real moves touch it."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    seen = [lifecycle.runs.get("run-1").updated_at]

    for status in (RunStatus.RUNNING, RunStatus.COMPLETED):
        lifecycle.service.transition("run-1", status)
        seen.append(lifecycle.runs.get("run-1").updated_at)

    assert seen == sorted(seen)
    assert lifecycle.runs.get("run-1").updated_at == seen[-1]


def test_a_rejected_transition_leaves_timestamps_untouched() -> None:
    """Validation happens before any write, so nothing moves."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [RunStatus.RUNNING, RunStatus.COMPLETED])
    before = lifecycle.runs.get("run-1")

    with pytest.raises(InvalidRunTransitionError):
        lifecycle.service.transition("run-1", RunStatus.RUNNING)

    assert lifecycle.runs.get("run-1").updated_at == before.updated_at
    assert lifecycle.runs.get("run-1").created_at == before.created_at


def test_no_later_transition_moves_a_terminal_runs_timestamp() -> None:
    """Once a run settles, the lifecycle stops writing to it."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [RunStatus.RUNNING, RunStatus.FAILED])
    terminal_at = lifecycle.runs.get("run-1").updated_at

    with pytest.raises(InvalidRunTransitionError):
        lifecycle.service.transition("run-1", RunStatus.COMPLETED)
    lifecycle.service.transition("run-1", RunStatus.FAILED)

    assert lifecycle.runs.get("run-1").updated_at == terminal_at


def test_the_terminal_fact_records_the_moment_the_run_settled() -> None:
    """``updated_at`` is a generic last-write clock, so the event is the timestamp.

    A run has no dedicated terminal-time column, and a later non-status write
    (recording the resolved execution, say) legitimately refreshes
    ``updated_at``. The durable, write-once record of *when the run settled* is
    therefore the timestamp on its terminal lifecycle event.
    """
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [RunStatus.RUNNING, RunStatus.COMPLETED])
    terminal = [
        event
        for event in lifecycle.events.get_events("run-1")
        if event.event_type is EventType.RUN_COMPLETED
    ]
    assert len(terminal) == 1
    settled_at = terminal[0].timestamp

    # A non-status write moves ``updated_at`` but not the recorded moment.
    lifecycle.runs.set_execution_selection("run-1", None)
    assert lifecycle.runs.get("run-1").updated_at > settled_at

    # And the recorded moment itself can never be rewritten.
    assert [
        event.timestamp
        for event in lifecycle.events.get_events("run-1")
        if event.event_type is EventType.RUN_COMPLETED
    ] == [settled_at]


# ============================================================
# END: Timestamps
# ============================================================
# ============================================================
# BEGIN: Unknown Runs
# ============================================================


def test_transitioning_an_unknown_run_is_reported_distinctly() -> None:
    """A missing run is not an illegal move between real states."""
    lifecycle = _lifecycle()
    for transition in (
        lifecycle.service.start,
        lifecycle.service.complete,
        lifecycle.service.fail,
        lifecycle.service.cancel,
    ):
        with pytest.raises(UnknownRunError) as raised:
            transition("ghost")
        assert raised.value.run_id == "ghost"


def test_lifecycle_helpers_cover_every_transition_with_an_event() -> None:
    """The named helpers and the generic transition share one legality model."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    lifecycle.service.start("run-1")
    lifecycle.service.fail("run-1", payload={"error_code": "agent_failed"})

    events = lifecycle.events.get_events("run-1")
    assert [event.event_type for event in events] == [
        EventType.RUN_STARTED,
        EventType.RUN_FAILED,
    ]
    assert events[-1].payload == {"error_code": "agent_failed"}


# ============================================================
# END: Unknown Runs
# ============================================================
# ============================================================
# BEGIN: One Terminal State Wins
# ============================================================


def test_a_stale_status_write_is_refused_rather_than_overwriting() -> None:
    """The guard is the guarantee that one terminal state can win.

    A writer that observed ``running`` cannot land ``completed`` on a run that
    has already become ``cancelled``: the compare-and-swap matches zero rows and
    the losing write does not happen at all.
    """
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [RunStatus.RUNNING])
    runs = lifecycle.runs

    assert (
        runs.compare_and_set_status(
            "run-1", expected_status=RunStatus.RUNNING, status=RunStatus.CANCELLED
        )
        is not None
    )
    assert (
        runs.compare_and_set_status(
            "run-1", expected_status=RunStatus.RUNNING, status=RunStatus.COMPLETED
        )
        is None
    )
    assert runs.get("run-1").status is RunStatus.CANCELLED


def test_a_guarded_write_to_an_unknown_run_is_refused() -> None:
    lifecycle = _lifecycle()
    assert (
        lifecycle.runs.compare_and_set_status(
            "ghost", expected_status=RunStatus.RUNNING, status=RunStatus.COMPLETED
        )
        is None
    )


def test_a_transition_that_lost_the_race_reports_the_persisted_winner() -> None:
    """A caller whose move lost is told what actually happened.

    Simulates the window between the lifecycle's read and its guarded write:
    another writer settles the run first. The late completion must not report
    success, and the error must name the state that really persisted.
    """
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [RunStatus.RUNNING])
    def cancel_underneath(run_id, *, expected_status, status):
        del expected_status, status
        # The competing writer wins the guard outright: this write matches no
        # rows because the run is no longer ``running``.
        lifecycle.runs.update_status(run_id, RunStatus.CANCELLED)
        return None

    lifecycle.runs.compare_and_set_status = cancel_underneath  # type: ignore[method-assign]
    with pytest.raises(InvalidRunTransitionError) as raised:
        lifecycle.service.complete("run-1")

    assert raised.value.from_status is RunStatus.CANCELLED
    assert raised.value.to_status is RunStatus.COMPLETED
    assert lifecycle.runs.get("run-1").status is RunStatus.CANCELLED
    assert [event.event_type for event in lifecycle.events.get_events("run-1")] == [
        EventType.RUN_STARTED
    ]


def test_a_race_the_run_already_reached_is_success_not_failure() -> None:
    """Converging on the same state is not an error, and never double-records."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    _drive(lifecycle, "run-1", [RunStatus.RUNNING])
    def complete_underneath(run_id, *, expected_status, status):
        del expected_status
        # The guard is lost, but the run reached the requested state anyway.
        if lifecycle.runs.get(run_id).status is not status:
            lifecycle.runs.update_status(run_id, status)
        return None

    lifecycle.runs.compare_and_set_status = complete_underneath  # type: ignore[method-assign]
    record = lifecycle.service.complete("run-1")

    assert record.status is RunStatus.COMPLETED
    assert [event.event_type for event in lifecycle.events.get_events("run-1")] == [
        EventType.RUN_STARTED
    ]


# ============================================================
# END: One Terminal State Wins
# ============================================================
# ============================================================
# BEGIN: Reported Terminal Statuses
# ============================================================


@pytest.mark.parametrize(
    ("reported", "expected_event"),
    [
        (RunStatus.COMPLETED, EventType.RUN_COMPLETED),
        (RunStatus.FAILED, EventType.RUN_FAILED),
        (RunStatus.CANCELLED, EventType.RUN_CANCELLED),
    ],
)
def test_a_reported_terminal_status_is_recorded_with_its_own_fact(
    reported: RunStatus, expected_event: EventType
) -> None:
    """Whatever execution reports, the run reaches it durably and factually."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    lifecycle.service.start("run-1")

    record = lifecycle.service.record_reported_terminal("run-1", reported)

    assert record.status is reported
    assert [event.event_type for event in lifecycle.events.get_events("run-1")] == [
        EventType.RUN_STARTED,
        expected_event,
    ]


def test_a_reported_failure_carries_the_callers_payload() -> None:
    """The lifecycle owns the transition; the caller owns what it says."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    lifecycle.service.start("run-1")

    lifecycle.service.record_reported_terminal(
        "run-1", RunStatus.FAILED, payload={"error_code": "context_window_exceeded"}
    )

    failed = [
        event
        for event in lifecycle.events.get_events("run-1")
        if event.event_type is EventType.RUN_FAILED
    ]
    assert failed[0].payload == {"error_code": "context_window_exceeded"}


@pytest.mark.parametrize("status", [RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_FOR_APPROVAL])
def test_a_reported_non_terminal_status_is_a_caller_bug(status: RunStatus) -> None:
    """Reporting "still working" is not a lifecycle event."""
    lifecycle = _lifecycle()
    _run(lifecycle)
    lifecycle.service.start("run-1")

    with pytest.raises(ValueError, match="not terminal"):
        lifecycle.service.record_reported_terminal("run-1", status)

    assert lifecycle.runs.get("run-1").status is RunStatus.RUNNING
    assert [event.event_type for event in lifecycle.events.get_events("run-1")] == [
        EventType.RUN_STARTED
    ]


# ============================================================
# END: Reported Terminal Statuses
# ============================================================
# ============================================================
# BEGIN: Vocabulary Authority
# ============================================================


def test_the_frontend_status_union_matches_the_backend_enum() -> None:
    """The frontend consumes the backend's vocabulary; it does not define one.

    A backend status that the shared TypeScript contract does not know would
    reach the UI as an untyped value, so the two lists are pinned together here
    rather than trusted to review. The complementary guard — that no backend
    module bypasses the transition authority — lives in ``test_architecture.py``
    with the other layering checks.
    """
    source = (_REPO_ROOT / "frontend" / "packages" / "contracts" / "src" / "runs.ts").read_text(
        encoding="utf-8"
    )
    union = re.search(r"export type RunStatus =(.*?);", source, re.DOTALL)
    assert union is not None
    declared = set(re.findall(r'"([a-z_]+)"', union.group(1)))
    assert declared == {status.value for status in RunStatus}


# ============================================================
# END: Vocabulary Authority
# ============================================================
