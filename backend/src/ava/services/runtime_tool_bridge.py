"""Bind runtime tool requests to AVA identity and the central execution service."""

import json
import logging
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import ValidationError

from ava.contracts.conversations import RunContext
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.events import EventType, RunEvent
from ava.contracts.json_types import JsonValue
from ava.contracts.requests import RunRequest
from ava.contracts.tools import ToolDefinition, ToolRequest, ToolResult, ToolStatus
from ava.repositories.run_event_repository import RunEventRepository
from ava.runtimes.contracts import RuntimeToolDisposition, RuntimeToolOutcome
from ava.services.tool_execution_service import ToolExecutionDisposition, ToolExecutionService
from ava.workspaces.contracts import RuntimeWorkspaceBinding

logger = logging.getLogger(__name__)


class RuntimeToolContextResolverPort(Protocol):
    """Resolve an opaque authority context from trusted Run/Workspace state."""

    def resolve(
        self,
        *,
        run_id: str,
        context: RunContext | None,
        workspace: RuntimeWorkspaceBinding | None,
    ) -> str | None: ...


def _strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


class ToolExecutionRuntimeBridge:
    """Runtime-facing adapter that delegates every valid request centrally.

    Production composition intentionally supplies no context resolver while
    AVA has no trusted authority issuer. Consequently discovery returns no
    operational schemas; unexpected calls still enter ToolExecutionService
    with an opaque unavailable context and are denied there.
    """

    def __init__(
        self,
        *,
        execution_service: ToolExecutionService,
        context_refs: RuntimeToolContextResolverPort | None = None,
        events: RunEventRepository | None = None,
    ) -> None:
        self._execution_service = execution_service
        self._context_refs = context_refs
        self._events = events

    def _context_ref(
        self,
        *,
        run_id: str,
        context: RunContext | None,
        workspace: RuntimeWorkspaceBinding | None,
    ) -> str:
        if self._context_refs is not None:
            try:
                resolved = self._context_refs.resolve(run_id=run_id, context=context, workspace=workspace)
                if isinstance(resolved, str) and resolved.strip():
                    return resolved
            except Exception:
                logger.warning("Unable to resolve tool context for run %s", run_id)
        return f"ava-unavailable-{uuid4()}"

    def discover_tools(
        self,
        *,
        run_id: str,
        request: RunRequest,
        context: RunContext | None,
        workspace: RuntimeWorkspaceBinding | None,
    ) -> list[ToolDefinition]:
        del request  # mode is obtained from the persisted Run inside the service.
        if self._context_refs is None:
            return []
        context_ref = self._context_ref(run_id=run_id, context=context, workspace=workspace)
        if context_ref.startswith("ava-unavailable-"):
            return []
        return self._execution_service.discover_tools(run_id, context_ref)

    def reject_unadvertised_tool(
        self,
        *,
        run_id: str,
        tool_id: str,
        tool_version: str,
        call_id: str,
        reason_code: str,
    ) -> RuntimeToolOutcome:
        """Record an unexpected model request without attempting dispatch."""
        invocation_id = (
            str(uuid5(NAMESPACE_URL, f"ava-runtime-tool:{run_id}:{call_id}"))
            if call_id
            else str(uuid4())
        )
        self._record(
            EventType.TOOL_REQUESTED,
            run_id=run_id,
            invocation_id=invocation_id,
            tool_id=tool_id,
            tool_version=tool_version,
            status="requested",
        )
        outcome = self._rejected(
            invocation_id=invocation_id,
            tool_id=tool_id,
            tool_version=tool_version,
            reason=reason_code,
        )
        self._record(
            EventType.TOOL_REJECTED,
            run_id=run_id,
            invocation_id=invocation_id,
            tool_id=tool_id,
            tool_version=tool_version,
            status=outcome.disposition.value,
            reason_code=reason_code,
        )
        return outcome

    def _record(
        self,
        event_type: EventType,
        *,
        run_id: str,
        invocation_id: str,
        tool_id: str,
        tool_version: str,
        status: str,
        reason_code: str | None = None,
    ) -> None:
        if self._events is None:
            return
        mode = self._execution_service.persisted_execution_mode(run_id)
        payload: dict[str, JsonValue] = {
            "invocation_id": invocation_id,
            "tool_id": tool_id,
            "tool_version": tool_version,
            "execution_mode": mode.value if mode is not None else "unavailable",
            "status": status,
        }
        if reason_code:
            payload["reason_code"] = reason_code
        try:
            self._events.append(
                RunEvent(
                    event_id=str(uuid4()),
                    run_id=run_id,
                    event_type=event_type,
                    payload=payload,
                )
            )
        except Exception:
            logger.warning("Unable to persist runtime tool event for run %s", run_id)

    @staticmethod
    def _rejected(
        *, invocation_id: str, tool_id: str, tool_version: str, reason: str
    ) -> RuntimeToolOutcome:
        try:
            result = ToolResult(
                invocation_id=invocation_id,
                tool_id=tool_id,
                tool_version=tool_version,
                status=ToolStatus.DENIED,
                error=ErrorResponse(
                    error_code=reason,
                    category=ErrorCategory.UNAVAILABLE,
                    message="AVA rejected the normalized tool request.",
                ),
            )
        except ValidationError:
            result = None
        return RuntimeToolOutcome(
            invocation_id=invocation_id,
            tool_id=tool_id,
            tool_version=tool_version,
            disposition=RuntimeToolDisposition.DENIED,
            result=result,
            reason_code=reason,
        )

    async def execute_tool(
        self,
        *,
        run_id: str,
        request: RunRequest,
        context: RunContext | None,
        workspace: RuntimeWorkspaceBinding | None,
        tool_id: str,
        tool_version: str,
        call_id: str,
        arguments_json: str,
    ) -> RuntimeToolOutcome:
        del request
        invocation_id = (
            str(uuid5(NAMESPACE_URL, f"ava-runtime-tool:{run_id}:{call_id}"))
            if call_id
            else str(uuid4())
        )
        self._record(
            EventType.TOOL_REQUESTED,
            run_id=run_id,
            invocation_id=invocation_id,
            tool_id=tool_id,
            tool_version=tool_version,
            status="requested",
        )
        try:
            arguments = json.loads(
                arguments_json,
                object_pairs_hook=_strict_object_pairs,
                parse_constant=_reject_json_constant,
            )
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be a JSON object")
            context_ref = self._context_ref(run_id=run_id, context=context, workspace=workspace)
            normalized = ToolRequest(
                invocation_id=invocation_id,
                tool_id=tool_id,
                tool_version=tool_version,
                arguments=arguments,
                execution_context_ref=context_ref,
                run_id=run_id,
            )
        except (ValueError, TypeError, ValidationError):
            outcome = self._rejected(
                invocation_id=invocation_id,
                tool_id=tool_id,
                tool_version=tool_version,
                reason="invalid_tool_request",
            )
            self._record(
                EventType.TOOL_REJECTED,
                run_id=run_id,
                invocation_id=invocation_id,
                tool_id=tool_id,
                tool_version=tool_version,
                status=outcome.disposition.value,
                reason_code=outcome.reason_code,
            )
            return outcome
        service_outcome = await self._execution_service.execute(normalized)
        disposition = {
            ToolExecutionDisposition.EXECUTED: RuntimeToolDisposition.EXECUTED,
            ToolExecutionDisposition.AWAITING_APPROVAL: RuntimeToolDisposition.AWAITING_APPROVAL,
            ToolExecutionDisposition.DENIED: RuntimeToolDisposition.DENIED,
            ToolExecutionDisposition.FAILED: RuntimeToolDisposition.FAILED,
            ToolExecutionDisposition.CANCELLED: RuntimeToolDisposition.CANCELLED,
            ToolExecutionDisposition.INDETERMINATE: RuntimeToolDisposition.INDETERMINATE,
        }[service_outcome.disposition]
        outcome = RuntimeToolOutcome(
            invocation_id=invocation_id,
            tool_id=tool_id,
            tool_version=tool_version,
            disposition=disposition,
            result=service_outcome.result,
            reason_code=service_outcome.policy_reason,
        )
        if service_outcome.authorized_for_dispatch:
            # The service owns actual start and terminal outcome events.
            pass
        elif disposition == RuntimeToolDisposition.AWAITING_APPROVAL:
            self._record(
                EventType.TOOL_OUTCOME,
                run_id=run_id,
                invocation_id=invocation_id,
                tool_id=tool_id,
                tool_version=tool_version,
                status=disposition.value,
                reason_code=outcome.reason_code,
            )
        else:
            self._record(
                EventType.TOOL_REJECTED,
                run_id=run_id,
                invocation_id=invocation_id,
                tool_id=tool_id,
                tool_version=tool_version,
                status=disposition.value,
                reason_code=outcome.reason_code,
            )
        return outcome
