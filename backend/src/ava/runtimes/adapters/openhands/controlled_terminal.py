"""AVA-controlled OpenHands command tool backed by the sandbox runner.

This is intentionally unrelated to OpenHands' raw TerminalTool.  It accepts
structured executable/argument input and delegates all authorization and
execution to AVA-owned boundaries.
"""

import asyncio
import logging
from dataclasses import dataclass
from threading import Lock
from typing import Any, ClassVar
from uuid import uuid4

from openhands.sdk.llm import TextContent
from openhands.sdk.tool import Action, Observation, ToolAnnotations, ToolDefinition, ToolExecutor, register_tool

from ava.execution.command_policy import CommandExecutionPolicy, CommandRequest, SandboxedCommandExecutionPolicy
from ava.execution.sandbox import SandboxedCommandRequest, SandboxedCommandResult, SandboxedCommandRunnerPort
from ava.execution.tool_security import ToolRunContext
from ava.workspaces.contracts import RuntimeWorkspaceBinding

logger = logging.getLogger(__name__)

AVA_TERMINAL_TOOL_NAME = "ava_terminal"
_TERMINAL_CONTEXT_PARAM = "terminal_context_id"


@dataclass(frozen=True)
class _TerminalContext:
    workspace: RuntimeWorkspaceBinding
    policy: CommandExecutionPolicy
    runner: SandboxedCommandRunnerPort
    context: ToolRunContext | None


_contexts: dict[str, _TerminalContext] = {}
_contexts_lock = Lock()


def register_terminal_context(
    *,
    workspace: RuntimeWorkspaceBinding,
    policy: CommandExecutionPolicy,
    runner: SandboxedCommandRunnerPort,
    context: ToolRunContext | None = None,
) -> str:
    """Store runtime-only dependencies outside OpenHands-persisted tool specs."""
    context_id = str(uuid4())
    with _contexts_lock:
        _contexts[context_id] = _TerminalContext(workspace=workspace, policy=policy, runner=runner, context=context)
    return context_id


def discard_terminal_context(context_id: str) -> None:
    """Release a context after its conversation has initialized."""
    with _contexts_lock:
        _contexts.pop(context_id, None)


def _terminal_context(context_id: str) -> _TerminalContext:
    with _contexts_lock:
        context = _contexts.get(context_id)
    if context is None:
        raise ValueError("AVA terminal context is unavailable")
    return context


class AvaTerminalAction(Action):
    """Structured command input; shell syntax is never accepted."""

    executable: str
    arguments: list[str] = []
    working_directory: str | None = None


class AvaTerminalObservation(Observation):
    """Public-safe, bounded terminal result."""

    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False

    @property
    def to_llm_content(self) -> list[TextContent]:
        return [TextContent(text=self.text)]


class AvaTerminalExecutor(ToolExecutor[AvaTerminalAction, AvaTerminalObservation]):
    def __init__(
        self,
        *,
        workspace: RuntimeWorkspaceBinding,
        policy: CommandExecutionPolicy,
        runner: SandboxedCommandRunnerPort,
        context: ToolRunContext | None = None,
    ) -> None:
        self._workspace = workspace
        self._policy = policy
        self._runner = runner
        self._context = context or ToolRunContext("internal", "openhands")

    def __call__(self, action: AvaTerminalAction, conversation: Any = None) -> AvaTerminalObservation:
        del conversation
        try:
            return self._execute(action)
        except Exception:
            logger.exception("Controlled command execution failed")
            self._context.record(AVA_TERMINAL_TOOL_NAME, "command.execute", "failure", "command_execution_failed")
            return AvaTerminalObservation.from_text(text="Command execution failed", is_error=True)

    def _execute(self, action: AvaTerminalAction) -> AvaTerminalObservation:
        if self._context.revoked.is_set():
            self._context.record(AVA_TERMINAL_TOOL_NAME, "command.execute", "denied", "run_cancelled")
            return AvaTerminalObservation.from_text(text="Run cancelled", is_error=True)
        command = CommandRequest(
            executable=action.executable,
            arguments=tuple(action.arguments),
            working_directory=action.working_directory,
        )
        decision = self._policy.evaluate(workspace=self._workspace, command=command)
        if not decision.allowed:
            self._context.record(AVA_TERMINAL_TOOL_NAME, "command.execute", "denied", decision.reason_code)
            return AvaTerminalObservation.from_text(
                text="Command execution is not permitted by AVA policy.", is_error=True
            )
        if not isinstance(self._policy, SandboxedCommandExecutionPolicy):
            self._context.record(AVA_TERMINAL_TOOL_NAME, "command.execute", "denied", "tool_disabled")
            return AvaTerminalObservation.from_text(text="Command runner is unavailable.", is_error=True)
        request = self._policy.to_sandboxed_request(
            command_id=str(uuid4()), workspace=self._workspace, command=command, decision=decision
        )
        self._context.record(AVA_TERMINAL_TOOL_NAME, "command.execute", "authorized", "allowed")
        result = asyncio.run(self._run_command(request))
        reason = {"timeout": "sandbox_timeout", "cancelled": "run_cancelled"}.get(
            result.reason_code or "", result.reason_code or ("command_nonzero_exit" if result.exit_code else "allowed")
        )
        self._context.record(
            AVA_TERMINAL_TOOL_NAME,
            "command.execute",
            "failure" if result.reason_code or result.exit_code != 0 else "success",
            reason,
        )
        if result.reason_code:
            return AvaTerminalObservation.from_text(
                text="Command execution ended: " + reason, is_error=True
            ).model_copy(
                update={"exit_code": result.exit_code, "timed_out": result.timed_out, "cancelled": result.cancelled}
            )
        output = _format_result(result.stdout, result.stderr, result.output_truncated)
        is_error = result.exit_code not in (0, None) or result.timed_out or result.cancelled
        is_error = is_error or result.reason_code is not None
        return AvaTerminalObservation.from_text(text=output, is_error=is_error).model_copy(
            update={
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "cancelled": result.cancelled,
            }
        )

    async def _run_command(self, request: SandboxedCommandRequest) -> SandboxedCommandResult:
        task = asyncio.create_task(self._runner.execute(request))
        while not task.done():
            if self._context.revoked.is_set():
                await self._runner.cancel(request.command_id)
                # The runner owns process-tree cleanup on task cancellation.
                if not task.done():
                    task.cancel()
                break
            await asyncio.wait({task}, timeout=0.05)
        try:
            return await task
        except asyncio.CancelledError:
            return SandboxedCommandResult(None, "", "", cancelled=True, reason_code="cancelled")


class AvaControlledTerminalTool(ToolDefinition[AvaTerminalAction, AvaTerminalObservation]):
    """Adapter-local SDK tool that can only reach AVA's sandbox runner."""

    name: ClassVar[str] = AVA_TERMINAL_TOOL_NAME

    @classmethod
    def create(
        cls,
        conv_state: Any,
        *,
        terminal_context_id: str,
    ) -> list["AvaControlledTerminalTool"]:
        del conv_state
        context = _terminal_context(terminal_context_id)
        return [
            cls(
                action_type=AvaTerminalAction,
                observation_type=AvaTerminalObservation,
                description=(
                    "Run one allowlisted command inside the approved AVA workspace sandbox. "
                    "Set executable to the bare program name and put every flag or value in arguments "
                    "(for example, executable='ls', arguments=['-la']). Shell syntax, executable paths, "
                    "redirection, and chaining are unavailable."
                ),
                annotations=ToolAnnotations(
                    title="ava_terminal",
                    readOnlyHint=False,
                    destructiveHint=True,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=AvaTerminalExecutor(
                    workspace=context.workspace, policy=context.policy, runner=context.runner, context=context.context
                ),
            )
        ]


def _format_result(stdout: str, stderr: str, truncated: bool) -> str:
    sections = [value for value in (stdout, stderr) if value]
    output = "\n".join(sections) or "Command completed with no output."
    if truncated:
        output += "\n[Output truncated by AVA policy.]"
    return output


register_tool(AVA_TERMINAL_TOOL_NAME, AvaControlledTerminalTool)
