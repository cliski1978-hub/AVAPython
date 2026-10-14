"""In-memory AVA run store.

Holds the smallest generic run-state representation needed to know the
current status of a run. This is Sprint 2 in-memory state only: no database,
cache, or queue. Assistant content intentionally lives in events, never here.
"""

from dataclasses import replace
from datetime import UTC, datetime

from ava.contracts.execution import ExecutionMode, RunExecutionSelection
from ava.contracts.responses import ACTIVE_RUN_STATUSES, RunStatus
from ava.contracts.run_inspection import RunInspectionSnapshot
from ava.repositories.run_repository import (
    ActiveConversationRunError,
    RunRecord,
    RunRepository,
)

# ============================================================
# BEGIN: Run Store
# ============================================================


class RunStore(RunRepository):
    """In-memory, AVA-owned store of run records keyed by run id.

    This is the in-memory ``RunRepository`` implementation used by the
    current composition. Sprint 2 state only: no database, cache, or queue.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def create(
        self,
        run_id: str,
        *,
        conversation_id: str | None = None,
        source_user_message_id: str | None = None,
        execution_mode: ExecutionMode = ExecutionMode.CHAT,
        owner_principal_ref: str | None = None,
        owner_tenant_ref: str | None = None,
        owner_auth_context_ref: str | None = None,
        owner_auth_valid_until: datetime | None = None,
        execution_workspace_id: str | None = None,
    ) -> RunRecord:
        """Create a new pending run record.

        Args:
            run_id: The AVA-generated run identifier.

        Returns:
            The newly created pending record.

        Raises:
            ValueError: If a run with this identifier already exists.
        """
        if run_id in self._runs:
            raise ValueError(f"Run already exists: {run_id}")
        if conversation_id is not None and any(
            record.conversation_id == conversation_id and record.status.is_active for record in self._runs.values()
        ):
            raise ActiveConversationRunError(conversation_id)
        now = datetime.now(UTC)
        record = RunRecord(
            run_id=run_id,
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
            conversation_id=conversation_id,
            source_user_message_id=source_user_message_id,
            execution_mode=execution_mode,
            owner_principal_ref=owner_principal_ref,
            owner_tenant_ref=owner_tenant_ref,
            owner_auth_context_ref=owner_auth_context_ref,
            owner_auth_valid_until=owner_auth_valid_until,
            execution_workspace_id=execution_workspace_id,
        )
        self._runs[run_id] = record
        return record

    def update_status(self, run_id: str, status: RunStatus) -> RunRecord | None:
        """Update a run's status, refreshing its ``updated_at``.

        Args:
            run_id: The run identifier.
            status: The new AVA run status.

        Returns:
            The updated record, or ``None`` if the run is unknown.
        """
        record = self._runs.get(run_id)
        if record is None:
            return None
        updated = replace(record, status=status, updated_at=datetime.now(UTC))
        self._runs[run_id] = updated
        return updated

    def compare_and_set_status(
        self,
        run_id: str,
        *,
        expected_status: RunStatus,
        status: RunStatus,
    ) -> RunRecord | None:
        """Move a run only while it is still in ``expected_status``.

        The in-memory store is mutated without awaiting, so the check and the
        write cannot interleave with another task and the guard is exact.
        """
        record = self._runs.get(run_id)
        if record is None or record.status is not expected_status:
            return None
        return self.update_status(run_id, status)

    def request_cancellation(self, run_id: str, *, requested_at: datetime) -> RunRecord | None:
        """Record cancellation intent once, and only while the run is active.

        The in-memory store is mutated without awaiting, so the guard and the
        write cannot interleave and the guard is exact.
        """
        record = self._runs.get(run_id)
        if record is None or not record.status.is_active:
            return None
        if record.cancellation_requested_at is not None:
            # The first request's timestamp is the one that persists; a repeat
            # click is not a later request, it is the same request.
            return None
        updated = replace(record, cancellation_requested_at=requested_at, updated_at=datetime.now(UTC))
        self._runs[run_id] = updated
        return updated

    def set_execution_selection(self, run_id: str, selection: RunExecutionSelection | None) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        updated = replace(record, execution_selection=selection, updated_at=datetime.now(UTC))
        self._runs[run_id] = updated
        return updated

    def set_inspection_snapshot(self, run_id: str, snapshot: RunInspectionSnapshot) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        updated = replace(record, inspection_snapshot=snapshot, updated_at=datetime.now(UTC))
        self._runs[run_id] = updated
        return updated

    def list_for_conversation(self, conversation_id: str) -> list[RunRecord]:
        return sorted(
            (record for record in self._runs.values() if record.conversation_id == conversation_id),
            key=lambda record: (record.created_at, record.run_id),
        )

    def set_assistant_message_id(self, run_id: str, assistant_message_id: str) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        updated = replace(record, assistant_message_id=assistant_message_id, updated_at=datetime.now(UTC))
        self._runs[run_id] = updated
        return updated

    def get(self, run_id: str) -> RunRecord | None:
        """Return the run record for ``run_id``, or ``None`` if unknown."""
        return self._runs.get(run_id)

    def list_active(self) -> list[RunRecord]:
        return sorted(
            (record for record in self._runs.values() if record.status in ACTIVE_RUN_STATUSES),
            key=lambda record: (record.created_at, record.run_id),
        )

    def list_run_ids(self) -> list[str]:
        """Return the identifiers of all tracked runs in insertion order."""
        return list(self._runs)

    def clear(self) -> None:
        """Remove all run records (test/observability helper)."""
        self._runs.clear()


# ============================================================
# END: Run Store
# ============================================================
