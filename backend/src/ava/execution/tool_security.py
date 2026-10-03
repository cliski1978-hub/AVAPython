"""Server-owned tool activation and metadata-only internal security audit.

Capabilities describe implementations; they never grant run permissions.
Neither model identity nor provider/profile selection is a policy input.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event, Lock
from typing import Literal, Protocol

from ava.contracts.runtimes import RuntimeCapabilities
from ava.workspaces.contracts import RuntimeWorkspaceBinding

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolAuthorizationDecision:
    allowed: bool
    reason_code: str


class ToolAuthorizationPolicy:
    """Pure activation policy. Operation checks remain mandatory."""

    def evaluate(
        self,
        *,
        tool_id: str,
        capabilities: RuntimeCapabilities,
        workspace: RuntimeWorkspaceBinding | None,
    ) -> ToolAuthorizationDecision:
        reason = "allowed"
        if tool_id not in {"file_editor", "ava_terminal"}:
            reason = "tool_not_approved"
        elif not capabilities.tools or not (
            capabilities.filesystem if tool_id == "file_editor" else capabilities.shell
        ):
            reason = "runtime_capability_missing"
        elif workspace is None or workspace.local_path is None:
            reason = "workspace_required"
        elif not workspace.permissions.read:
            reason = "workspace_read_denied"
        elif tool_id == "ava_terminal" and not workspace.permissions.shell:
            reason = "workspace_shell_denied"
        elif tool_id == "ava_terminal" and workspace.permissions.network:
            reason = "network_policy_unsupported"
        return ToolAuthorizationDecision(reason == "allowed", reason)


@dataclass(frozen=True)
class ToolAuditEvent:
    run_id: str
    runtime_id: str
    tool_id: str
    action: str
    outcome: Literal["authorized", "denied", "success", "failure"]
    reason_code: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class ToolAuditSink(Protocol):
    def record(self, event: ToolAuditEvent) -> None: ...


class NoOpToolAuditSink:
    def record(self, event: ToolAuditEvent) -> None:
        pass


class InMemoryToolAuditSink:
    """Thread-safe collector for tests/internal consumers; never public run events."""

    def __init__(self) -> None:
        self._events: list[ToolAuditEvent] = []
        self._lock = Lock()

    def record(self, event: ToolAuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[ToolAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)


@dataclass(frozen=True)
class ToolRunContext:
    run_id: str
    runtime_id: str
    sink: ToolAuditSink = field(default_factory=NoOpToolAuditSink)
    revoked: Event = field(default_factory=Event)

    def record(
        self,
        tool_id: str,
        action: str,
        outcome: Literal["authorized", "denied", "success", "failure"],
        reason: str,
    ) -> None:
        try:
            self.sink.record(ToolAuditEvent(self.run_id, self.runtime_id, tool_id, action, outcome, reason))
        except Exception:
            # Audit transport is best effort; policy and operation outcomes do
            # not change. Log a diagnostic without event payload/exception text.
            logger.error("Security audit sink failed", exc_info=False)
