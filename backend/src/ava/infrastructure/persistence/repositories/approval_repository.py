"""SQLite adapter for the AVA approval repository port."""

import sqlite3

from ava.contracts.approvals import ApprovalRecord, ApprovalStatus
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.repositories.approval_repository import ApprovalConflictError, ApprovalRepository


class CorruptApprovalRecordError(ValueError):
    """Persisted approval data is invalid and must fail closed."""


class RelationalApprovalRepository(ApprovalRepository):
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, record: ApprovalRecord) -> ApprovalRecord:
        record = ApprovalRecord.model_validate(record.model_dump())
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO approval_records "
                    "(approval_id, invocation_id, run_id, workspace_id, status, requested_at, record_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.approval_id,
                        record.invocation_id,
                        record.run_id,
                        record.workspace_id,
                        record.status.value,
                        record.requested_at.isoformat(),
                        record.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ApprovalConflictError("An approval already exists for this invocation.") from exc
        return record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM approval_records WHERE approval_id = ?", (approval_id,)).fetchone()
        return self._decode_row(row) if row else None

    def get_by_invocation(self, invocation_id: str) -> ApprovalRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM approval_records WHERE invocation_id = ?", (invocation_id,)
            ).fetchone()
        return self._decode_row(row) if row else None

    def list_pending(self, *, limit: int = 100) -> list[ApprovalRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM approval_records WHERE status = 'pending' ORDER BY requested_at, approval_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def list_pending_for_run(self, run_id: str) -> list[ApprovalRecord]:
        return self._list_pending_by("run_id", run_id)

    def list_pending_for_workspace(self, workspace_id: str) -> list[ApprovalRecord]:
        return self._list_pending_by("workspace_id", workspace_id)

    def _list_pending_by(self, column: str, value: str) -> list[ApprovalRecord]:
        if column not in {"run_id", "workspace_id"}:
            raise ValueError("unsupported approval lookup")
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM approval_records WHERE status = 'pending' AND {column} = ? "
                "ORDER BY requested_at, approval_id",
                (value,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def compare_and_set(
        self, approval_id: str, expected: ApprovalStatus, replacement: ApprovalRecord
    ) -> ApprovalRecord | None:
        replacement = ApprovalRecord.model_validate(replacement.model_dump())
        with self._database.transaction() as connection:
            row = connection.execute("SELECT * FROM approval_records WHERE approval_id = ?", (approval_id,)).fetchone()
            if row is None:
                return None
            current = self._decode_row(row)
            if replacement.approval_id != approval_id or replacement.invocation_id != current.invocation_id:
                raise ValueError("approval identity is immutable")
            cursor = connection.execute(
                "UPDATE approval_records SET status = ?, record_json = ? WHERE approval_id = ? AND status = ?",
                (replacement.status.value, replacement.model_dump_json(), approval_id, expected.value),
            )
            return replacement if cursor.rowcount == 1 else None

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> ApprovalRecord:
        try:
            record = ApprovalRecord.model_validate_json(row["record_json"])
            expected = (
                record.approval_id,
                record.invocation_id,
                record.run_id,
                record.workspace_id,
                record.status.value,
                record.requested_at.isoformat(),
            )
            actual = tuple(
                row[key] for key in ("approval_id", "invocation_id", "run_id", "workspace_id", "status", "requested_at")
            )
            if actual != expected:
                raise ValueError("approval index fields do not match record data")
            return record
        except (ValueError, TypeError) as exc:
            raise CorruptApprovalRecordError("Persisted approval record is invalid.") from exc
