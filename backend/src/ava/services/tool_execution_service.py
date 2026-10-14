"""Runtime-neutral, default-deny boundary for normalized tool invocation."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

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


class InvocationReservationState(StrEnum):
    NOT_STARTED = "not_started"
    RESERVED = "reserved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


class InvocationReservationRepository(Protocol):
    """Atomic per-invocation lifecycle guard.

    ``durable`` must be true only for a production-grade reservation adapter.
    An in-memory lock/status cannot claim exactly-once side effects.
    """

    durable: bool

    def reserve(self, invocation_id: str, binding: ToolOperationBinding) -> bool:
        """Atomically move NOT_STARTED to RESERVED; false means already claimed."""
        ...

    def transition(self, invocation_id: str, state: InvocationReservationState) -> None:
        """Record the current dispatch lifecycle state."""
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
                or (
                    authority.narrowing_tool_ids is not None
                    and definition.tool_id not in authority.narrowing_tool_ids
                )
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
            or authority.context.context_id != invocation.execution_context_ref
            or authority.context.workspace_id is None
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
        if (
            current.decision != preflight.decision
            or current.operation_binding != preflight.operation_binding
            or current_authority != authority
            or current_authority is None
            or current_authority.revoked
        ):
            return self._denied(invocation, "execution_context_changed", preflight.decision)
        current_run = self._runs.get(run_id)
        if (
            current_run is None
            or current_run.status.is_terminal
            or current_run.cancellation_requested
            or current_run.execution_mode != mode
        ):
            return self._denied(invocation, "run_execution_context_changed", preflight.decision)

        executor = self._executors.get(invocation.tool_id)
        if executor is None:
            return self._denied(invocation, "executor_unavailable", preflight.decision)
        reservations = self._reservations
        if reservations is None or not reservations.durable:
            return self._denied(invocation, "durable_invocation_reservation_unavailable", preflight.decision)
        binding = preflight.operation_binding
        try:
            reserved = reservations.reserve(invocation.invocation_id, binding)
        except Exception:
            return self._denied(invocation, "invocation_reservation_unavailable", preflight.decision)
        if not reserved:
            return self._denied(invocation, "duplicate_invocation", preflight.decision)
        try:
            reservations.transition(invocation.invocation_id, InvocationReservationState.EXECUTING)
        except Exception:
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
            self._record_event(
                EventType.TOOL_STARTED, invocation, mode, status=ToolStatus.STARTED.value
            )
            result = await executor.execute(authorized)
            normalized = self._normalize_executor_result(invocation, result)
        except asyncio.CancelledError:
            with suppress(Exception):
                reservations.transition(invocation.invocation_id, InvocationReservationState.CANCELLED)
            self._record_event(
                EventType.TOOL_OUTCOME, invocation, mode, status=ToolStatus.CANCELLED.value
            )
            raise
        except Exception:
            with suppress(Exception):
                reservations.transition(invocation.invocation_id, InvocationReservationState.FAILED)
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
                InvocationReservationState.COMPLETED
                if normalized.status == ToolStatus.COMPLETED
                else InvocationReservationState.FAILED,
            )
        except Exception:
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
        disposition = (
            ToolExecutionDisposition.EXECUTED
            if normalized.status == ToolStatus.COMPLETED
            else ToolExecutionDisposition.FAILED
        )
        return ToolExecutionOutcome(
            disposition=disposition,
            result=normalized,
            preflight_decision=preflight.decision,
            authorized_for_dispatch=True,
        )

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
            disposition=ToolExecutionDisposition.FAILED,
            result=result,
            policy_reason=reason,
            preflight_decision=preflight_decision,
            authorized_for_dispatch=True,
        )
