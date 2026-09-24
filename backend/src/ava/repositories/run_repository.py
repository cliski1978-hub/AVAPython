"""AVA-owned run persistence repository port.

Expresses the run-state semantics that ``RunService`` needs today, split out
of the concrete in-memory ``RunStore`` so durable implementations (Step 4.3+)
can satisfy the same contract without touching run lifecycle behavior.

The port is deliberately framework-neutral: no SQL, ORM entities, sessions,
transactions, queries, rows, or database drivers. Inputs and outputs use
AVA-owned contracts (``RunStatus``, ``RunExecutionSelection``) plus the
AVA-owned ``RunRecord`` domain record. Run identifiers are always supplied by
the caller; a repository never mints run ids.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ava.contracts.execution import RunExecutionSelection
from ava.contracts.responses import RunStatus

# ============================================================
# BEGIN: Run Record
# ============================================================


@dataclass(frozen=True)
class RunRecord:
    """AVA-owned snapshot of a run's persisted state.

    Internally shared by run-repository implementations and the existing
    in-memory store. ``created_at`` and ``updated_at`` are timezone-aware UTC
    timestamps (``datetime.now(UTC)`` semantics of the current store); durable
    adapters must preserve aware-UTC round-tripping.
    """

    run_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    execution_selection: RunExecutionSelection | None = None


# ============================================================
# END: Run Record
# ============================================================


# ============================================================
# BEGIN: Run Repository
# ============================================================


class RunRepository(ABC):
    """Port that durable run-state repositories must satisfy.

    Responsibilities mirror the existing ``RunStore`` semantics consumed by
    ``RunService``:

    * ``create`` — open a new pending run; a duplicate run id is an error.
    * ``get`` — read the current run snapshot, or ``None`` for an unknown run.
    * ``update_status`` — move a run to a new status, refreshing ``updated_at``.
    * ``set_execution_selection`` — record the resolved execution identity.

    Deliberately not part of this port: run identity generation, sessions,
    transactions, query language, ORM entities, and observability helpers such
    as ``list``/``clear`` (those remain concrete-implementation concerns).
    """

    @abstractmethod
    def create(self, run_id: str) -> RunRecord:
        """Create a new pending run record.

        Args:
            run_id: The AVA-generated run identifier.

        Returns:
            The newly created pending record.

        Raises:
            ValueError: If a run with this identifier already exists.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, run_id: str) -> RunRecord | None:
        """Return the run's current snapshot, or ``None`` if unknown.

        Args:
            run_id: The AVA-generated run identifier.

        Returns:
            A frozen ``RunRecord`` snapshot, or ``None`` when the run is unknown.
        """
        raise NotImplementedError

    @abstractmethod
    def update_status(self, run_id: str, status: RunStatus) -> RunRecord | None:
        """Update a run's status, refreshing its ``updated_at``.

        Args:
            run_id: The AVA-generated run identifier.
            status: The new AVA run status.

        Returns:
            The updated snapshot, or ``None`` if the run is unknown.
        """
        raise NotImplementedError

    @abstractmethod
    def set_execution_selection(
        self,
        run_id: str,
        selection: RunExecutionSelection | None,
    ) -> RunRecord | None:
        """Record the resolved execution selection for a run.

        Args:
            run_id: The AVA-generated run identifier.
            selection: The resolved execution identity, or ``None`` to clear it.

        Returns:
            The updated snapshot, or ``None`` if the run is unknown.
        """
        raise NotImplementedError


# ============================================================
# END: Run Repository
# ============================================================