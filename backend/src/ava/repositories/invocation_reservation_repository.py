"""Framework-neutral durable lifecycle records for normalized tool calls."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Protocol


class InvocationReservationState(StrEnum):
    NOT_STARTED = "not_started"
    RESERVED = "reserved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INDETERMINATE = "indeterminate"


TERMINAL_INVOCATION_STATES = frozenset(
    {
        InvocationReservationState.COMPLETED,
        InvocationReservationState.FAILED,
        InvocationReservationState.CANCELLED,
        InvocationReservationState.INDETERMINATE,
    }
)


@dataclass(frozen=True)
class InvocationReservation:
    invocation_id: str
    run_id: str
    tool_id: str
    tool_version: str
    operation_fingerprint: str
    workspace_id: str
    execution_context_ref: str
    authority_revision_ref: str
    configuration_revision_ref: str
    execution_mode: str
    state: InvocationReservationState = InvocationReservationState.RESERVED
    revision: int = 0
    created_at: datetime = datetime.min.replace(tzinfo=UTC)
    updated_at: datetime = datetime.min.replace(tzinfo=UTC)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result_status: str | None = None
    error_code: str | None = None
    reconciliation_status: str = "not_required"

    def __post_init__(self) -> None:
        identity = (
            self.invocation_id,
            self.run_id,
            self.tool_id,
            self.tool_version,
            self.workspace_id,
            self.execution_context_ref,
            self.authority_revision_ref,
            self.configuration_revision_ref,
        )
        if any(not value for value in identity):
            raise ValueError("invocation identity fields must be present")
        if re.fullmatch(r"[a-f0-9]{64}", self.operation_fingerprint) is None:
            raise ValueError("operation fingerprint must be a lowercase SHA-256 digest")
        if self.execution_mode not in {"chat", "plan", "agent"}:
            raise ValueError("invalid persisted execution mode")
        if self.revision < 0 or self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("invalid invocation revision or timestamp")
        if self.result_status is not None and self.result_status not in {
            "completed", "failed", "cancelled", "indeterminate"
        }:
            raise ValueError("invalid normalized invocation result status")
        if self.error_code is not None and re.fullmatch(r"[a-z0-9_.-]{1,128}", self.error_code) is None:
            raise ValueError("invalid normalized invocation error code")


class InvocationReservationConflict(ValueError):  # noqa: N818
    """A reservation exists or its immutable identity does not match."""


class InvocationReservationRepository(Protocol):
    durable: bool

    def reserve(self, reservation: InvocationReservation) -> InvocationReservation:
        """Atomically insert a RESERVED record; duplicate IDs always conflict."""
        ...

    def get(self, invocation_id: str) -> InvocationReservation | None: ...

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
        """CAS a legal forward transition, raising on conflict or bad state."""
        ...

    def list_incomplete(self, *, limit: int = 100) -> tuple[InvocationReservation, ...]: ...

    def list_for_run(self, run_id: str, *, limit: int = 100) -> tuple[InvocationReservation, ...]: ...


def next_reservation(
    record: InvocationReservation,
    state: InvocationReservationState,
    *,
    result_status: str | None = None,
    error_code: str | None = None,
    reconciliation_status: str | None = None,
) -> InvocationReservation:
    allowed = {
        InvocationReservationState.RESERVED: {
            InvocationReservationState.EXECUTING,
            InvocationReservationState.FAILED,
            InvocationReservationState.CANCELLED,
        },
        InvocationReservationState.EXECUTING: {
            InvocationReservationState.COMPLETED,
            InvocationReservationState.FAILED,
            InvocationReservationState.CANCELLED,
            InvocationReservationState.INDETERMINATE,
        },
    }
    if state not in allowed.get(record.state, set()):
        raise InvocationReservationConflict("illegal or terminal invocation transition")
    now = datetime.now(UTC)
    return replace(
        record,
        state=state,
        revision=record.revision + 1,
        updated_at=now,
        started_at=now if state == InvocationReservationState.EXECUTING else record.started_at,
        completed_at=now if state in TERMINAL_INVOCATION_STATES else record.completed_at,
        result_status=result_status if result_status is not None else record.result_status,
        error_code=error_code if error_code is not None else record.error_code,
        reconciliation_status=reconciliation_status or record.reconciliation_status,
    )


class InMemoryInvocationReservationRepository:
    """Isolated adapter for tests; never suitable for dispatch authorization."""

    durable = False

    def __init__(self) -> None:
        self._records: dict[str, InvocationReservation] = {}
        self._lock = RLock()

    def reserve(self, reservation: InvocationReservation) -> InvocationReservation:
        with self._lock:
            if reservation.invocation_id in self._records:
                raise InvocationReservationConflict("invocation already reserved")
            self._records[reservation.invocation_id] = reservation
            return reservation

    def get(self, invocation_id: str) -> InvocationReservation | None:
        with self._lock:
            return self._records.get(invocation_id)

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
        with self._lock:
            current = self._records.get(invocation_id)
            if current is None or current.revision != expected_revision:
                raise InvocationReservationConflict("invocation revision conflict")
            updated = next_reservation(
                current,
                state,
                result_status=result_status if result_status is not None else current.result_status,
                error_code=error_code if error_code is not None else current.error_code,
                reconciliation_status=reconciliation_status
                if reconciliation_status is not None
                else current.reconciliation_status,
            )
            self._records[invocation_id] = updated
            return updated

    def list_incomplete(self, *, limit: int = 100) -> tuple[InvocationReservation, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("invocation query limit must be between 1 and 1000")
        with self._lock:
            return tuple(
                sorted(
                    (r for r in self._records.values() if r.state not in TERMINAL_INVOCATION_STATES),
                    key=lambda r: (r.created_at, r.invocation_id),
                )[:limit]
            )

    def list_for_run(self, run_id: str, *, limit: int = 100) -> tuple[InvocationReservation, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("invocation query limit must be between 1 and 1000")
        with self._lock:
            return tuple(
                sorted(
                    (r for r in self._records.values() if r.run_id == run_id),
                    key=lambda r: (r.created_at, r.invocation_id),
                )[-limit:]
            )
