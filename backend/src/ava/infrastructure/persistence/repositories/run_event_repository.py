"""SQLite-backed run-event repository adapter (Step 4.6).

Implements the AVA ``RunEventRepository`` port over the shared
``SqliteDatabase``. Behavioral parity with the in-memory ``RunEventStore``:

* events are stored per run in append order via an explicit monotonic sequence
  (``seq``), never timestamp ordering;
* at most one terminal event per run: the adapter checks in-transaction before
  inserting and the ``idx_run_events_one_terminal`` partial unique index backs
  that invariant at the database level;
* a terminal event for an already-terminal run is ignored (idempotent);
* the event payload and timestamp round-trip through deterministic JSON text
  and ISO-8601 UTC strings.
"""

import sqlite3

from ava.contracts.events import RunEvent
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import dump_json, row_to_run_event, to_utc_iso
from ava.repositories.run_event_repository import TERMINAL_EVENT_TYPES, RunEventRepository

_EVENT_COLUMNS = "event_id, run_id, event_type, seq, \"timestamp\", payload, contract_version"

_TERMINAL_VALUES: tuple[str, ...] = tuple(sorted(event_type.value for event_type in TERMINAL_EVENT_TYPES))
_TERMINAL_PLACEHOLDERS: str = ",".join("?" for _ in _TERMINAL_VALUES)
_TERMINAL_EXISTS_SQL: str = (
    "SELECT 1 FROM run_events WHERE run_id = ? AND event_type IN "
    f"({_TERMINAL_PLACEHOLDERS}) LIMIT 1"
)

# ============================================================
# BEGIN: Relational Run Event Repository
# ============================================================


class RelationalRunEventRepository(RunEventRepository):
    """SQLite-backed implementation of the run-event repository port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def append(self, event: RunEvent) -> RunEvent:
        stored: RunEvent | None = None
        try:
            with self._database.transaction() as connection:
                if event.event_type in TERMINAL_EVENT_TYPES:
                    terminal = connection.execute(
                        _TERMINAL_EXISTS_SQL,
                        (event.run_id, *_TERMINAL_VALUES),
                    ).fetchone()
                    if terminal is not None:
                        return event
                seq = connection.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM run_events WHERE run_id = ?",
                    (event.run_id,),
                ).fetchone()
                connection.execute(
                    "INSERT INTO run_events (event_id, run_id, event_type, seq, \"timestamp\", "
                    "payload, contract_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.run_id,
                        event.event_type.value,
                        int(seq[0]),
                        to_utc_iso(event.timestamp),
                        dump_json(event.payload),
                        event.contract_version,
                    ),
                )
                row = connection.execute(
                    f"SELECT {_EVENT_COLUMNS} FROM run_events WHERE event_id = ?",
                    (event.event_id,),
                ).fetchone()
                stored = row_to_run_event(row) if row is not None else None
        except sqlite3.Error as exc:
            if event.event_type in TERMINAL_EVENT_TYPES:
                return event
            raise translate_database_error(exc, entity="Run event", key=event.event_id) from exc
        # Ports preserve their existing return contract (the caller's input).
        # Reads expose the persisted cursor used by the transport.
        del stored
        return event

    def get_events(self, run_id: str) -> list[RunEvent]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_EVENT_COLUMNS} FROM run_events WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ).fetchall()
        return [row_to_run_event(row) for row in rows]

    def list_after_sequence(self, run_id: str, after_sequence: int) -> list[RunEvent]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_EVENT_COLUMNS} FROM run_events "
                "WHERE run_id = ? AND seq > ? ORDER BY seq ASC",
                (run_id, after_sequence),
            ).fetchall()
        return [row_to_run_event(row) for row in rows]

    def get_latest(self, run_id: str) -> RunEvent | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_EVENT_COLUMNS} FROM run_events WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return row_to_run_event(row) if row is not None else None


# ============================================================
# END: Relational Run Event Repository
# ============================================================
