"""SQLite adapter for AVA's normalized tool invocation lifecycle port."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import cast

from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.errors import PersistenceError
from ava.repositories.invocation_reservation_repository import (
    TERMINAL_INVOCATION_STATES,
    InvocationReservation,
    InvocationReservationConflict,
    InvocationReservationState,
    next_reservation,
)


class RelationalInvocationReservationRepository:
    durable = True

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def reserve(self, reservation: InvocationReservation) -> InvocationReservation:
        if reservation.state != InvocationReservationState.RESERVED or reservation.revision != 0:
            raise ValueError("new invocation reservations must start at revision zero in reserved state")
        columns = (
            "invocation_id, run_id, tool_id, tool_version, operation_fingerprint, workspace_id, "
            "execution_context_ref, authority_revision_ref, configuration_revision_ref, execution_mode, "
            "state, revision, created_at, updated_at, started_at, completed_at, result_status, error_code, "
            "reconciliation_status"
        )
        values = self._values(reservation)
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    f"INSERT INTO tool_invocation_reservations ({columns}) VALUES ({','.join('?' for _ in values)})",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise InvocationReservationConflict("invocation identity already reserved or Run is missing") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("tool invocation reservation could not be stored") from exc
        return reservation

    def get(self, invocation_id: str) -> InvocationReservation | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tool_invocation_reservations WHERE invocation_id = ?", (invocation_id,)
            ).fetchone()
        return self._decode(row) if row is not None else None

    def transition(
        self,
        invocation_id: str,
        *,
        expected_revision: int,
        state: InvocationReservationState,
        result_status: str | None = None,
        error_code: str | None = None,
        reconciliation_status: str | None = None,
    ) -> InvocationReservation:
        try:
            with self._database.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM tool_invocation_reservations WHERE invocation_id = ?", (invocation_id,)
                ).fetchone()
                if row is None:
                    raise InvocationReservationConflict("invocation reservation is missing")
                current = self._decode(row)
                if current.revision != expected_revision:
                    raise InvocationReservationConflict("invocation revision conflict")
                updated = next_reservation(
                    current,
                    state,
                    result_status=result_status,
                    error_code=error_code,
                    reconciliation_status=reconciliation_status,
                )
                cursor = connection.execute(
                    """UPDATE tool_invocation_reservations SET state=?, revision=?, updated_at=?, started_at=?,
                       completed_at=?, result_status=?, error_code=?, reconciliation_status=?
                       WHERE invocation_id=? AND revision=? AND state=?""",
                    (
                        updated.state.value,
                        updated.revision,
                        updated.updated_at.isoformat(),
                        updated.started_at.isoformat() if updated.started_at else None,
                        updated.completed_at.isoformat() if updated.completed_at else None,
                        updated.result_status,
                        updated.error_code,
                        updated.reconciliation_status,
                        invocation_id,
                        expected_revision,
                        current.state.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise InvocationReservationConflict("invocation revision conflict")
                return updated
        except (InvocationReservationConflict, ValueError):
            raise
        except sqlite3.Error as exc:
            raise PersistenceError("tool invocation transition could not be stored") from exc

    def list_incomplete(self, *, limit: int = 100) -> tuple[InvocationReservation, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("invocation query limit must be between 1 and 1000")
        states = tuple(state.value for state in TERMINAL_INVOCATION_STATES)
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_invocation_reservations WHERE state NOT IN "
                f"({','.join('?' for _ in states)}) ORDER BY created_at, invocation_id LIMIT ?",
                (*states, limit),
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    def list_for_run(self, run_id: str, *, limit: int = 100) -> tuple[InvocationReservation, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("invocation query limit must be between 1 and 1000")
        with self._database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM tool_invocation_reservations WHERE run_id=?
                   ORDER BY created_at DESC, invocation_id DESC LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        return tuple(reversed(tuple(self._decode(row) for row in rows)))

    @staticmethod
    def _values(record: InvocationReservation) -> tuple[object, ...]:
        return (
            record.invocation_id,
            record.run_id,
            record.tool_id,
            record.tool_version,
            record.operation_fingerprint,
            record.workspace_id,
            record.execution_context_ref,
            record.authority_revision_ref,
            record.configuration_revision_ref,
            record.execution_mode,
            record.state.value,
            record.revision,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            record.started_at.isoformat() if record.started_at else None,
            record.completed_at.isoformat() if record.completed_at else None,
            record.result_status,
            record.error_code,
            record.reconciliation_status,
        )

    @staticmethod
    def _decode(row: sqlite3.Row) -> InvocationReservation:
        try:
            record = InvocationReservation(
                invocation_id=cast(str, row["invocation_id"]),
                run_id=cast(str, row["run_id"]),
                tool_id=cast(str, row["tool_id"]),
                tool_version=cast(str, row["tool_version"]),
                operation_fingerprint=cast(str, row["operation_fingerprint"]),
                workspace_id=cast(str, row["workspace_id"]),
                execution_context_ref=cast(str, row["execution_context_ref"]),
                authority_revision_ref=cast(str, row["authority_revision_ref"]),
                configuration_revision_ref=cast(str, row["configuration_revision_ref"]),
                execution_mode=cast(str, row["execution_mode"]),
                state=InvocationReservationState(cast(str, row["state"])),
                revision=cast(int, row["revision"]),
                created_at=datetime.fromisoformat(cast(str, row["created_at"])),
                updated_at=datetime.fromisoformat(cast(str, row["updated_at"])),
                started_at=datetime.fromisoformat(cast(str, row["started_at"])) if row["started_at"] else None,
                completed_at=datetime.fromisoformat(cast(str, row["completed_at"])) if row["completed_at"] else None,
                result_status=cast(str | None, row["result_status"]),
                error_code=cast(str | None, row["error_code"]),
                reconciliation_status=cast(str, row["reconciliation_status"]),
            )
            if record.revision < 0 or record.created_at.tzinfo is None or record.updated_at.tzinfo is None:
                raise ValueError("invalid revision or timestamp")
            if record.state == InvocationReservationState.RESERVED and record.started_at is not None:
                raise ValueError("reserved record cannot have a started timestamp")
            if record.state in TERMINAL_INVOCATION_STATES and record.completed_at is None:
                raise ValueError("terminal record requires completion timestamp")
            return record
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError("corrupt tool invocation reservation record") from exc
