"""AVA-owned run event persistence repository port.

Expresses the run-event semantics currently owned by ``RunEventStore`` so
durable implementations (Step 4.3+) can satisfy the same contract without
changing event lifecycle behavior.

Events are appended per run in original order and retrieved as immutable
snapshots in append order. Each run permits at most one terminal event
(``run_completed``, ``run_cancelled``, ``run_failed``): a second terminal
event for an already-terminal run is ignored (idempotent), keeping the
lifecycle deterministic and preserving current ``RunService`` behavior.

The port is deliberately framework-neutral: no SQL, ORM entities, sessions,
transactions, queries, rows, queues, or streaming. Phase 5 handles
streaming/reconnect. Event and run identifiers are AVA-owned and supplied on
the ``RunEvent`` contract; a repository never mints them.
"""

from abc import ABC, abstractmethod
from collections.abc import Collection

from ava.contracts.events import EventType, RunEvent

#: Event types that terminate a run's event lifecycle. One canonical definition
#: shared by the port, the in-memory store, and the durable adapters.
TERMINAL_EVENT_TYPES: frozenset[EventType] = frozenset(
    {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}
)

# ============================================================
# BEGIN: Run Event Repository
# ============================================================


class RunEventRepository(ABC):
    """Port that durable run-event repositories must satisfy.

    Responsibilities mirror the existing ``RunEventStore`` semantics:

    * ``append`` — append a ``RunEvent`` to its run in original order,
      tolerating (ignoring) a terminal event for an already-terminal run.
    * ``get_events`` — return the run's events in append order, or ``[]`` for
      an unknown run.
    * ``list_after_sequence`` — replay facts after an exclusive per-run cursor.
    * ``get_latest`` — return the most recently appended event, if any.

    Terminal-event enforcement is expressed by ``TERMINAL_EVENT_TYPES`` and the
    idempotent-append invariant documented on ``append``; implementations own
    the mechanism (in-memory guard, database constraint, …) but must honor the
    same observable semantics.

    Deliberately not part of this port: ``clear``/list observability helpers,
    transport streaming, lifecycle reconstruction, and any event schema beyond
    ``RunEvent``.
    """

    @abstractmethod
    def append(self, event: RunEvent) -> RunEvent:
        """Append an event to its run in original order.

        A terminal event for a run that already has a terminal event is ignored
        (idempotent), preventing conflicting or duplicate terminal sequences.

        Args:
            event: The AVA-owned ``RunEvent`` to append.

        Returns:
            The persisted event, including its allocated sequence. A
            terminal-ignored append reports the input without storing it.
        """
        raise NotImplementedError

    @abstractmethod
    def get_events(self, run_id: str) -> Collection[RunEvent]:
        """Return the run's events in append order.

        Args:
            run_id: The AVA-generated run identifier.

        Returns:
            Ordered immutable snapshot of the run's events. An unknown run
            yields an empty collection; run existence is the caller's concern
            (see ``RunRepository``).
        """
        raise NotImplementedError

    @abstractmethod
    def list_after_sequence(self, run_id: str, after_sequence: int) -> Collection[RunEvent]:
        """Return persisted facts whose per-run sequence is strictly newer.

        ``after_sequence`` is an exclusive cursor. Zero returns a run's full
        log; a cursor ahead of the log returns an empty snapshot.
        """
        raise NotImplementedError

    @abstractmethod
    def get_latest(self, run_id: str) -> RunEvent | None:
        """Return the most recently appended event for ``run_id``, if any.

        Args:
            run_id: The AVA-generated run identifier.

        Returns:
            The latest event snapshot, or ``None`` when the run has no events.
        """
        raise NotImplementedError


# ============================================================
# END: Run Event Repository
# ============================================================
