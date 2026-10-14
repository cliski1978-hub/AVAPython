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
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from ava.contracts.execution import ExecutionMode, RunExecutionSelection
from ava.contracts.responses import RunStatus
from ava.contracts.run_inspection import RunInspectionSnapshot

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

    ``cancellation_requested_at`` is durable *intent*, not an outcome. It is
    written once, when a user first asks for the run to stop, and is never
    cleared — including when the run finishes normally instead. A settled run
    with a request timestamp is exactly the evidence that cancellation was
    requested and lost its race.
    """

    run_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    execution_selection: RunExecutionSelection | None = None
    execution_mode: ExecutionMode = ExecutionMode.CHAT
    conversation_id: str | None = None
    source_user_message_id: str | None = None
    assistant_message_id: str | None = None
    cancellation_requested_at: datetime | None = None
    inspection_snapshot: RunInspectionSnapshot | None = None
    owner_principal_ref: str | None = None
    owner_tenant_ref: str | None = None
    owner_auth_context_ref: str | None = None
    owner_auth_valid_until: datetime | None = None
    execution_workspace_id: str | None = None

    @property
    def cancellation_requested(self) -> bool:
        """Whether a cancellation request is recorded, derived from its timestamp.

        One field, one truth. A separate mutable boolean would be a second
        thing to keep in sync and a second thing to get wrong under a race.
        """
        return self.cancellation_requested_at is not None


# ============================================================
# END: Run Record
# ============================================================


# ============================================================
# BEGIN: Run Repository
# ============================================================


class ActiveConversationRunError(ValueError):
    """A conversation already owns an active run."""

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation already has an active run: {conversation_id}")


class RunRepository(ABC):
    """Port that durable run-state repositories must satisfy.

    Responsibilities mirror the existing ``RunStore`` semantics consumed by
    ``RunService``:

    * ``create`` — open a new pending run; a duplicate run id is an error.
    * ``get`` — read the current run snapshot, or ``None`` for an unknown run.
    * ``update_status`` — move a run to a new status, refreshing ``updated_at``.
    * ``compare_and_set_status`` — move a run only if it is still in the status
      the caller last observed.
    * ``request_cancellation`` — record cancellation intent, once, and only
      while the run is still active.
    * ``set_execution_selection`` — record the resolved execution identity.

    ``update_status`` is the blind primitive and ``compare_and_set_status`` is
    the guarded one. Both exist because the lifecycle authority needs to lose a
    race, not just win one: only the guarded write can promise that two
    concurrent terminal transitions never overwrite each other. Neither method
    decides whether a transition is *legal* — that is the lifecycle's rule, and
    keeping it out of here is what leaves the repositories testable on their
    own.

    Deliberately not part of this port: run identity generation, sessions,
    transactions, query language, ORM entities, and observability helpers such
    as ``list``/``clear`` (those remain concrete-implementation concerns).
    """

    @abstractmethod
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

    def list_run_ids(self) -> list[str]:
        """Return the identifiers of every run this repository can read.

        Phase 5.30 needs active-run discovery at cold start, and discovery needs
        enumeration: no combination of ``get`` calls can reveal runs nobody asks
        about by id.

        This is a *capability probe*, deliberately not an empty default. A
        repository that answered ``()`` here would make cold-start recovery
        believe a database full of stranded runs held nothing at all, and
        recovery would then serve stale ``running`` state as if it were
        healthy. Failing loudly keeps that impossible, while remaining
        source-compatible: an implementation that does not override this stays
        instantiable, and is only unusable for discovery.

        Implementations may instead override :meth:`list_active` directly with a
        cheaper query and never call this.

        Returns:
            Every run identifier known to this repository.

        Raises:
            NotImplementedError: If the repository supports neither
                :meth:`list_run_ids` nor an overriding :meth:`list_active`.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement list_run_ids() or override list_active(): "
            "active-run discovery cannot be answered with an empty result"
        )

    def list_active(self) -> Collection[RunRecord]:
        """Return every active run snapshot in deterministic creation/id order.

        Used by cold-start recovery (Phase 5.30) to find runs whose execution
        owner was lost with the previous process.

        The default is a correct generic implementation — not an empty result —
        so an implementation gains active-run discovery by implementing
        :meth:`list_run_ids` and nothing else. It asks the record itself whether
        it is active, through :attr:`RunStatus.is_active`, so the active set is
        the canonical one rather than a second list of status strings kept
        somewhere else. It is read-only and its ordering makes a recovery pass
        reproducible.

        Production repositories override this with an optimized query that
        filters in the persistence layer instead of loading every run.
        """
        records = (
            record
            for run_id in self.list_run_ids()
            if (record := self.get(run_id)) is not None and record.status.is_active
        )
        return sorted(records, key=lambda record: (record.created_at, record.run_id))

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
    def compare_and_set_status(
        self,
        run_id: str,
        *,
        expected_status: RunStatus,
        status: RunStatus,
    ) -> RunRecord | None:
        """Move a run to ``status`` only while it is still in ``expected_status``.

        The guarded counterpart to :meth:`update_status`. A caller that read
        ``expected_status`` and then asks to write ``status`` is asking "has
        anything moved under me?" — a question a plain update cannot answer
        without overwriting the answer.

        Args:
            run_id: The AVA-generated run identifier.
            expected_status: The status the caller observed and is writing from.
            status: The new AVA run status.

        Returns:
            The updated snapshot, or ``None`` when the run is unknown *or* is no
            longer in ``expected_status``. Callers distinguish those by
            re-reading the run.
        """
        raise NotImplementedError

    @abstractmethod
    def request_cancellation(self, run_id: str, *, requested_at: datetime) -> RunRecord | None:
        """Record that someone asked for this run to stop.

        The write is guarded on both halves of the intent at once: the run must
        still be *active* and must not already carry a request. Both are part of
        the write itself rather than a read followed by a conditional, so two
        concurrent requests cannot both land and a run cannot acquire a
        cancellation it was already too late to receive.

        Args:
            run_id: The AVA-generated run identifier.
            requested_at: The moment the request was made. The first request's
                value is the one that persists.

        Returns:
            The updated snapshot, or ``None`` when the run is unknown, has
            already settled, or already has a request recorded. Callers
            distinguish those by re-reading the run.
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

    def set_inspection_snapshot(self, run_id: str, snapshot: RunInspectionSnapshot) -> RunRecord | None:
        """Persist captured execution facts for this run."""
        raise NotImplementedError

    def list_for_conversation(self, conversation_id: str) -> list[RunRecord]:
        """Return runs for a conversation in chronological order."""
        raise NotImplementedError

    def set_assistant_message_id(self, run_id: str, assistant_message_id: str) -> RunRecord | None:
        """Record the single durable assistant response created for a run.

        Older third-party/in-memory ports remain usable for unlinked legacy
        runs; linked runs require an implementation that returns a record.
        """
        return None


# ============================================================
# END: Run Repository
# ============================================================
