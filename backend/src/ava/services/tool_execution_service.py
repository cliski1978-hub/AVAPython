"""Runtime-neutral, default-deny boundary for normalized tool invocation."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import ExecutionMode
from ava.contracts.json_types import JsonValue
from ava.contracts.tool_policy import ToolPolicyDecisionType, ToolPolicyRequest
from ava.contracts.tools import (
    ToolCapability,
    ToolDefinition,
    ToolOperationBinding,
    ToolRequest,
    ToolResult,
    ToolStatus,
)
from ava.repositories.invocation_reservation_repository import (
    InvocationReservation,
    InvocationReservationConflict,
    InvocationReservationRepository,
    InvocationReservationState,
)
from ava.repositories.run_event_repository import RunEventRepository
from ava.repositories.run_repository import RunRepository
from ava.services.approval_service import ApprovalService
from ava.services.tool_feature_service import ToolFeatureService
from ava.services.tool_policy_service import ToolPolicyService
from ava.tools.authority import ToolExecutionAuthority, ToolExecutionAuthorityPort, ToolOperationType
from ava.tools.registry import ToolRegistry
from ava.workspaces.contracts import RuntimeWorkspaceBinding

logger = logging.getLogger(__name__)


class ToolExecutionDisposition(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    DENIED = "denied"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INDETERMINATE = "indeterminate"


class ToolExecutionOutcome(BaseModel):
    """Normalized boundary result; preflight eligibility is not a grant."""

    model_config = ConfigDict(frozen=True)
    disposition: ToolExecutionDisposition
    result: ToolResult | None = None
    policy_reason: str | None = None
    preflight_decision: ToolPolicyDecisionType | None = None
    authorized_for_dispatch: bool = False


@dataclass(frozen=True)
class AuthorizedToolInvocation:
    """Narrow executor input, constructible only by this service module."""

    request: ToolRequest
    run_id: str
    execution_mode: ExecutionMode
    operation_binding: ToolOperationBinding
    workspace_id: str
    workspace: RuntimeWorkspaceBinding
    _proof: object

    def __post_init__(self) -> None:
        if self._proof is not _AUTHORIZATION_PROOF:
            raise ValueError("authorized invocations are created by ToolExecutionService")


_AUTHORIZATION_PROOF = object()


class ToolExecutorPort(Protocol):
    async def execute(self, invocation: AuthorizedToolInvocation) -> ToolResult:
        """Perform one constrained effect and return a normalized result."""
        ...


class ToolExecutionService:
    """The single AVA Core boundary from untrusted tool intent to an executor.

    There is intentionally no production executor or reservation adapter in
    Phase 6.10. A policy ALLOW is re-evaluated, authority is checked again, and
    dispatch additionally requires a current approved decision when requested,
    an executor, and a durable reservation implementation.
    """

    def __init__(
        self,
        *,
        runs: RunRepository,
        registry: ToolRegistry,
        features: ToolFeatureService,
        policy: ToolPolicyService,
        authority: ToolExecutionAuthorityPort | None = None,
        approvals: ApprovalService | None = None,
        executors: dict[str, ToolExecutorPort] | None = None,
        reservations: InvocationReservationRepository | None = None,
        run_events: RunEventRepository | None = None,
    ) -> None:
        self._runs = runs
        self._registry = registry
        self._features = features
        self._policy = policy
        self._authority = authority
        self._approvals = approvals
        self._executors = dict(executors or {})
        if any(registry.get(tool_id) is None for tool_id in self._executors):
            raise ValueError("executor mappings must reference registered tools")
        self._reservations = reservations
        self._run_events = run_events

    def _record_event(
        self,
        event_type: EventType,
        request: ToolRequest,
        mode: ExecutionMode,
        *,
        status: str,
        reason_code: str | None = None,
    ) -> None:
        """Persist safe lifecycle facts without arguments or result contents."""
        if self._run_events is None or request.run_id is None:
            return
        payload: dict[str, JsonValue] = {
            "invocation_id": request.invocation_id,
            "tool_id": request.tool_id,
            "tool_version": request.tool_version,
            "execution_mode": mode.value,
            "status": status,
        }
        if reason_code:
            payload["reason_code"] = reason_code
        try:
            self._run_events.append(
                RunEvent(
                    event_id=str(uuid4()),
                    run_id=request.run_id,
                    event_type=event_type,
                    payload=payload,
                )
            )
        except Exception:
            logger.warning("Unable to persist tool lifecycle event for run %s", request.run_id)

    def persisted_execution_mode(self, run_id: str) -> ExecutionMode | None:
        """Read the mode owned by the stored Run, never a model or runtime field."""
        run = self._runs.get(run_id)
        return run.execution_mode if run is not None else None

    def discover_tools(self, run_id: str, execution_context_ref: str) -> list[ToolDefinition]:
        """Return only tools that could reach the central dispatch boundary.

        This is still descriptive: every call is revalidated by ``execute``.
        Discovery fails closed when the run, authority, executor, or durable
        reservation is missing, and it uses the persisted Run mode.
        """
        run = self._runs.get(run_id)
        try:
            durable_reservations = self._reservations is not None and self._reservations.durable
        except Exception:
            durable_reservations = False
        if (
            run is None
            or run.status.is_terminal
            or run.cancellation_requested
            or run.execution_mode == ExecutionMode.CHAT
            or self._authority is None
            or not durable_reservations
        ):
            return []
        try:
            authority = self._authority.resolve(execution_context_ref)
        except Exception:
            return []
        if (
            not isinstance(authority, ToolExecutionAuthority)
            or authority.revoked
            or authority.run_id != run_id
            or run.owner_principal_ref is None
            or authority.principal_ref != run.owner_principal_ref
            or authority.tenant_ref != run.owner_tenant_ref
            or authority.workspace_configuration_revision is None
            or authority.grant_id is None
            or authority.grant_revision is None
            or run.execution_workspace_id != authority.context.workspace_id
            or authority.context.context_id != execution_context_ref
            or authority.context.workspace_id is None
            or not isinstance(authority.workspace, RuntimeWorkspaceBinding)
            or authority.workspace.workspace_id != authority.context.workspace_id
        ):
            return []
        minimum_capabilities = {
            ToolOperationType.READ: frozenset({ToolCapability.FILE_READ}),
            ToolOperationType.WRITE: frozenset({ToolCapability.FILE_READ, ToolCapability.FILE_WRITE}),
            ToolOperationType.EDIT: frozenset({ToolCapability.FILE_READ, ToolCapability.FILE_WRITE}),
            ToolOperationType.DELETE: frozenset(
                {ToolCapability.FILE_READ, ToolCapability.FILE_WRITE, ToolCapability.FILE_DELETE}
            ),
        }
        candidates: list[ToolDefinition] = []
        for definition in self._registry.list():
            operation = self._policy.operation_for_tool(definition.tool_id)
            if operation is None or operation == ToolOperationType.COMMAND:
                continue
            minimum = minimum_capabilities[operation]
            required = minimum | frozenset(definition.required_capabilities)
            if not minimum.issubset(definition.required_capabilities):
                continue
            if run.execution_mode == ExecutionMode.PLAN and (
                operation != ToolOperationType.READ
                or not set(definition.required_capabilities).issubset({ToolCapability.FILE_READ})
            ):
                continue
            if (
                definition.tool_id not in self._executors
                or definition.tool_id not in authority.allowed_tool_ids
                or (authority.narrowing_tool_ids is not None and definition.tool_id not in authority.narrowing_tool_ids)
            ):
                continue
            try:
                self._features.require_enabled(definition.tool_id)
            except Exception:
                continue
            workspace = authority.workspace
            if not workspace.permissions.read:
                continue
            if operation in {ToolOperationType.WRITE, ToolOperationType.EDIT, ToolOperationType.DELETE} and not (
                workspace.permissions.write
            ):
                continue
            if not required.issubset(authority.allowed_capabilities) or not required.issubset(
                authority.technical_capabilities
            ):
                continue
            candidates.append(definition)
        return candidates

    async def execute(self, request: ToolRequest, *, approval_id: str | None = None) -> ToolExecutionOutcome:
        """Validate current run/mode/policy/approval, then dispatch at most once."""
        if not isinstance(request, ToolRequest):
            return self._invalid_request()
        try:
            invocation = ToolRequest.model_validate(request.model_dump(warnings=False))
        except (TypeError, ValueError, AttributeError):
            return self._invalid_request()
        run_id = invocation.run_id
        if run_id is None:
            return self._denied(invocation, "run_identity_missing")
        run = self._runs.get(run_id)
        if run is None or run.status.is_terminal or run.cancellation_requested:
            return self._denied(invocation, "run_unavailable")
        mode = run.execution_mode
        if mode == ExecutionMode.CHAT:
            return self._denied(invocation, "chat_tool_execution_disabled")

        definition = self._registry.get(invocation.tool_id)
        if definition is None:
            return self._denied(invocation, "unknown_tool")
        operation = self._policy.operation_for_tool(invocation.tool_id)
        if operation is None:
            return self._denied(invocation, "effect_unclassified")
        if operation == ToolOperationType.COMMAND:
            return self._denied(invocation, "command_effect_unsupported")
        if mode == ExecutionMode.PLAN and operation != ToolOperationType.READ:
            return self._denied(invocation, "plan_mode_read_only")
        if mode == ExecutionMode.PLAN and not set(definition.required_capabilities).issubset(
            {ToolCapability.FILE_READ}
        ):
            return self._denied(invocation, "plan_mode_effects_not_read_only")

        try:
            self._features.require_enabled(invocation.tool_id)
        except Exception:
            # Configuration errors and disabled/missing feature state are all
            # unavailable execution, never a path around the policy service.
            return self._denied(invocation, "tool_feature_unavailable")
        if self._authority is None:
            return self._denied(invocation, "execution_authority_unavailable")
        try:
            authority = self._authority.resolve(invocation.execution_context_ref)
        except Exception:
            return self._denied(invocation, "execution_authority_unavailable")
        if (
            not isinstance(authority, ToolExecutionAuthority)
            or authority.revoked
            or authority.run_id != run_id
            or run.owner_principal_ref is None
            or authority.principal_ref != run.owner_principal_ref
            or authority.tenant_ref != run.owner_tenant_ref
            or authority.context.context_id != invocation.execution_context_ref
            or authority.context.workspace_id is None
            or authority.context.workspace_id != run.execution_workspace_id
            or authority.grant_id is None
            or authority.grant_revision is None
            or authority.workspace_configuration_revision is None
        ):
            return self._denied(invocation, "execution_authority_invalid")

        preflight = self._policy.evaluate(ToolPolicyRequest(request=invocation))
        if preflight.decision == ToolPolicyDecisionType.DENY or preflight.operation_binding is None:
            return self._denied(invocation, preflight.reason.value)
        if preflight.decision == ToolPolicyDecisionType.REQUIRES_APPROVAL:
            if approval_id is None or self._approvals is None:
                return self._awaiting_approval(invocation, preflight.reason.value)
            if not self._approvals.is_approved_for_execution(approval_id, current_request=invocation):
                return self._awaiting_approval(invocation, "approval_not_currently_valid")
        elif approval_id is not None:
            # Never let a stale approval reference bless a currently different
            # operation or change policy's decision.
            if not self._approvals or not self._approvals.is_approved_for_execution(
                approval_id, current_request=invocation
            ):
                return self._denied(invocation, "approval_operation_mismatch")

        # Re-evaluate after approval and re-resolve authority immediately before
        # the reservation boundary. A binding or revision drift closes dispatch.
        current = self._policy.evaluate(ToolPolicyRequest(request=invocation))
        try:
            current_authority = self._authority.resolve(invocation.execution_context_ref)
        except Exception:
            current_authority = None
        current_run = self._runs.get(run_id)
        if (
            current.decision != preflight.decision
            or current.operation_binding != preflight.operation_binding
            or current_authority != authority
            or current_authority is None
            or current_authority.revoked
            or current_run is None
            or current_run.status.is_terminal
            or current_run.cancellation_requested
            or current_run.execution_mode != mode
            or current_authority.principal_ref != current_run.owner_principal_ref
            or current_authority.tenant_ref != current_run.owner_tenant_ref
            or current_authority.context.workspace_id != current_run.execution_workspace_id
        ):
            return self._denied(invocation, "execution_context_changed", preflight.decision)
        executor = self._executors.get(invocation.tool_id)
        if executor is None:
            return self._denied(invocation, "executor_unavailable", preflight.decision)
        reservations = self._reservations
        if reservations is None or not reservations.durable:
            return self._denied(invocation, "durable_invocation_reservation_unavailable", preflight.decision)
        binding = preflight.operation_binding
        feature_state = self._features.state()
        reservation = InvocationReservation(
            invocation_id=invocation.invocation_id,
            run_id=run_id,
            tool_id=invocation.tool_id,
            tool_version=invocation.tool_version,
            operation_fingerprint=binding.operation_digest,
            workspace_id=authority.context.workspace_id,
            execution_context_ref=invocation.execution_context_ref,
            authority_revision_ref=authority.revision_ref,
            configuration_revision_ref=f"tool-features:{feature_state.configuration.configuration_version}",
            execution_mode=mode.value,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        try:
            reservation = reservations.reserve(reservation)
        except InvocationReservationConflict:
            return self._denied(invocation, "duplicate_invocation", preflight.decision)
        except Exception:
            return self._denied(invocation, "invocation_reservation_unavailable", preflight.decision)
        try:
            reservation = reservations.transition(
                invocation.invocation_id,
                expected_revision=reservation.revision,
                state=InvocationReservationState.EXECUTING,
            )
        except Exception:
            with suppress(Exception):
                reservations.transition(
                    invocation.invocation_id,
                    expected_revision=reservation.revision,
                    state=InvocationReservationState.FAILED,
                    error_code="execution_not_started",
                    result_status=ToolStatus.FAILED.value,
                )
            return self._denied(invocation, "invocation_reservation_unavailable", preflight.decision)
        authorized = AuthorizedToolInvocation(
            request=invocation,
            run_id=run_id,
            execution_mode=mode,
            operation_binding=binding,
            workspace_id=authority.context.workspace_id,
            workspace=authority.workspace,
            _proof=_AUTHORIZATION_PROOF,
        )
        try:
            self._record_event(EventType.TOOL_STARTED, invocation, mode, status=ToolStatus.STARTED.value)
            result = await executor.execute(authorized)
            normalized = self._normalize_executor_result(invocation, result)
        except asyncio.CancelledError:
            with suppress(Exception):
                reservations.transition(
                    invocation.invocation_id,
                    expected_revision=reservation.revision,
                    state=InvocationReservationState.INDETERMINATE,
                    result_status=ToolStatus.INDETERMINATE.value,
                    error_code="execution_cancelled_outcome_unknown",
                    reconciliation_status="required",
                )
            self._record_event(
                EventType.TOOL_OUTCOME,
                invocation,
                mode,
                status=ToolStatus.INDETERMINATE.value,
                reason_code="execution_cancelled_outcome_unknown",
            )
            raise
        except Exception:
            finalized_failure = False
            try:
                reservations.transition(
                    invocation.invocation_id,
                    expected_revision=reservation.revision,
                    state=InvocationReservationState.FAILED,
                    result_status=ToolStatus.FAILED.value,
                    error_code="tool_execution_failed",
                )
                finalized_failure = True
            except Exception:
                with suppress(Exception):
                    latest = reservations.get(invocation.invocation_id)
                    if latest is not None and latest.state == InvocationReservationState.EXECUTING:
                        reservations.transition(
                            invocation.invocation_id,
                            expected_revision=latest.revision,
                            state=InvocationReservationState.INDETERMINATE,
                            result_status=ToolStatus.INDETERMINATE.value,
                            error_code="failure_outcome_finalization_failed",
                            reconciliation_status="required",
                        )
            if not finalized_failure:
                self._record_event(
                    EventType.TOOL_OUTCOME,
                    invocation,
                    mode,
                    status=ToolStatus.INDETERMINATE.value,
                    reason_code="failure_outcome_finalization_failed",
                )
                return self._indeterminate(
                    invocation, "failure_outcome_finalization_failed", preflight.decision
                )
            failed = self._failure(invocation, "tool_execution_failed")
            self._record_event(
                EventType.TOOL_OUTCOME,
                invocation,
                mode,
                status=ToolStatus.FAILED.value,
                reason_code="tool_execution_failed",
            )
            return failed
        try:
            reservations.transition(
                invocation.invocation_id,
                expected_revision=reservation.revision,
                state={
                    ToolStatus.COMPLETED: InvocationReservationState.COMPLETED,
                    ToolStatus.CANCELLED: InvocationReservationState.CANCELLED,
                    ToolStatus.INDETERMINATE: InvocationReservationState.INDETERMINATE,
                }.get(normalized.status, InvocationReservationState.FAILED),
                result_status=normalized.status.value,
                error_code=normalized.error.error_code if normalized.error else None,
            )
        except Exception:
            with suppress(Exception):
                latest = reservations.get(invocation.invocation_id)
                if latest is not None and latest.state == InvocationReservationState.EXECUTING:
                    reservations.transition(
                        invocation.invocation_id,
                        expected_revision=latest.revision,
                        state=InvocationReservationState.INDETERMINATE,
                        result_status=ToolStatus.INDETERMINATE.value,
                        error_code="outcome_finalization_failed",
                        reconciliation_status="required",
                    )
            self._record_event(
                EventType.TOOL_OUTCOME,
                invocation,
                mode,
                status=ToolStatus.INDETERMINATE.value,
                reason_code="invocation_reservation_finalization_failed",
            )
            return self._indeterminate(invocation, "invocation_reservation_finalization_failed", preflight.decision)
        self._record_event(
            EventType.TOOL_OUTCOME,
            invocation,
            mode,
            status=normalized.status.value,
        )
        disposition = {
            ToolStatus.COMPLETED: ToolExecutionDisposition.EXECUTED,
            ToolStatus.CANCELLED: ToolExecutionDisposition.CANCELLED,
            ToolStatus.INDETERMINATE: ToolExecutionDisposition.INDETERMINATE,
        }.get(normalized.status, ToolExecutionDisposition.FAILED)
        return ToolExecutionOutcome(
            disposition=disposition,
            result=normalized,
            preflight_decision=preflight.decision,
            authorized_for_dispatch=True,
        )

    def list_invocations_for_run(self, run_id: str) -> tuple[InvocationReservation, ...]:
        """Return normalized safe lifecycle history for a Run."""
        if self._reservations is None:
            return ()
        return self._reservations.list_for_run(run_id)

    def reconcile_interrupted_invocations(self) -> tuple[InvocationReservation, ...]:
        """Finalize interrupted records without replay; safe to invoke repeatedly."""
        if self._reservations is None:
            return ()
        reconciled: list[InvocationReservation] = []
        for pending in self._reservations.list_incomplete(limit=100):
            run = self._runs.get(pending.run_id)
            run_matches = run is not None and run.execution_mode.value == pending.execution_mode
            if pending.state == InvocationReservationState.RESERVED:
                target = (
                    InvocationReservationState.CANCELLED
                    if run is not None and run.cancellation_requested
                    else InvocationReservationState.FAILED
                )
                if target == InvocationReservationState.CANCELLED:
                    error_code = "run_cancelled_before_execution"
                elif run is None:
                    error_code = "associated_run_missing_before_execution"
                elif not run_matches:
                    error_code = "associated_run_mismatch_before_execution"
                else:
                    error_code = "execution_not_started"
                result_status = (
                    ToolStatus.CANCELLED.value
                    if target == InvocationReservationState.CANCELLED
                    else ToolStatus.FAILED.value
                )
            else:
                target = InvocationReservationState.INDETERMINATE
                if run is None:
                    error_code = "associated_run_missing_outcome_unknown"
                elif not run_matches:
                    error_code = "associated_run_mismatch_outcome_unknown"
                else:
                    error_code = "interrupted_execution_outcome_unknown"
                result_status = ToolStatus.INDETERMINATE.value
            try:
                updated = self._reservations.transition(
                    pending.invocation_id,
                    expected_revision=pending.revision,
                    state=target,
                    error_code=error_code,
                    result_status=result_status,
                    reconciliation_status="reconciled",
                )
            except InvocationReservationConflict:
                continue
            reconciled.append(updated)
            self._record_reservation_outcome(updated)
        return tuple(reconciled)

    def _record_reservation_outcome(self, reservation: InvocationReservation) -> None:
        if self._run_events is None or self._runs.get(reservation.run_id) is None:
            return
        existing = self._run_events.get_events(reservation.run_id)
        if any(
            event.payload.get("invocation_id") == reservation.invocation_id
            and event.event_type == EventType.TOOL_OUTCOME
            for event in existing
        ):
            return
        try:
            self._run_events.append(
                RunEvent(
                    event_id=str(
                        uuid5(NAMESPACE_URL, f"ava:tool-outcome:{reservation.invocation_id}:{reservation.revision}")
                    ),
                    run_id=reservation.run_id,
                    event_type=EventType.TOOL_OUTCOME,
                    payload={
                        "invocation_id": reservation.invocation_id,
                        "tool_id": reservation.tool_id,
                        "tool_version": reservation.tool_version,
                        "execution_mode": reservation.execution_mode,
                        "status": reservation.result_status or reservation.state.value,
                        "reason_code": reservation.error_code or "reconciled",
                    },
                )
            )
        except Exception:
            logger.warning("Unable to persist reconciled tool outcome for run %s", reservation.run_id)

    @staticmethod
    def _normalize_executor_result(request: ToolRequest, result: ToolResult) -> ToolResult:
        if (
            not isinstance(result, ToolResult)
            or result.invocation_id != request.invocation_id
            or result.tool_id != request.tool_id
            or result.tool_version != request.tool_version
        ):
            raise ValueError("executor returned a result for a different invocation")
        return ToolResult.model_validate(result.model_dump(warnings=False))

    @classmethod
    def _denied(
        cls,
        request: ToolRequest,
        reason: str,
        preflight_decision: ToolPolicyDecisionType | None = None,
    ) -> ToolExecutionOutcome:
        result = ToolResult(
            invocation_id=request.invocation_id,
            tool_id=request.tool_id,
            tool_version=request.tool_version,
            status=ToolStatus.DENIED,
            error=ErrorResponse(
                error_code=reason,
                category=ErrorCategory.UNAVAILABLE,
                message="Tool execution was denied by AVA's current execution boundary.",
            ),
        )
        return ToolExecutionOutcome(
            disposition=ToolExecutionDisposition.DENIED,
            result=result,
            policy_reason=reason,
            preflight_decision=preflight_decision,
        )

    @staticmethod
    def _invalid_request() -> ToolExecutionOutcome:
        return ToolExecutionOutcome(
            disposition=ToolExecutionDisposition.DENIED,
            policy_reason="invalid_request",
        )

    @classmethod
    def _awaiting_approval(cls, request: ToolRequest, reason: str) -> ToolExecutionOutcome:
        return ToolExecutionOutcome(
            disposition=ToolExecutionDisposition.AWAITING_APPROVAL,
            policy_reason=reason,
            preflight_decision=ToolPolicyDecisionType.REQUIRES_APPROVAL,
        )

    @classmethod
    def _failure(cls, request: ToolRequest, reason: str) -> ToolExecutionOutcome:
        result = ToolResult(
            invocation_id=request.invocation_id,
            tool_id=request.tool_id,
            tool_version=request.tool_version,
            status=ToolStatus.FAILED,
            error=ErrorResponse(
                error_code=reason,
                category=ErrorCategory.INTERNAL,
                message="The tool executor failed.",
            ),
        )
        return ToolExecutionOutcome(
            disposition=ToolExecutionDisposition.FAILED,
            result=result,
            authorized_for_dispatch=True,
        )

    @classmethod
    def _indeterminate(
        cls,
        request: ToolRequest,
        reason: str,
        preflight_decision: ToolPolicyDecisionType,
    ) -> ToolExecutionOutcome:
        result = ToolResult(
            invocation_id=request.invocation_id,
            tool_id=request.tool_id,
            tool_version=request.tool_version,
            status=ToolStatus.INDETERMINATE,
            error=ErrorResponse(
                error_code=reason,
                category=ErrorCategory.UNAVAILABLE,
                message="The invocation outcome could not be finalized safely; it must not be retried automatically.",
            ),
        )
        return ToolExecutionOutcome(
            disposition=ToolExecutionDisposition.INDETERMINATE,
            result=result,
            policy_reason=reason,
            preflight_decision=preflight_decision,
            authorized_for_dispatch=True,
        )
