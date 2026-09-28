"""In-memory AVA run event store.

Stores normalized ``RunEvent`` records per run so events are retrievable
independently of the concrete agent. This is Sprint 2 in-memory state only:
no database, Redis, Kafka, queue, or event-bus framework.

The store also enforces a single-terminal-event invariant per run: an
already-terminal run refuses a second terminal event (``run_completed``,
``run_cancelled``, ``run_failed``). This keeps the lifecycle deterministic.
"""

from ava.contracts.events import RunEvent
from ava.repositories.run_event_repository import (
    TERMINAL_EVENT_TYPES,
    RunEventRepository,
)

# ============================================================
# BEGIN: Run Event Store
# ============================================================


class RunEventStore(RunEventRepository):
    """In-memory, AVA-owned store of run events keyed by run id.

    This is the in-memory ``RunEventRepository`` implementation used by the
    current composition. Sprint 2 state only: no database, Redis, Kafka,
    queue, or event-bus framework.
    """

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
        stored = event.model_copy(update={"sequence": len(existing) + 1})
        self._events.setdefault(event.run_id, []).append(stored)
        return stored

    def get_events(self, run_id: str) -> list[RunEvent]:
        """Return the events for ``run_id`` in append order.

        An unknown run yields an empty list; run existence is the caller's
        concern (see the run store).
        """
        return list(self._events.get(run_id, []))

    def list_after_sequence(self, run_id: str, after_sequence: int) -> list[RunEvent]:
        """Return the run's ordered facts strictly after an exclusive cursor."""
        return [event for event in self._events.get(run_id, []) if event.sequence > after_sequence]

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
