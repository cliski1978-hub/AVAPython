"""Run service.

Coordinates an AVA run as a normalized sequence of AVA-owned events using
only the Sprint 1 event/status vocabulary, and owns the generic run/event
state.

This service orchestrates a run; it does not decide what a run's status may
change to. Every durable status change goes through
:class:`~ava.services.run_lifecycle_service.RunLifecycleService`, the single
transition authority, which validates the move against the authoritative record
and writes the status plus its lifecycle event. The service therefore contains
no transition table, no terminal-status list, and no direct
``RunRepository.update_status`` call: those rules live in exactly one place
(Phase 5.23).

Documented event sequences (deterministic):

    Successful:   run_started → message_started → message_content* → run_completed
    Cancelled:    run_started → message_started → message_content* → run_cancelled
    Failed:       run_started → message_started → message_content* → run_failed

``message_content`` is a full current-content snapshot. Zero or many snapshots
may precede a terminal fact; content already persisted remains truthful after
failure or cancellation.

Ordering rule: a status is always written before the lifecycle event that
records it, so an event can never claim a state the authoritative run does not
have. A missing event is possible if the process dies between the two writes;
a premature event is not. See the lifecycle module for why that direction is
the safe one.

The service is the lifecycle coordinator and the single AVA owner of run
identities, event identities, and run/event state. Routes stay thin and are
never allowed to read concrete adapter internals.

Run/event state is accessed only through the ``RunRepository`` and
``RunEventRepository`` ports; the service never names concrete repository
implementations. Application composition injects the selected implementation:
the in-memory stores by default, or the durable relational adapters when
``AVA_PERSISTENCE=relational`` (Step 4.8).

The service does not assemble conversational history. When a run is linked to
a conversation, the injected ``ContextConstructionService`` produces the
neutral context before the run starts, and the service only forwards it. An
unlinked run keeps its prompt-only path unchanged.

The retrieval methods (``get_run`` / ``get_run_events``) are snapshot
retrieval only — they are not streaming.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from ava.agents.contracts import AgentPort, AgentRunResult, ExecutionConfigurationError
from ava.contracts.attempts import can_be_superseded
from ava.contracts.conversations import MessageRole, MessageStatus, RunContext
from ava.contracts.events import EventType, RunEvent
from ava.contracts.failures import FailureCode, failure_payload
from ava.contracts.json_types import JsonValue
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.contracts.run_inspection import ContextWindowAccounting, RunInspection, RunInspectionSnapshot, RunListItem
from ava.repositories.conversation_repository import ConversationRepository
from ava.repositories.message_repository import MessageRecord, MessageRepository
from ava.repositories.run_event_repository import RunEventRepository
from ava.repositories.run_repository import ActiveConversationRunError, RunRecord, RunRepository
from ava.services.assistant_response_service import AssistantResponseService
from ava.services.context_construction_service import ContextConstructionService
from ava.services.run_context_preparation_service import RunContextPreparationService
from ava.services.run_lifecycle_service import (
    InvalidRunTransitionError,
    RunLifecycleService,
    UnknownRunError,
)

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "credential",
}


def _redact(value: object, key: str = "") -> JsonValue:
    """Redact credential-shaped values at the backend inspection boundary."""
    normalized = key.lower().replace("-", "_")
    token_accounting_fields = {
        "context_window_tokens",
        "input_budget_tokens",
        "estimated_input_tokens",
        "output_reserve_tokens",
    }
    if (
        normalized in _SENSITIVE_KEYS
        or (normalized.endswith("_token") and normalized not in token_accounting_fields)
        or normalized.endswith("_secret")
    ):
        return "[REDACTED]"
    if normalized in {"headers", "environment", "env"}:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(child_key): _redact(child_value, str(child_key)) for child_key, child_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def sanitize_inspection(snapshot: RunInspectionSnapshot) -> RunInspectionSnapshot:
    """Return a snapshot with credential-shaped fields removed recursively."""
    return RunInspectionSnapshot.model_validate(_redact(snapshot.model_dump(mode="json")))


def sanitize_event(event: RunEvent) -> RunEvent:
    """Return an event whose arbitrary payload cannot expose credential keys."""
    return event.model_copy(update={"payload": _redact(event.payload)})


#: The stable body of a ``run_failed`` event. AVA reports one failure shape to
#: clients; the run's own log carries the cause, and Phase 5.34 owns richer
#: error reporting.
_AGENT_FAILURE_PAYLOAD: dict[str, JsonValue] = failure_payload(FailureCode.AGENT_FAILED)

#: Reason on an ``ExecutionConfigurationError`` -> public failure code. Every
#: entry is a key of :data:`ava.contracts.failures.PUBLIC_FAILURE_MESSAGES`, so
#: the safe message and the recoverability come from the one taxonomy rather
#: than being restated here.
_CONFIGURATION_FAILURES: dict[str, str] = {
    "execution_defaults_not_configured": FailureCode.CONFIGURATION_MISSING,
    "configured_reference_missing": FailureCode.CONFIGURATION_INVALID,
    "configured_reference_disabled": FailureCode.CONFIGURATION_INVALID,
    "model_provider_mismatch": FailureCode.MODEL_UNAVAILABLE,
    "runtime_adapter_not_registered": FailureCode.RUNTIME_UNAVAILABLE,
    "provider_adapter_not_registered": FailureCode.PROVIDER_CONNECTION_UNAVAILABLE,
    "credential_resolution_failed": FailureCode.CREDENTIAL_UNAVAILABLE,
    "configured_model_ineligible": FailureCode.MODEL_UNAVAILABLE,
    "provider_construction_failed": FailureCode.PROVIDER_CONNECTION_UNAVAILABLE,
}

# A missing or disabled record is normally a configuration edit, so it maps to
# ``configuration_invalid``. An unavailable *runtime* is the exception: the
# configuration is not wrong, the execution backend cannot be used, and the
# operator needs to be pointed at the runtime rather than at their settings
# combination. Reporting it as a configuration error sends them to fix something
# that is already correct.
_KIND_OVERRIDES: dict[str, str] = {
    "runtime configuration": FailureCode.RUNTIME_UNAVAILABLE,
}


def _configuration_failure_code(exc: ExecutionConfigurationError) -> str:
    """Map one configuration error to its public code.

    The reason is the primary signal, but ``configured_reference_missing`` and
    ``configured_reference_disabled`` are raised for all three configured
    domains, so the record's ``kind`` refines the outcome for those.
    """
    code = _CONFIGURATION_FAILURES.get(exc.reason, FailureCode.CONFIGURATION_INVALID)
    kind = getattr(exc, "kind", None)
    if isinstance(kind, str):
        return _KIND_OVERRIDES.get(kind, code)
    return code


class CancellationRequestError(RuntimeError):
    """Cancellation persistence failed; the caller may safely retry."""


class RunRelationshipError(ValueError):
    """A requested durable run/message relationship is invalid."""


class RunNotSupersedableError(RunRelationshipError):
    """A retry/regenerate named a prior run that cannot be branched from.

    Distinct from a generic relationship error so the route can report an
    eligibility refusal honestly instead of a malformed request: the request is
    well formed, the targeted run is simply not a valid source of a new attempt
    (unknown, cross-conversation, or still active).
    """


class ConversationRunActiveError(RunRelationshipError):
    """A valid request conflicts with the conversation's active run."""


@dataclass(frozen=True)
class PreparedRun:
    """A durable, dispatched run awaiting agent execution.

    This is an application-internal handoff, not a public contract. Creating it
    makes the AVA run identity and its started event observable before an agent
    can finish, while leaving execution and lifecycle ownership unchanged.
    """

    run_id: str
    request: RunRequest
    context: RunContext | None
    assistant_message_id: str | None
    output_message_id: str


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
        conversation_repository: ConversationRepository | None = None,
        message_repository: MessageRepository | None = None,
        context_service: ContextConstructionService | None = None,
        context_preparation_service: RunContextPreparationService | None = None,
        lifecycle: RunLifecycleService | None = None,
        approval_cancellation: Callable[[str], object] | None = None,
    ) -> None:
        """Construct the run service over an agent adapter and repository ports.

        Args:
            agent: The configured agent adapter (an ``AgentPort``).
            run_repository: AVA run-state repository. Composition injects the
                in-memory ``RunStore`` by default (Step 4.8 also selects the
                durable relational adapter under ``AVA_PERSISTENCE=relational``).
            run_event_repository: AVA event repository. Composition injects
                the in-memory ``RunEventStore`` by default (Step 4.8 also
                selects the durable relational adapter under
                ``AVA_PERSISTENCE=relational``).
            context_service: Constructs the durable execution context for
                conversation-linked runs. A linked run requires it: without
                it the relationship is rejected rather than silently executed
                with a prompt-only history.
            lifecycle: The run lifecycle authority. Composition may inject a
                configured instance; by default one is built over the injected
                repositories, so no caller can accidentally run without
                validated transitions.
        """
        self._agent = agent
        self._run_repository = run_repository
        self._run_event_repository = run_event_repository
        self._conversation_repository = conversation_repository
        self._message_repository = message_repository
        self._context_service = context_service
        self._context_preparation_service = context_preparation_service
        self._lifecycle = lifecycle or RunLifecycleService(
            run_repository=run_repository, run_event_repository=run_event_repository
        )
        self._approval_cancellation = approval_cancellation
        self._assistant_responses = AssistantResponseService(
            run_repository=run_repository,
            run_event_repository=run_event_repository,
            message_repository=message_repository,
        )

    async def start_run(self, request: RunRequest) -> RunResponse:
        """Start a run, generating the AVA-owned run identifier.

        Run identifiers and event identifiers are owned and created by AVA,
        never by the client or the agent adapter.

        Ordering, which is the observable contract:

        1. the relationship is validated and the durable context is built —
           before any run record exists, so a rejected request leaves no run;
        2. the run is created ``pending``;
        3. the durable assistant placeholder is created and linked;
        4. the run becomes ``running`` and ``run_started`` is recorded;
        5. the agent executes; each non-empty changed content snapshot is
           persisted before its matching event, and final-only output uses the
           same path;
        6. the terminal status is written, then its lifecycle event.

        A run that cannot complete because execution was cancelled mid-flight
        reports the cancellation that already won; it never resurrects itself
        as completed.
        """
        prepared = self.prepare_run(request)
        if isinstance(prepared, RunResponse):
            return prepared
        return await self.execute_prepared_run(prepared)

    def prepare_run(self, request: RunRequest) -> PreparedRun | RunResponse:
        """Create and dispatch a run before its agent execution begins.

        The returned :class:`PreparedRun` is consumed by the API route's
        background task. Its public run response is therefore available before
        a stream is opened. This method never schedules work itself.
        """
        request = self._resolve_supersession(request)
        self._validate_relationship_request(request)
        context = self._build_context(request)
        run_id = str(uuid4())
        try:
            self._lifecycle.create_run(
                run_id,
                conversation_id=request.conversation_id,
                source_user_message_id=request.source_user_message_id,
                execution_mode=request.execution_mode,
            )
        except ActiveConversationRunError as exc:
            raise ConversationRunActiveError("This conversation already has an active run.") from exc
        assistant_message_id = self._create_assistant_placeholder(run_id, request)
        output_message_id = assistant_message_id or str(uuid4())
        # Status first, then the fact: a ``run_started`` event never exists for
        # a run that is still ``pending``.
        try:
            self._lifecycle.start(run_id)
        except InvalidRunTransitionError as rejected:
            # The run was cancelled between creation and dispatch. Handing it to
            # an agent now would be starting work the user already stopped, and
            # the placeholder stays: it projects ``cancelled`` from its run.
            logger.debug("Run %s was cancelled before execution began", run_id)
            cancelled = self._lifecycle.get(run_id)
            if cancelled is None:  # pragma: no cover - the run was just created
                raise UnknownRunError(run_id) from rejected
            return self._run_response(cancelled)

        self._assistant_responses.start_message(run_id, output_message_id)

        return PreparedRun(
            run_id=run_id,
            request=request,
            context=context,
            assistant_message_id=assistant_message_id,
            output_message_id=output_message_id,
        )

    async def execute_prepared_run(self, prepared: PreparedRun) -> RunResponse:
        """Execute a previously dispatched run and record its real outcome."""
        run_id = prepared.run_id
        request = prepared.request
        context = prepared.context
        assistant_message_id = prepared.assistant_message_id
        output_message_id = prepared.output_message_id

        def record_content(content: str) -> None:
            self._assistant_responses.record_snapshot(
                run_id=run_id,
                message_id=output_message_id,
                conversation_id=request.conversation_id,
                content=content,
            )

        def record_inspection(snapshot: RunInspectionSnapshot) -> None:
            try:
                self._run_repository.set_inspection_snapshot(run_id, sanitize_inspection(snapshot))
            except Exception:
                # Inspection is observability; persistence failure must never
                # change the outcome of model execution.
                logger.exception("Unable to persist inspection snapshot for run %s", run_id)

        try:
            resolved_execution = None
            if self._context_preparation_service is not None:
                prepared_context = await self._context_preparation_service.prepare(request, context)
                context = prepared_context.context
                resolved_execution = prepared_context.execution
            if resolved_execution is None:
                result = await self._agent.start_run_streaming(
                    run_id=run_id,
                    request=request,
                    context=context,
                    on_content=record_content,
                    on_inspection=record_inspection,
                )
            else:
                result = await self._agent.start_run_streaming(
                    run_id=run_id,
                    request=request,
                    context=context,
                    on_content=record_content,
                    on_inspection=record_inspection,
                    resolved_execution=resolved_execution,
                )
        except ExecutionConfigurationError as exc:
            self._lifecycle.fail(run_id, payload=self._configuration_failure_payload(exc))
            return self._run_response(self._lifecycle.get(run_id) or self._lifecycle.fail(run_id))
        if result.inspection_snapshot is not None:
            record_inspection(result.inspection_snapshot)
        self._run_repository.set_execution_selection(run_id, result.execution_selection)

        current = self._lifecycle.get(run_id)
        if current is not None and current.status.is_terminal:
            # Another writer settled the run while the agent was in progress; do
            # not emit message or completion events for it.
            return RunResponse(
                run_id=run_id,
                status=current.status,
                execution_selection=current.execution_selection,
                conversation_id=request.conversation_id,
                source_user_message_id=request.source_user_message_id,
                assistant_message_id=current.assistant_message_id,
                cancellation_requested_at=current.cancellation_requested_at,
                execution_mode=current.execution_mode,
            )

        if result.status == RunStatus.COMPLETED:
            # Final-only adapters and genuine streaming adapters converge here.
            # An identical final snapshot is a no-op; a differing final response
            # deterministically replaces the accumulated snapshot before the
            # run reaches completed.
            self._assistant_responses.record_snapshot(
                run_id=run_id,
                message_id=output_message_id,
                conversation_id=request.conversation_id,
                content=result.content or "",
            )
            return self._terminal_response(
                self._lifecycle.complete,
                run_id,
                request,
                result,
                assistant_message_id=assistant_message_id,
            )

        if result.status == RunStatus.FAILED:
            response = self._terminal_response(self._fail_transition, run_id, request, result, pass_result=True)
            logger.debug("Run %s failed", run_id)
            return response

        # The agent observed cancellation mid-flight. Record the terminal
        # state and the run_cancelled event (duplicate-protected by the
        # lifecycle authority and by the event store for concurrent
        # cancellation requests).
        response = self._terminal_response(self._lifecycle.cancel, run_id, request, result)
        logger.debug("Run %s cancelled", run_id)
        return response

    @staticmethod
    def _configuration_failure_payload(exc: ExecutionConfigurationError) -> dict[str, JsonValue]:
        """The durable payload for a failure raised while resolving execution."""
        return failure_payload(_configuration_failure_code(exc))

    def _fail_transition(self, run_id: str, result: AgentRunResult | None = None) -> RunRecord:
        """Apply the canonical failure transition with its stable error body.

        The run reaches this point from every failing layer, but not all
        failures are the same event. A code the execution layers already
        classified is persisted as that code; only a genuinely unclassified
        failure takes the generic :attr:`FailureCode.AGENT_FAILED` body.

        This is the single place a public failure payload is built, so the
        durable record can never carry an internal message, a provider status,
        or a code outside the public taxonomy.
        """
        payload = failure_payload(result.failure_code) if result is not None else failure_payload(None)
        return self._lifecycle.fail(run_id, payload=payload)

    def _terminal_response(
        self,
        apply_transition: Callable[..., RunRecord],
        run_id: str,
        request: RunRequest,
        result: AgentRunResult,
        *,
        assistant_message_id: str | None = None,
        pass_result: bool = False,
    ) -> RunResponse:
        """Apply a terminal transition and answer with the authoritative status.

        If the transition is rejected because another writer already moved the
        run to a different terminal state — the complete-versus-cancel race —
        the run's own record is the answer. The service reports that recorded
        outcome instead of forcing its intended one, so exactly one terminal
        state is ever persisted for a run.

        ``pass_result`` forwards the agent result to the transition, for the
        failure transition alone, which needs the classification the execution
        layers produced. It defaults off so no other transition can be handed a
        result it does not use.
        """
        try:
            record: RunRecord | None = apply_transition(run_id, result) if pass_result else apply_transition(run_id)
        except InvalidRunTransitionError as exc:
            logger.info(
                "Run %s is already %s; requested %s was rejected",
                exc.run_id,
                exc.from_status.value,
                exc.to_status.value,
            )
            record = self._lifecycle.get(run_id)
        if record is None:  # pragma: no cover - the run exists or was just created
            raise UnknownRunError(run_id)
        return RunResponse(
            run_id=run_id,
            status=record.status,
            execution_selection=result.execution_selection or record.execution_selection,
            conversation_id=request.conversation_id,
            source_user_message_id=request.source_user_message_id,
            assistant_message_id=assistant_message_id or record.assistant_message_id,
            cancellation_requested_at=record.cancellation_requested_at,
            execution_mode=record.execution_mode,
        )

    async def cancel_run(self, run_id: str) -> RunResponse:
        """Request cancellation of a run, durably and before acting on it.

        The order is the guarantee:

        1. the cancellation *request* is persisted, so a process that dies
           between here and the runtime still leaves evidence that the user
           asked;
        2. execution is asked to stop — best effort, and never a condition for
           the request having been made;
        3. the terminal outcome is recorded when there is one to record.

        Behavior:

        * An unknown run is an idempotent no-op reported as cancelled, and
          records no request: there is no run to have an intent about.
        * A run that has already settled reports its recorded status and gains no
          request. It was not cancelled on purpose; it finished first.
        * A ``pending`` or ``waiting_for_approval`` run has no execution in
          flight, so it settles immediately through the lifecycle authority
          without troubling a runtime that was never handed the run.
        * A ``running`` run is asked to stop through the agent. If that attempt
          fails, the request stays persisted and the response reports the run's
          real status — a failed attempt to stop is not the same as a run that
          was never asked to stop, and must not read as one.
        """
        try:
            record = self._lifecycle.get(run_id)
            if record is None:
                return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)
            # Commit intent before invoking any runtime operation.
            record = self._lifecycle.request_cancellation(run_id)
        except Exception as exc:
            raise CancellationRequestError("Unable to persist cancellation request.") from exc
        if not record.status.is_active:
            return self._run_response(record)

        if self._approval_cancellation is not None:
            try:
                self._approval_cancellation(run_id)
            except Exception:
                # The durable cancellation request makes any later approval
                # decision fail closed even if history reconciliation fails.
                logger.exception("Unable to reconcile approvals for cancelled run %s", run_id)

        if record.status is RunStatus.RUNNING:
            record = await self._stop_execution(run_id, record)
        else:
            # Nothing is executing: the request is already the whole story, so
            # the run settles locally instead of asking a runtime to stop work
            # that was never started.
            self._record_terminal_from_agent(run_id, RunStatus.CANCELLED)
            record = self._lifecycle.get(run_id) or record
            logger.debug("Run %s cancelled before execution began", run_id)
        return self._run_response(record)

    async def _stop_execution(self, run_id: str, record: RunRecord) -> RunRecord:
        """Ask the agent to stop a running execution and settle what it reports.

        The agent is the only component that knows whether the stop worked. A
        failure there is logged and absorbed: the durable request already
        exists, and translating a runtime error into "the run is still running
        and nobody asked" would erase the one fact this phase exists to protect.
        A provider or SDK exception is never surfaced to the client.
        """
        try:
            response = await self._agent.cancel_run(run_id)
        except Exception:
            logger.exception("Unable to stop run %s; its cancellation request stands", run_id)
            return self._lifecycle.get(run_id) or record
        if response.status.is_terminal:
            self._record_terminal_from_agent(run_id, response.status)
            settled = self._lifecycle.get(run_id)
            if settled is not None:
                # A completion may have won the race; the persisted run is the
                # answer, not what this call intended.
                return settled
        return self._lifecycle.get(run_id) or record

    def _run_response(self, record: RunRecord) -> RunResponse:
        """Answer with the run's authoritative state, including its intent.

        The request timestamp alone never claims a run stopped. A caller reading
        ``status == running`` with a ``cancellation_requested_at`` learns that
        the request is durable and the outcome is still open.
        """
        return RunResponse(
            run_id=record.run_id,
            status=record.status,
            execution_selection=record.execution_selection,
            conversation_id=record.conversation_id,
            source_user_message_id=record.source_user_message_id,
            assistant_message_id=record.assistant_message_id,
            cancellation_requested_at=record.cancellation_requested_at,
            execution_mode=record.execution_mode,
        )

    def _record_terminal_from_agent(self, run_id: str, status: RunStatus) -> None:
        """Persist the terminal status an agent reported for an active run.

        The agent's outcome is an AVA-level status, never a provider exception.
        Every reported terminal state is written through the same authority with
        its matching lifecycle event, so a run reported as completed by a
        cancellation race gains the ``run_completed`` fact it was previously
        missing. A rejected transition means the run already settled; the
        recorded state stands.
        """
        try:
            self._lifecycle.record_reported_terminal(run_id, status, payload=_AGENT_FAILURE_PAYLOAD)
        except InvalidRunTransitionError as exc:
            logger.info(
                "Run %s is already %s; agent-reported %s was rejected",
                exc.run_id,
                exc.from_status.value,
                exc.to_status.value,
            )

    def get_run(self, run_id: str) -> RunResponse | None:
        """Return the run's stored state, or ``None`` for an unknown run.

        The snapshot carries the durable cancellation request, so a client
        refresh learns that a run was asked to stop without reconstructing it
        from the event log.
        """
        run = self._run_repository.get(run_id)
        if run is None:
            return None
        return self._run_response(run)

    def preview_context_window(self, request: RunRequest) -> ContextWindowAccounting | None:
        """Return an unsent draft's backend-owned context budget without persistence."""
        context = None
        if request.conversation_id is not None:
            if self._context_service is None:
                raise RunRelationshipError("linked previews require a context construction service")
            context = self._context_service.build_for_preview(request.conversation_id)
        if self._context_preparation_service is not None:
            context = self._context_preparation_service.preview(request, context)
        return self._agent.preview_context_window(request, context=context)

    def _build_context(self, request: RunRequest) -> RunContext | None:
        """Build the run's durable context before any run state is written.

        A conversation-linked run always gets its context, and a failure to
        resolve it surfaces as a ``ContextConstructionError`` instead of a
        silent prompt-only run. An unlinked run has no durable context, so
        ``None`` is returned and the runtime keeps its existing single-prompt
        behavior.
        """
        if request.conversation_id is None:
            return None
        if self._context_service is None:
            raise RunRelationshipError("linked runs require a context construction service")
        return self._context_service.build_for_source(request.conversation_id, request.source_user_message_id)

    def _resolve_supersession(self, request: RunRequest) -> RunRequest:
        """Re-anchor a retry/regenerate request onto durable persistence.

        When ``retry_of_run_id`` is present the request becomes a new attempt
        branching from that prior run. Two things are then read from
        authoritative storage instead of the request body:

        * the source user message, taken from the prior run's own durable
          ``source_user_message_id``. A client that supplies a different one is
          refused rather than silently trusted, so an attempt can never be
          attributed to a turn the prior run did not answer.
        * the prompt, taken from that source user message's persisted content.
          No duplicate user message is created and no client-authored text
          stands in for durable history.

        The prior run must already be terminal. That single status guard is what
        stops a stale client from branching a still-executing turn, and it needs
        no knowledge of whether the intent was a retry or a regenerate — the
        backend deliberately does not learn which button was pressed.

        The returned request is a fresh, fully validated one. ``execution`` and
        ``workspace_id`` are carried through unchanged and are deliberately NOT
        read back from the prior run: the new run resolves its own execution
        configuration at creation time, so neither an old run's resolved runtime
        nor its credentials are ever inherited.

        Nothing here writes to the prior run. It is terminal history before
        this method is called and it is unchanged after it returns.
        """
        if request.retry_of_run_id is None:
            return request
        prior = self._run_repository.get(request.retry_of_run_id)
        if prior is None:
            raise RunNotSupersedableError("retry target run does not exist")
        if prior.conversation_id is None:
            raise RunNotSupersedableError("retry target run is not conversation-linked")
        if prior.conversation_id != request.conversation_id:
            raise RunNotSupersedableError("retry target run belongs to a different conversation")
        if not can_be_superseded(prior.status):
            # An active run is never a retry or regenerate target: the current
            # attempt must settle before its turn can be branched. Concurrency
            # rules for genuinely concurrent turns are a later phase.
            raise RunNotSupersedableError(f"retry target run is {prior.status.value} and must settle first")
        source_user_message_id = prior.source_user_message_id
        if source_user_message_id is None:
            raise RunNotSupersedableError("retry target run has no durable source user message")
        if request.source_user_message_id is not None and request.source_user_message_id != source_user_message_id:
            raise RunNotSupersedableError("retry target run answers a different source user message")
        if self._message_repository is None:
            raise RunRelationshipError("linked runs require a message repository")
        source = self._message_repository.get(prior.conversation_id, source_user_message_id)
        if source is None or source.role != MessageRole.USER:
            raise RunNotSupersedableError("retry target run's source user message is no longer durable")
        # Rebuilding the request (rather than mutating it) re-runs contract
        # validation, and the object stored on PreparedRun is exactly what was
        # executed rather than what the client claimed.
        return RunRequest(
            prompt=source.content,
            conversation_id=prior.conversation_id,
            source_user_message_id=source_user_message_id,
            execution=request.execution,
            workspace_id=request.workspace_id,
            retry_of_run_id=request.retry_of_run_id,
            execution_mode=request.execution_mode,
        )

    def _validate_relationship_request(self, request: RunRequest) -> None:
        """Validate optional linked-run inputs without guessing legacy links."""
        if request.conversation_id is None and request.source_user_message_id is None:
            return
        if request.conversation_id is None or request.source_user_message_id is None:
            raise RunRelationshipError("conversation_id and source_user_message_id must be supplied together")
        if self._conversation_repository is None or self._message_repository is None:
            raise RunRelationshipError("linked runs require conversation and message repositories")
        if self._conversation_repository.get(request.conversation_id) is None:
            raise RunRelationshipError("run conversation does not exist")
        source = self._message_repository.get(request.conversation_id, request.source_user_message_id)
        if source is None:
            raise RunRelationshipError("source user message does not belong to run conversation")
        if source.role != MessageRole.USER:
            raise RunRelationshipError("source user message must have role user")

    def _create_assistant_placeholder(self, run_id: str, request: RunRequest) -> str | None:
        """Create the durable assistant response before execution starts.

        Its persisted ``pending`` value is only the creation placeholder; read
        projections derive the public status from the authoritative run.
        """
        if request.conversation_id is None:
            return None
        if self._message_repository is None:
            raise RunRelationshipError("linked runs require a message repository")
        now = datetime.now(UTC)
        message_id = str(uuid4())
        self._message_repository.append(
            MessageRecord(
                message_id=message_id,
                conversation_id=request.conversation_id,
                role=MessageRole.ASSISTANT,
                content="",
                status=MessageStatus.PENDING,
                source_run_id=run_id,
                created_at=now,
                updated_at=now,
            )
        )
        if self._run_repository.set_assistant_message_id(run_id, message_id) is None:
            raise RunRelationshipError("run repository cannot persist assistant message relationship")
        return message_id

    def get_run_events(self, run_id: str, *, after_sequence: int = 0) -> list[RunEvent] | None:
        """Return the run's events in append order, or ``None`` if unknown.

        Snapshot retrieval only; this is not streaming.
        """
        if self._run_repository.get(run_id) is None:
            return None
        return list(self._run_event_repository.list_after_sequence(run_id, after_sequence))

    def list_runs_for_conversation(self, conversation_id: str) -> list[RunRecord]:
        return self._run_repository.list_for_conversation(conversation_id)

    def list_run_summaries_for_conversation(self, conversation_id: str) -> list[RunListItem]:
        return [
            RunListItem(
                run_id=record.run_id,
                status=record.status,
                created_at=record.created_at,
                updated_at=record.updated_at,
                execution_mode=record.execution_mode,
            )
            for record in self.list_runs_for_conversation(conversation_id)
        ]

    def get_run_inspection(self, run_id: str) -> RunInspection | None:
        record = self._run_repository.get(run_id)
        if record is None:
            return None
        message = (
            self._message_repository.get(record.conversation_id, record.assistant_message_id)
            if self._message_repository is not None
            and record.conversation_id is not None
            and record.assistant_message_id is not None
            else None
        )
        events = self._run_event_repository.list_after_sequence(run_id, 0)
        return RunInspection(
            run_id=record.run_id,
            conversation_id=record.conversation_id,
            source_user_message_id=record.source_user_message_id,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            execution_selection=record.execution_selection,
            execution_mode=record.execution_mode,
            assistant_message_id=record.assistant_message_id,
            assistant_message=message.content if message is not None else None,
            snapshot=sanitize_inspection(record.inspection_snapshot) if record.inspection_snapshot else None,
            events=[sanitize_event(event) for event in events],
        )

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
