"""In-memory AVA run event store.

Stores normalized ``RunEvent`` records per run so events are retrievable
independently of the concrete agent. This is Sprint 2 in-memory state only:
no database, Redis, Kafka, queue, or event-bus framework.

The store also enforces a single-terminal-event invariant per run: an
already-terminal run refuses a second terminal event (``run_completed``,
``run_cancelled``, ``run_failed``). This keeps the lifecycle deterministic.
"""

from ava.contracts.events import EventType, RunEvent

#: Event types that terminate a run's event lifecycle.
TERMINAL_EVENT_TYPES = frozenset(
    {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}
)

# ============================================================
# BEGIN: Run Event Store
# ============================================================


class RunEventStore:
    """In-memory, AVA-owned store of run events keyed by run id."""

    def __init__(self) -> None:
        self._events: dict[str, list[RunEvent]] = {}

    def append(self, event: RunEvent) -> RunEvent:
        """Append an event to its run in original order.

        A terminal event for a run that already has a terminal event is
        ignored (idempotent), preventing conflicting or duplicate terminal
        event sequences.

        Args:
            event: The AVA-owned ``RunEvent`` to append.

        Returns:
            The appended event.
        """
        existing = self._events.get(event.run_id, [])
        if event.event_type in TERMINAL_EVENT_TYPES and any(
            other.event_type in TERMINAL_EVENT_TYPES for other in existing
        ):
            return event
        self._events.setdefault(event.run_id, []).append(event)
        return event

    def get_events(self, run_id: str) -> list[RunEvent]:
        """Return the events for ``run_id`` in append order.

        An unknown run yields an empty list; run existence is the caller's
        concern (see the run store).
        """
        return list(self._events.get(run_id, []))

    def get_latest(self, run_id: str) -> RunEvent | None:
        """Return the most recently appended event for ``run_id``, if any."""
        events = self._events.get(run_id)
        return events[-1] if events else None

    def clear(self) -> None:
        """Remove all events (test/observability helper)."""
        self._events.clear()


# ============================================================
# END: Run Event Store
# ============================================================