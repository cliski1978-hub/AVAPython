"""SQLite-backed run repository adapter (Step 4.6).

Implements the AVA ``RunRepository`` port over the shared ``SqliteDatabase``.
Behavioral parity with the in-memory ``RunStore``: duplicates raise
``ValueError``, unknown runs return ``None``, updates refresh ``updated_at``.
"""

import sqlite3
from datetime import UTC, datetime

from ava.contracts.execution import RunExecutionSelection
from ava.contracts.responses import ACTIVE_RUN_STATUSES, RunStatus
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import (
    dump_execution_selection,
    row_to_run_record,
    to_utc_iso,
)
from ava.repositories.run_repository import ActiveConversationRunError, RunRecord, RunRepository

_RUN_COLUMNS = (
    "run_id, status, created_at, updated_at, execution_selection, conversation_id, "
    "source_user_message_id, assistant_message_id, cancellation_requested_at"
)

#: The statuses a run may still hold when a cancellation request arrives. A
#: settled run is never marked as having been cancelled on purpose: the request
#: would have arrived too late to be true.
_ACTIVE_STATUS_VALUES: tuple[str, ...] = tuple(status.value for status in ACTIVE_RUN_STATUSES)

# ============================================================
# BEGIN: Relational Run Repository
# ============================================================


class RelationalRunRepository(RunRepository):
    """SQLite-backed implementation of the run repository port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(
        self,
        run_id: str,
        *,
        conversation_id: str | None = None,
        source_user_message_id: str | None = None,
    ) -> RunRecord:
        now = datetime.now(UTC)
        try:
            with self._database.transaction() as connection:
                if conversation_id is not None:
                    placeholders = ", ".join("?" for _ in _ACTIVE_STATUS_VALUES)
                    active = connection.execute(
                        f"SELECT 1 FROM runs WHERE conversation_id = ? AND status IN ({placeholders}) LIMIT 1",
                        (conversation_id, *_ACTIVE_STATUS_VALUES),
                    ).fetchone()
                    if active is not None:
                        raise ActiveConversationRunError(conversation_id)
                connection.execute(
                    "INSERT INTO runs (run_id, status, created_at, updated_at, conversation_id, "
                    "source_user_message_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        RunStatus.PENDING.value,
                        to_utc_iso(now),
                        to_utc_iso(now),
                        conversation_id,
                        source_user_message_id,
                    ),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Run", key=run_id) from exc
        return RunRecord(
            run_id=run_id,
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
            conversation_id=conversation_id,
            source_user_message_id=source_user_message_id,
        )

    def get(self, run_id: str) -> RunRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row_to_run_record(row) if row is not None else None

    def list_run_ids(self) -> list[str]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT run_id FROM runs ORDER BY created_at ASC, run_id ASC").fetchall()
        return [row["run_id"] for row in rows]

    def list_active(self) -> list[RunRecord]:
        """Return active runs, filtered in SQL rather than by loading every run.

        Recovery runs on every cold start, so this is the optimized path: the
        status filter and the deterministic order are both applied by the
        database, and the generic port default is never consulted.
        """
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUS_VALUES)
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE status IN ({placeholders}) ORDER BY created_at ASC, run_id ASC",
                _ACTIVE_STATUS_VALUES,
            ).fetchall()
        return [row_to_run_record(row) for row in rows]

    def update_status(self, run_id: str, status: RunStatus) -> RunRecord | None:
        now = datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status.value, to_utc_iso(now), run_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row_to_run_record(row) if row is not None else None

    def compare_and_set_status(
        self,
        run_id: str,
        *,
        expected_status: RunStatus,
        status: RunStatus,
    ) -> RunRecord | None:
        """Move a run only while it is still in ``expected_status``.

        The guard is part of the ``WHERE`` clause, so the database decides: two
        concurrent writers can never both match, and the loser updates zero rows
        instead of overwriting the winner. That is the guarantee a read-then-write
        in Python cannot give.
        """
        now = datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ? AND status = ?",
                (status.value, to_utc_iso(now), run_id, expected_status.value),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row_to_run_record(row) if row is not None else None

    def request_cancellation(self, run_id: str, *, requested_at: datetime) -> RunRecord | None:
        """Record cancellation intent once, and only while the run is active.

        Both conditions live in the ``WHERE`` clause, so the database decides:
        a duplicate request cannot overwrite the first request's timestamp, and a
        run that settled between the caller's read and this write cannot acquire
        a cancellation it was already too late to receive. A read-then-write in
        Python would leave exactly those two windows open.
        """
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUS_VALUES)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runs SET cancellation_requested_at = ?, updated_at = ? "
                f"WHERE run_id = ? AND cancellation_requested_at IS NULL "
                f"AND status IN ({placeholders})",
                (to_utc_iso(requested_at), to_utc_iso(datetime.now(UTC)), run_id, *_ACTIVE_STATUS_VALUES),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row_to_run_record(row) if row is not None else None

    def set_execution_selection(
        self,
        run_id: str,
        selection: RunExecutionSelection | None,
    ) -> RunRecord | None:
        now = datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runs SET execution_selection = ?, updated_at = ? WHERE run_id = ?",
                (dump_execution_selection(selection), to_utc_iso(now), run_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row_to_run_record(row) if row is not None else None

    def set_assistant_message_id(self, run_id: str, assistant_message_id: str) -> RunRecord | None:
        now = datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runs SET assistant_message_id = ?, updated_at = ? WHERE run_id = ?",
                (assistant_message_id, to_utc_iso(now), run_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(f"SELECT {_RUN_COLUMNS} FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return row_to_run_record(row) if row is not None else None


# ============================================================
# END: Relational Run Repository
# ============================================================
