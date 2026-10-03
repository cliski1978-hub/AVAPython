"""AVA's single authority for durable run-state transitions.

Phase 5.23 normalizes *how* a run moves through lifecycle states. Before this
module, ``RunService`` called ``RunRepository.update_status`` directly at five
sites, legality was implicit in the shape of the code, and a terminal run could
be silently rewritten (a late completion could overwrite a cancellation that had
already won). The vocabulary existed (``RunStatus``) but the state machine did
not.

This module is the state machine. It owns:

* the allowed-transition table (:data:`ALLOWED_TRANSITIONS`) — one table, not
  one rule per caller;
* validation, via :class:`InvalidRunTransitionError`, for every transition that
  is not allowed;
* the write itself, so exactly one production path can change a run's status;
* the lifecycle event that belongs to a transition, so a run cannot reach a new
  status without the matching durable fact;
* durable *cancellation intent* (Phase 5.24) — recorded here so that "someone
  asked for this to stop" survives a process that dies before any runtime
  acknowledges it. Intent is not a status: it has no entry in the table above,
  and only ``RunStatus.CANCELLED`` means a run actually stopped.

Three properties are deliberate and load-bearing:

1. **The status is the authority and is written first.** A lifecycle event is
   the durable fact *of* a transition, so it is appended only after the status
   write succeeded. Divergence can therefore only ever be a *missing* event,
   never an event that contradicts the authoritative state — a consumer of
   events can never believe something ``Run.status`` denies. A single
   cross-repository transaction does not exist in the current repository design,
   so that ordering is the strongest available guarantee; Phase 5.26 owns
   stronger event guarantees.
2. **Repeating a transition that has already happened is a no-op, not an
   error.** Idempotence is what production actually needs: a racing
   complete/cancel pair and a duplicated cancellation request both legitimately
   re-request a terminal state that is already recorded, and the run-event port
   is already idempotent for terminal events. A no-op writes nothing, appends
   no event, and does not disturb ``updated_at``.
3. **Legality is checked against the persisted state, and the write is guarded
   against it.** The record is re-read inside the transition, and the write is a
   compare-and-swap on the status that read observed. So two concurrent writers
   cannot both believe they were first: the database decides, the first terminal
   write wins, and the loser is told what actually happened rather than
   overwriting it. Validating against a plain read would leave a window in which
   a late completion could still clobber a cancellation that had already won.

The repositories stay persistence-oriented. ``update_status`` remains a blind
primitive — this module, not the repository, decides whether a write is legal.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

from ava.contracts.events import EventType, RunEvent
from ava.contracts.json_types import JsonValue
from ava.contracts.responses import RunStatus
from ava.repositories.run_event_repository import RunEventRepository
from ava.repositories.run_repository import RunRecord, RunRepository

logger = logging.getLogger(__name__)

# ============================================================
# BEGIN: Transition Table
# ============================================================

#: The canonical run state machine: for every status, the statuses a run may
#: legally move to. A terminal status maps to an empty set — no run leaves a
#: terminal state, which is what makes late completions and post-cancel writes
#: rejections rather than silent overwrites.
#:
#: ``pending`` may also reach ``waiting_for_approval``. No production code
#: writes that status yet; the edge exists so the published vocabulary is
#: internally consistent and an approvals flow will not have to edit the table.
ALLOWED_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = MappingProxyType(
    {
        RunStatus.PENDING: frozenset(
            {
                RunStatus.WAITING_FOR_APPROVAL,
                RunStatus.RUNNING,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }
        ),
        RunStatus.WAITING_FOR_APPROVAL: frozenset({RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}),
        RunStatus.RUNNING: frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}),
        RunStatus.COMPLETED: frozenset(),
        RunStatus.FAILED: frozenset(),
        RunStatus.CANCELLED: frozenset(),
    }
)

#: The lifecycle event each status transition must produce. A status missing
#: from this mapping (``pending``, ``waiting_for_approval``) has no lifecycle
#: event in the current event vocabulary, so such a transition writes the status
#: only. Keeping the mapping here is what stops a run from reaching a status
#: whose event a caller forgot to emit.
LIFECYCLE_EVENT_FOR_STATUS: Mapping[RunStatus, EventType | None] = MappingProxyType(
    {
        RunStatus.PENDING: None,
        RunStatus.WAITING_FOR_APPROVAL: None,
        RunStatus.RUNNING: EventType.RUN_STARTED,
        RunStatus.COMPLETED: EventType.RUN_COMPLETED,
        RunStatus.FAILED: EventType.RUN_FAILED,
        RunStatus.CANCELLED: EventType.RUN_CANCELLED,
    }
)

# ============================================================
# END: Transition Table
# ============================================================
# ============================================================
# BEGIN: Invalid Transition Error
# ============================================================


class InvalidRunTransitionError(ValueError):
    """A run was asked to move to a status its current state does not allow.

    A deterministic, typed rejection rather than a best-effort write. Reaching
    it means the caller and the authoritative state disagree — most often a late
    completion or a duplicated cancellation losing a race. The error carries the
    three safe identifiers needed to diagnose it and nothing else: no prompt
    content, no provider payload, no credentials.
    """

    def __init__(self, *, run_id: str, from_status: RunStatus, to_status: RunStatus) -> None:
        """Record the rejected transition.

        Args:
            run_id: The run whose transition was rejected.
            from_status: The status the run is authoritatively in.
            to_status: The status the caller asked for.
        """
        self.run_id = run_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Run {run_id!r} cannot move from {from_status.value!r} to {to_status.value!r}")


# ============================================================
# END: Invalid Transition Error
# ============================================================
class UnknownRunError(ValueError):
    """A lifecycle transition named a run that does not exist.

    Separate from :class:`InvalidRunTransitionError` on purpose: a missing run
    is a caller/orchestration problem, not an illegal move between two real
    states, and the two deserve different handling.
    """

    def __init__(self, run_id: str) -> None:
        """Record the unknown run identifier."""
        self.run_id = run_id
        super().__init__(f"Unknown run: {run_id}")


# ============================================================
# BEGIN: Run Lifecycle Service
# ============================================================


class RunLifecycleService:
    """The one writer of durable run lifecycle state.

    Every production path that changes a run's status goes through
    :meth:`transition` (directly or through the named helpers below). The
    service holds no run objects, caches no state, and makes no decisions about
    *why* a run should end: it validates the move against the persisted record
    and performs the write plus its lifecycle event.
    """

    def __init__(
        self,
        *,
        run_repository: RunRepository,
        run_event_repository: RunEventRepository,
    ) -> None:
        """Construct the lifecycle authority over the run and event ports.

        Args:
            run_repository: Persistence for run records. Used as a blind store;
                no legality is enforced here.
            run_event_repository: Persistence for run events, including the
                lifecycle event that accompanies each transition.
        """
        self._runs = run_repository
        self._events = run_event_repository

    # ============================================================
    # BEGIN: Reads
    # ============================================================

    def get(self, run_id: str) -> RunRecord | None:
        """Return the authoritative run snapshot, or ``None`` when unknown."""
        return self._runs.get(run_id)

    def is_active(self, run_id: str) -> bool:
        """Whether the persisted run is still in progress."""
        record = self._runs.get(run_id)
        return record is not None and record.status.is_active

    def is_terminal(self, run_id: str) -> bool:
        """Whether the persisted run has reached a final state."""
        record = self._runs.get(run_id)
        return record is not None and record.status.is_terminal

    # ============================================================
    # END: Reads
    # ============================================================
    # ============================================================
    # BEGIN: Creation
    # ============================================================

    def create_run(
        self,
        run_id: str,
        *,
        conversation_id: str | None = None,
        source_user_message_id: str | None = None,
    ) -> RunRecord:
        """Open a run in ``pending``.

        ``pending`` is the only state a run is ever created in, and
        ``created_at`` is written once here and never rewritten. The repository
        remains the owner of the timestamp values; this method exists so that
        run creation is part of the same authority as every later transition,
        and so no other component can invent a different initial state.
        """
        return self._runs.create(
            run_id,
            conversation_id=conversation_id,
            source_user_message_id=source_user_message_id,
        )

    # ============================================================
    # END: Creation
    # ============================================================
    # ============================================================
    # BEGIN: Named Transitions
    # ============================================================

    def start(self, run_id: str) -> RunRecord:
        """Move a run to ``running`` — the point it is actively executing.

        This is the dispatch point, not request acceptance: the run service calls
        it immediately before handing the request to the agent, so a run spends
        as little of its life as possible in a state that claims to be executing
        without executing. Queuing, resource waiting, and approval gating are
        separate concerns; ``pending`` and ``waiting_for_approval`` cover them.
        """
        return self.transition(run_id, RunStatus.RUNNING)

    def complete(self, run_id: str) -> RunRecord:
        """Move a run to ``completed`` and record the completion fact.

        The caller must have persisted the final assistant content first: a
        completed run whose response is missing is the inconsistency this
        ordering exists to prevent.
        """
        return self.transition(run_id, RunStatus.COMPLETED)

    def fail(self, run_id: str, *, payload: Mapping[str, JsonValue] | None = None) -> RunRecord:
        """Move a run to ``failed``.

        ``payload`` carries the run's failure event body (a stable error code
        and a safe message). The caller decides what the payload says; the
        lifecycle only decides that every failure — configuration, context
        window, provider, or runtime — lands in the same terminal state, because
        the lifecycle has no reason to distinguish them.
        """
        return self.transition(run_id, RunStatus.FAILED, payload=payload)

    def cancel(self, run_id: str) -> RunRecord:
        """Move a run to ``cancelled`` and record the cancellation fact."""
        return self.transition(run_id, RunStatus.CANCELLED)

    def record_reported_terminal(
        self,
        run_id: str,
        status: RunStatus,
        *,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> RunRecord:
        """Record a terminal status an agent or runtime reported for a live run.

        An execution boundary answers with an AVA-level status, and the run it
        describes has to reach that same status durably — with its matching
        lifecycle fact. Dispatching here rather than in the caller is what keeps
        the terminal set in one place: a caller cannot handle three terminal
        states one way and a fourth another way, or quietly forget one.

        Args:
            run_id: The run that reported the terminal status.
            status: The reported terminal status.
            payload: Optional body for the ``run_failed`` fact, ignored by the
                transitions that carry no payload.

        Raises:
            ValueError: If ``status`` is not terminal. A reported non-terminal
                state is a caller bug, not a lifecycle event.
            UnknownRunError: If the run does not exist.
            InvalidRunTransitionError: If another writer already settled the run.
        """
        if not status.is_terminal:
            raise ValueError(f"Reported status is not terminal: {status.value}")
        if status is RunStatus.COMPLETED:
            return self.complete(run_id)
        if status is RunStatus.FAILED:
            return self.fail(run_id, payload=payload)
        return self.cancel(run_id)

    # ============================================================
    # END: Named Transitions
    # ============================================================
    # ============================================================
    # BEGIN: Cancellation Intent
    # ============================================================

    def request_cancellation(
        self,
        run_id: str,
        *,
        requested_at: datetime | None = None,
    ) -> RunRecord:
        """Record that someone asked for this run to stop.

        This is intent, not an outcome, and it is the reason a cancel survives a
        process that dies before the runtime ever acknowledges it. The request is
        persisted *before* any attempt to stop execution, so the order in which
        AVA does the two things can never lose the first one.

        A run that has already settled is returned untouched: it is never
        retroactively marked as having been cancelled on purpose, because the
        request would have arrived too late to be true. A second request keeps
        the first request's timestamp — three clicks are one request, and the
        moment the user first asked does not move because they clicked again.

        Args:
            run_id: The run to request cancellation of.
            requested_at: The moment of the request; the repository's clock when
                omitted. Tests pass one to make the durable value deterministic.

        Returns:
            The run record carrying the cancellation request, which is the
            unchanged record when the run had already settled or already had a
            request.

        Raises:
            UnknownRunError: If the run does not exist.
        """
        record = self._runs.get(run_id)
        if record is None:
            raise UnknownRunError(run_id)
        if not record.status.is_active:
            logger.debug(
                "Run %s is already %s; cancellation request ignored",
                run_id,
                record.status.value,
            )
            return record
        updated = self._runs.request_cancellation(run_id, requested_at=requested_at or datetime.now(UTC))
        if updated is None:
            # The guard declined: either the run settled between the read and the
            # write, or another request already recorded one. Both cases leave
            # the first truth standing, so re-read rather than force a write.
            settled = self._runs.get(run_id)
            if settled is None:  # pragma: no cover - the run existed a moment ago
                raise UnknownRunError(run_id)
            logger.debug(
                "Run %s already has cancellation intent as %s",
                run_id,
                settled.status.value,
            )
            return settled
        # The request is durable before anything tries to act on it, so the fact
        # is appended after the field rather than instead of it.
        try:
            self._append_lifecycle_event(run_id, EventType.RUN_CANCEL_REQUESTED, None)
        except Exception:
            # Intent already committed. An observation failure must not prevent
            # the best-effort runtime stop; transactional events belong to 5.26.
            logger.exception("Cancellation request event unavailable for run %s", run_id)
        return updated

    # ============================================================
    # END: Cancellation Intent
    # ============================================================
    # ============================================================
    # BEGIN: Transition
    # ============================================================

    def transition(
        self,
        run_id: str,
        to_status: RunStatus,
        *,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> RunRecord:
        """Validate and persist one lifecycle transition.

        Args:
            run_id: The run to transition.
            to_status: The requested status.
            payload: Optional body for the lifecycle event this transition
                produces.

        Timestamp values are the repository's to write: the lifecycle authority
        never invents ``updated_at`` itself, which keeps one clock in the
        persistence layer.

        Returns:
            The run record after the transition, the unchanged record when the
            run is already in ``to_status``, or the record another writer
            converged on when it made the very same move.

        Raises:
            UnknownRunError: If the run does not exist.
            InvalidRunTransitionError: If the transition is not allowed from the
                run's authoritative status, or if another writer moved the run
                somewhere else first.
        """
        record = self._runs.get(run_id)
        if record is None:
            raise UnknownRunError(run_id)
        if record.status is to_status:
            # Idempotent: the requested state is already the authoritative one.
            # Nothing is written and no duplicate lifecycle event is appended,
            # which is also what the run-event port requires for terminal facts.
            logger.debug("Run %s is already %s", run_id, to_status.value)
            return record
        if to_status not in ALLOWED_TRANSITIONS[record.status]:
            raise InvalidRunTransitionError(run_id=run_id, from_status=record.status, to_status=to_status)
        updated = self._runs.compare_and_set_status(run_id, expected_status=record.status, status=to_status)
        if updated is None:
            # The guarded write lost: another writer moved the run between the
            # read and the write. Re-read to say what actually happened instead
            # of assuming this caller's move was the one that landed.
            return self._resolve_lost_race(run_id, to_status)
        event_type = LIFECYCLE_EVENT_FOR_STATUS[to_status]
        if event_type is not None:
            self._append_lifecycle_event(run_id, event_type, payload)
        logger.debug("Run %s moved from %s to %s", run_id, record.status.value, to_status.value)
        return updated

    def _resolve_lost_race(self, run_id: str, to_status: RunStatus) -> RunRecord:
        """Report the outcome that actually persisted after a lost race.

        Landing on ``to_status`` is success, not failure: the run reached the
        state this caller asked for, so the fact it needs has been recorded by
        the writer that won and re-appending it would duplicate a terminal
        event. Anything else is a genuine rejection.
        """
        current = self._runs.get(run_id)
        if current is None:
            raise UnknownRunError(run_id)
        if current.status is to_status:
            logger.info("Run %s reached %s via another writer", run_id, to_status.value)
            return current
        raise InvalidRunTransitionError(run_id=run_id, from_status=current.status, to_status=to_status)

    def _append_lifecycle_event(
        self,
        run_id: str,
        event_type: EventType,
        payload: Mapping[str, JsonValue] | None,
    ) -> None:
        """Append the durable fact for a transition that has already persisted.

        Called only after the status write succeeded. Event identity is
        AVA-owned here, exactly as it is for message events, so a lifecycle
        fact is as well-formed as any other event.
        """
        self._events.append(
            RunEvent(
                event_id=str(uuid4()),
                run_id=run_id,
                event_type=event_type,
                payload=dict(payload or {}),
            )
        )

    # ============================================================
    # END: Transition
    # ============================================================


# ============================================================
# END: Run Lifecycle Service
# ============================================================

__all__ = [
    "ALLOWED_TRANSITIONS",
    "LIFECYCLE_EVENT_FOR_STATUS",
    "InvalidRunTransitionError",
    "RunLifecycleService",
    "UnknownRunError",
]
