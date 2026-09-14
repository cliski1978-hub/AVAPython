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
from ava.services.run_event_store import RunEventStore
from ava.services.run_store import RunStore

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
        run_store: RunStore | None = None,
        event_store: RunEventStore | None = None,
    ) -> None:
        """Construct the run service with an agent adapter and AVA-owned state.

        Args:
            agent: The configured agent adapter (an ``AgentPort``).
            run_store: Generic AVA run-state store; a fresh in-memory store
                is created when omitted.
            event_store: Generic AVA event store; a fresh in-memory store is
                created when omitted.
        """
        self._agent = agent
        self._run_store = run_store or RunStore()
        self._event_store = event_store or RunEventStore()

    async def start_run(self, request: RunRequest) -> RunResponse:
        """Start a run, generating the AVA-owned run identifier.

        Run identifiers and event identifiers are owned and created by AVA,
        never by the client or the agent adapter. No persistence is
        introduced in this sprint.
        """
        run_id = str(uuid4())
        self._run_store.create(run_id)
        self._append(run_id, EventType.RUN_STARTED, self._json_payload())
        self._run_store.update_status(run_id, RunStatus.RUNNING)

        result = await self._agent.start_run(run_id=run_id, request=request)

        current = self._run_store.get(run_id)
        if current is not None and current.status == RunStatus.CANCELLED:
            # Cancellation won while the agent was in progress; do not emit
            # message or completion events.
            return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)

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
            self._run_store.update_status(run_id, RunStatus.COMPLETED)
            self._append(run_id, EventType.RUN_COMPLETED, self._json_payload())
            logger.debug("Run %s completed", run_id)
            return RunResponse(run_id=run_id, status=RunStatus.COMPLETED)

        if result.status == RunStatus.FAILED:
            self._run_store.update_status(run_id, RunStatus.FAILED)
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
            return RunResponse(run_id=run_id, status=RunStatus.FAILED)

        # The agent observed cancellation mid-flight. Record the terminal
        # state and the run_cancelled event (duplicate-protected by the
        # event store for concurrent cancellation requests).
        self._run_store.update_status(run_id, RunStatus.CANCELLED)
        self._append(run_id, EventType.RUN_CANCELLED, self._json_payload())
        logger.debug("Run %s cancelled", run_id)
        return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)

    async def cancel_run(self, run_id: str) -> RunResponse:
        """Cancel a run and update AVA run/event state consistently.

        Behavior:
        * An unknown run is an idempotent no-op reported as cancelled.
        * A terminal run reports its recorded status without new events.
        * Otherwise the agent is asked to cancel; a cancelled outcome
          updates state and records a single ``run_cancelled`` event.
        """
        run = self._run_store.get(run_id)
        if run is None:
            return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)
        if run.status in _TERMINAL_STATUSES:
            return RunResponse(run_id=run_id, status=run.status)

        response = await self._agent.cancel_run(run_id)
        if response.status in _TERMINAL_STATUSES:
            self._run_store.update_status(run_id, response.status)
            if response.status == RunStatus.CANCELLED:
                self._append(run_id, EventType.RUN_CANCELLED, self._json_payload())
        return response

    def get_run(self, run_id: str) -> RunResponse | None:
        """Return the run's stored state, or ``None`` for an unknown run."""
        run = self._run_store.get(run_id)
        if run is None:
            return None
        return RunResponse(run_id=run.run_id, status=run.status)

    def get_run_events(self, run_id: str) -> list[RunEvent] | None:
        """Return the run's events in append order, or ``None`` if unknown.

        Snapshot retrieval only; this is not streaming.
        """
        if self._run_store.get(run_id) is None:
            return None
        return self._event_store.get_events(run_id)

    def _append(
        self,
        run_id: str,
        event_type: EventType,
        payload: dict[str, JsonValue],
    ) -> None:
        """Append an AVA-owned RunEvent with an AVA-generated event id."""
        self._event_store.append(
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