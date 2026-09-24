"""Run service.

Coordinates an AVA run as a normalized sequence of AVA-owned events using
only the Sprint 1 event/status vocabulary, and owns the generic run/event
state.

Documented event sequences (deterministic):

    Successful:   run_started → message_started → message_content → run_completed
    Cancelled:    run_started → run_cancelled
                  (cancellation that wins stops the run; no message events or
                  run_completed are ever emitted afterwards)
    Failed:       run_started → run_failed

The service is the lifecycle coordinator and the single AVA owner of run
identities, event identities, and run/event state. Routes stay thin and are
never allowed to read concrete adapter internals.

Run/event state is accessed only through the ``RunRepository`` and
``RunEventRepository`` ports; the service never names concrete repository
implementations. Application composition injects the selected implementation:
the in-memory stores by default, or the durable relational adapters when
``AVA_PERSISTENCE=relational`` (Step 4.8).

The retrieval methods (``get_run`` / ``get_run_events``) are snapshot
retrieval only — they are not streaming.
"""

import logging
from uuid import uuid4

from ava.agents.contracts import AgentPort
from ava.contracts.events import EventType, RunEvent
from ava.contracts.json_types import JsonValue
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.repositories.run_event_repository import RunEventRepository
from ava.repositories.run_repository import RunRepository

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED}
)

# ============================================================
# BEGIN: Run Service
# ============================================================


class RunService:
    """Coordinates a single agent run across the agent port."""

    def __init__(
        self,
        agent: AgentPort,
        *,
        run_repository: RunRepository,
        run_event_repository: RunEventRepository,
    ) -> None:
        """Construct the run service over an agent adapter and repository ports.

        Args:
            agent: The configured agent adapter (an ``AgentPort``).
            run_repository: AVA run-state repository. Composition injects the
                in-memory ``RunStore`` by default (Step 4.8 also selects the
                durable relational adapter under ``AVA_PERSISTENCE=relational``).
            run_event_repository: AVA event repository. Composition injects the
                in-memory ``RunEventStore`` by default (Step 4.8 also selects
                the durable relational adapter under
                ``AVA_PERSISTENCE=relational``).
        """
        self._agent = agent
        self._run_repository = run_repository
        self._run_event_repository = run_event_repository

    async def start_run(self, request: RunRequest) -> RunResponse:
        """Start a run, generating the AVA-owned run identifier.

        Run identifiers and event identifiers are owned and created by AVA,
        never by the client or the agent adapter.
        """
        run_id = str(uuid4())
        self._run_repository.create(run_id)
        self._append(run_id, EventType.RUN_STARTED, self._json_payload())
        self._run_repository.update_status(run_id, RunStatus.RUNNING)

        result = await self._agent.start_run(run_id=run_id, request=request)
        self._run_repository.set_execution_selection(run_id, result.execution_selection)

        current = self._run_repository.get(run_id)
        if current is not None and current.status == RunStatus.CANCELLED:
            # Cancellation won while the agent was in progress; do not emit
            # message or completion events.
            return RunResponse(
                run_id=run_id,
                status=RunStatus.CANCELLED,
                execution_selection=current.execution_selection if current else None,
            )

        if result.status == RunStatus.COMPLETED:
            message_id = str(uuid4())
            self._append(
                run_id,
                EventType.MESSAGE_STARTED,
                self._json_payload(message_id=message_id, role="assistant"),
            )
            self._append(
                run_id,
                EventType.MESSAGE_CONTENT,
                self._json_payload(
                    message_id=message_id,
                    content=result.content or "",
                ),
            )
            self._run_repository.update_status(run_id, RunStatus.COMPLETED)
            self._append(run_id, EventType.RUN_COMPLETED, self._json_payload())
            logger.debug("Run %s completed", run_id)
            return RunResponse(
                run_id=run_id,
                status=RunStatus.COMPLETED,
                execution_selection=result.execution_selection,
            )

        if result.status == RunStatus.FAILED:
            self._run_repository.update_status(run_id, RunStatus.FAILED)
            self._append(
                run_id,
                EventType.RUN_FAILED,
                self._json_payload(
                    error_code="agent_failed",
                    message="The agent failed to complete the run.",
                    recoverable=False,
                ),
            )
            logger.debug("Run %s failed", run_id)
            return RunResponse(run_id=run_id, status=RunStatus.FAILED, execution_selection=result.execution_selection)

        # The agent observed cancellation mid-flight. Record the terminal
        # state and the run_cancelled event (duplicate-protected by the
        # event store for concurrent cancellation requests).
        self._run_repository.update_status(run_id, RunStatus.CANCELLED)
        self._append(run_id, EventType.RUN_CANCELLED, self._json_payload())
        logger.debug("Run %s cancelled", run_id)
        return RunResponse(run_id=run_id, status=RunStatus.CANCELLED, execution_selection=result.execution_selection)

    async def cancel_run(self, run_id: str) -> RunResponse:
        """Cancel a run and update AVA run/event state consistently.

        Behavior:
        * An unknown run is an idempotent no-op reported as cancelled.
        * A terminal run reports its recorded status without new events.
        * Otherwise the agent is asked to cancel; a cancelled outcome
          updates state and records a single ``run_cancelled`` event.
        """
        run = self._run_repository.get(run_id)
        if run is None:
            return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)
        if run.status in _TERMINAL_STATUSES:
            return RunResponse(run_id=run_id, status=run.status, execution_selection=run.execution_selection)

        response = await self._agent.cancel_run(run_id)
        if response.status in _TERMINAL_STATUSES:
            self._run_repository.update_status(run_id, response.status)
            if response.status == RunStatus.CANCELLED:
                self._append(run_id, EventType.RUN_CANCELLED, self._json_payload())
        return response.model_copy(update={"execution_selection": run.execution_selection})

    def get_run(self, run_id: str) -> RunResponse | None:
        """Return the run's stored state, or ``None`` for an unknown run."""
        run = self._run_repository.get(run_id)
        if run is None:
            return None
        return RunResponse(run_id=run.run_id, status=run.status, execution_selection=run.execution_selection)

    def get_run_events(self, run_id: str) -> list[RunEvent] | None:
        """Return the run's events in append order, or ``None`` if unknown.

        Snapshot retrieval only; this is not streaming.
        """
        if self._run_repository.get(run_id) is None:
            return None
        return list(self._run_event_repository.get_events(run_id))

    def _append(
        self,
        run_id: str,
        event_type: EventType,
        payload: dict[str, JsonValue],
    ) -> None:
        """Append an AVA-owned RunEvent with an AVA-generated event id."""
        self._run_event_repository.append(
            RunEvent(
                event_id=str(uuid4()),
                run_id=run_id,
                event_type=event_type,
                payload=payload,
            )
        )

    def _json_payload(self, **kwargs: JsonValue) -> dict[str, JsonValue]:
        """Build a JSON-safe event payload from typed keyword values."""
        return dict(kwargs)


# ============================================================
# END: Run Service
# ============================================================
