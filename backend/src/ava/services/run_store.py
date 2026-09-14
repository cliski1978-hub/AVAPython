"""In-memory AVA run store.

Holds the smallest generic run-state representation needed to know the
current status of a run. This is Sprint 2 in-memory state only: no database,
cache, or queue. Assistant content intentionally lives in events, never here.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from ava.contracts.responses import RunStatus

# ============================================================
# BEGIN: Run Record
# ============================================================


@dataclass(frozen=True)
class RunRecord:
    """AVA-owned snapshot of a run's current state."""

    run_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime


# ============================================================
# END: Run Record
# ============================================================


# ============================================================
# BEGIN: Run Store
# ============================================================


class RunStore:
    """In-memory, AVA-owned store of run records keyed by run id."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def create(self, run_id: str) -> RunRecord:
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
        now = datetime.now(UTC)
        record = RunRecord(
            run_id=run_id,
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
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

    def get(self, run_id: str) -> RunRecord | None:
        """Return the run record for ``run_id``, or ``None`` if unknown."""
        return self._runs.get(run_id)

    def list_run_ids(self) -> list[str]:
        """Return the identifiers of all tracked runs in insertion order."""
        return list(self._runs)

    def clear(self) -> None:
        """Remove all run records (test/observability helper)."""
        self._runs.clear()


# ============================================================
# END: Run Store
# ============================================================