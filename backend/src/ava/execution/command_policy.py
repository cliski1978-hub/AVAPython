"""Runtime-neutral AVA command-execution policy boundary.

This layer deliberately does not execute commands.  It evaluates the
workspace-owned permission and constructs safe execution inputs for a future
sandboxed command runner.  A host shell is not an acceptable runner because a
working directory alone cannot contain filesystem access.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ava.execution.sandbox import SandboxedCommandRequest
from ava.workspaces.contracts import RuntimeWorkspaceBinding

DEFAULT_COMMAND_TIMEOUT_SECONDS = 30
"""Backend-owned upper bound for a future command runner."""

MINIMAL_COMMAND_ENVIRONMENT: Mapping[str, str] = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}
"""Static environment; deliberately not inherited from the AVA process."""


@dataclass(frozen=True)
class CommandRequest:
    """Internal structured input for a prospective command runner.

    ``working_directory`` is an optional path relative to the approved root.
    No caller supplies an environment or timeout; both remain AVA-owned.
    """

    executable: str
    arguments: tuple[str, ...] = ()
    working_directory: str | None = None


@dataclass(frozen=True)
class CommandDecision:
    """Deterministic result of AVA command-policy evaluation."""

    allowed: bool
    reason_code: str
    working_directory: Path | None = None
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS
    environment: Mapping[str, str] | None = None


class CommandExecutionPolicy(Protocol):
    """Runtime-neutral port for AVA command authorization and preparation."""

    def evaluate(
        self,
        *,
        workspace: RuntimeWorkspaceBinding,
        command: CommandRequest,
    ) -> CommandDecision: ...


class SandboxedCommandExecutionPolicy:
    """Prepare a command for a future sandbox, but deny host execution today.

    The policy deliberately fails closed even for a workspace with ``shell``
    permission.  That permission is a necessary AVA grant, not proof that a
    host process can be contained.
    """

    def __init__(self, *, runner_available: bool = False) -> None:
        self._runner_available = runner_available

    @property
    def runner_available(self) -> bool:
        return self._runner_available

    def evaluate(
        self,
        *,
        workspace: RuntimeWorkspaceBinding,
        command: CommandRequest,
    ) -> CommandDecision:
        if not workspace.permissions.read:
            return CommandDecision(allowed=False, reason_code="read_permission_required")
        if not workspace.permissions.shell:
            return CommandDecision(allowed=False, reason_code="shell_permission_required")
        if workspace.local_path is None:
            return CommandDecision(allowed=False, reason_code="local_workspace_required")
        root = workspace.local_path
        try:
            root = root.resolve(strict=True)
        except OSError:
            return CommandDecision(allowed=False, reason_code="workspace_root_unavailable")
        if not root.is_dir():
            return CommandDecision(allowed=False, reason_code="workspace_root_unavailable")
        directory = self._resolve_directory(root, command.working_directory)
        if directory is None:
            return CommandDecision(allowed=False, reason_code="working_directory_outside_workspace")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", command.executable):
            return CommandDecision(allowed=False, reason_code="invalid_executable")
        return CommandDecision(
            allowed=self._runner_available,
            reason_code="allowed" if self._runner_available else "sandbox_required",
            working_directory=directory,
            environment=MINIMAL_COMMAND_ENVIRONMENT,
        )

    @staticmethod
    def to_sandboxed_request(
        *,
        command_id: str,
        workspace: RuntimeWorkspaceBinding,
        command: CommandRequest,
        decision: CommandDecision,
    ) -> SandboxedCommandRequest:
        """Translate an allowed policy decision to an internal runner request."""
        if not decision.allowed or decision.working_directory is None or decision.environment is None:
            raise ValueError("Command policy did not authorize execution")
        if workspace.local_path is None:
            raise ValueError("Command policy requires a local workspace")
        return SandboxedCommandRequest(
            command_id=command_id,
            executable=command.executable,
            arguments=command.arguments,
            workspace_root=workspace.local_path,
            working_directory=decision.working_directory,
            workspace_writable=workspace.permissions.write,
            environment=dict(decision.environment),
            timeout_seconds=decision.timeout_seconds,
            network_allowed=workspace.permissions.network,
        )

    @staticmethod
    def _resolve_directory(root: Path, requested: str | None) -> Path | None:
        if requested is None:
            return root
        relative = Path(requested)
        if relative.is_absolute():
            return None
        try:
            candidate = (root / relative).resolve(strict=True)
        except OSError:
            return None
        if not candidate.is_dir() or (candidate != root and root not in candidate.parents):
            return None
        return candidate
