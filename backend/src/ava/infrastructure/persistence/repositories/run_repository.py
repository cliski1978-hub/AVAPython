"""SQLite-backed run repository adapter (Step 4.6).

Implements the AVA ``RunRepository`` port over the shared ``SqliteDatabase``.
Behavioral parity with the in-memory ``RunStore``: duplicates raise
``ValueError``, unknown runs return ``None``, updates refresh ``updated_at``.
"""

import sqlite3
from datetime import UTC, datetime

from ava.contracts.execution import RunExecutionSelection
from ava.contracts.responses import RunStatus
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import (
    dump_execution_selection,
    row_to_run_record,
    to_utc_iso,
)
from ava.repositories.run_repository import RunRecord, RunRepository

_RUN_COLUMNS = "run_id, status, created_at, updated_at, execution_selection"

# ============================================================
# BEGIN: Relational Run Repository
# ============================================================


class RelationalRunRepository(RunRepository):
    """SQLite-backed implementation of the run repository port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, run_id: str) -> RunRecord:
        now = datetime.now(UTC)
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (run_id, RunStatus.PENDING.value, to_utc_iso(now), to_utc_iso(now)),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Run", key=run_id) from exc
        return RunRecord(run_id=run_id, status=RunStatus.PENDING, created_at=now, updated_at=now)

    def get(self, run_id: str) -> RunRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row_to_run_record(row) if row is not None else None

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


# ============================================================
# END: Relational Run Repository
# ============================================================