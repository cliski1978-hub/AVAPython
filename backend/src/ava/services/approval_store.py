"""Thread-safe in-memory approval repository for tests and local composition."""

from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from ava.contracts.approvals import ApprovalAuditEvent, ApprovalAuditEventType, ApprovalRecord, ApprovalStatus
from ava.repositories.approval_repository import ApprovalConflictError, ApprovalRepository


class ApprovalStore(ApprovalRepository):
    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._audit: dict[str, list[ApprovalAuditEvent]] = {}
        self._invocations: dict[str, str] = {}
        self._lock = RLock()

    def create(self, record: ApprovalRecord) -> ApprovalRecord:
        record = ApprovalRecord.model_validate(record.model_dump())
        with self._lock:
            if record.approval_id in self._records or record.invocation_id in self._invocations:
                raise ApprovalConflictError("An approval already exists for this invocation.")
            self._records[record.approval_id] = record
            self._invocations[record.invocation_id] = record.approval_id
            self._append_audit(record, ApprovalAuditEventType.REQUESTED)
            return record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._records.get(approval_id)

    def get_by_invocation(self, invocation_id: str) -> ApprovalRecord | None:
        with self._lock:
            approval_id = self._invocations.get(invocation_id)
            return self._records.get(approval_id) if approval_id else None

    def list_pending(self, *, limit: int = 100) -> list[ApprovalRecord]:
        with self._lock:
            return [record for record in self._records.values() if record.status == ApprovalStatus.PENDING][:limit]

    def list_recent(self, *, limit: int = 100) -> list[ApprovalRecord]:
        with self._lock:
            return sorted(
                self._records.values(),
                key=lambda record: (record.requested_at, record.approval_id),
                reverse=True,
            )[:limit]

    def list_audit_events(self, approval_id: str) -> list[ApprovalAuditEvent]:
        with self._lock:
            return list(self._audit.get(approval_id, ()))

    def list_pending_for_run(self, run_id: str) -> list[ApprovalRecord]:
        with self._lock:
            return [
                record
                for record in self._records.values()
                if record.run_id == run_id and record.status == ApprovalStatus.PENDING
            ]

    def list_pending_for_workspace(self, workspace_id: str) -> list[ApprovalRecord]:
        with self._lock:
            return [
                record
                for record in self._records.values()
                if record.workspace_id == workspace_id and record.status == ApprovalStatus.PENDING
            ]

    def compare_and_set(
        self, approval_id: str, expected: ApprovalStatus, replacement: ApprovalRecord
    ) -> ApprovalRecord | None:
        replacement = ApprovalRecord.model_validate(replacement.model_dump())
        with self._lock:
            current = self._records.get(approval_id)
            if current is None or current.status != expected:
                return None
            if replacement.approval_id != approval_id or replacement.invocation_id != current.invocation_id:
                raise ValueError("approval identity is immutable")
            self._records[approval_id] = replacement
            self._append_audit(replacement, ApprovalAuditEventType(replacement.status.value))
            return replacement

    def _append_audit(self, record: ApprovalRecord, event_type: ApprovalAuditEventType) -> None:
        events = self._audit.setdefault(record.approval_id, [])
        metadata = record.decision_metadata
        events.append(ApprovalAuditEvent(
            event_id=uuid4().hex,
            approval_id=record.approval_id,
            sequence=len(events) + 1,
            event_type=event_type,
            status=record.status,
            actor_principal_ref=metadata.principal_ref if metadata is not None else None,
            authority_revision_ref=metadata.authority_revision_ref if metadata is not None else None,
            occurred_at=metadata.decided_at if metadata is not None else datetime.now(UTC),
        ))
