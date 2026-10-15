"""Persistence port for immutable, compare-and-set approval decisions."""

from abc import ABC, abstractmethod

from ava.contracts.approvals import ApprovalAuditEvent, ApprovalRecord, ApprovalStatus


class ApprovalConflictError(ValueError):
    """An approval already exists for an invocation or its state changed."""


class ApprovalRepository(ABC):
    @abstractmethod
    def create(self, record: ApprovalRecord) -> ApprovalRecord: ...

    @abstractmethod
    def get(self, approval_id: str) -> ApprovalRecord | None: ...

    @abstractmethod
    def get_by_invocation(self, invocation_id: str) -> ApprovalRecord | None: ...

    @abstractmethod
    def list_pending(self, *, limit: int = 100) -> list[ApprovalRecord]: ...

    @abstractmethod
    def list_recent(self, *, limit: int = 100) -> list[ApprovalRecord]: ...

    @abstractmethod
    def list_audit_events(self, approval_id: str) -> list[ApprovalAuditEvent]: ...

    @abstractmethod
    def list_pending_for_run(self, run_id: str) -> list[ApprovalRecord]: ...

    @abstractmethod
    def list_pending_for_workspace(self, workspace_id: str) -> list[ApprovalRecord]: ...

    @abstractmethod
    def compare_and_set(
        self, approval_id: str, expected: ApprovalStatus, replacement: ApprovalRecord
    ) -> ApprovalRecord | None: ...
