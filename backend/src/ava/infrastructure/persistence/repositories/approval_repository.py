"""SQLite adapter for the AVA approval repository port."""

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from ava.contracts.approvals import ApprovalAuditEvent, ApprovalAuditEventType, ApprovalRecord, ApprovalStatus
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
                self._append_audit(connection, record, ApprovalAuditEventType.REQUESTED, 1)
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

    def list_recent(self, *, limit: int = 100) -> list[ApprovalRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("approval listing limit must be between 1 and 500")
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM approval_records ORDER BY requested_at DESC, approval_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def list_audit_events(self, approval_id: str) -> list[ApprovalAuditEvent]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM approval_audit_events WHERE approval_id = ? ORDER BY sequence", (approval_id,)
            ).fetchall()
        return [
            ApprovalAuditEvent(
                event_id=row["event_id"], approval_id=row["approval_id"], sequence=int(row["sequence"]),
                event_type=ApprovalAuditEventType(row["event_type"]), status=ApprovalStatus(row["status"]),
                actor_principal_ref=row["actor_principal_ref"],
                authority_revision_ref=row["authority_revision_ref"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
            )
            for row in rows
        ]

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
            if cursor.rowcount == 1:
                sequence = int(connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM approval_audit_events WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()[0])
                self._append_audit(
                    connection, replacement, ApprovalAuditEventType(replacement.status.value), sequence
                )
            return replacement if cursor.rowcount == 1 else None

    @staticmethod
    def _append_audit(connection: sqlite3.Connection, record: ApprovalRecord,
                      event_type: ApprovalAuditEventType, sequence: int) -> None:
        metadata = record.decision_metadata
        occurred_at = metadata.decided_at if metadata is not None else datetime.now(UTC)
        connection.execute(
            "INSERT INTO approval_audit_events "
            "(event_id, approval_id, sequence, event_type, status, actor_principal_ref, "
            "authority_revision_ref, occurred_at, safe_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (uuid4().hex, record.approval_id, sequence, event_type.value, record.status.value,
             metadata.principal_ref if metadata is not None else None,
             metadata.authority_revision_ref if metadata is not None else None,
             occurred_at.isoformat()),
        )

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
