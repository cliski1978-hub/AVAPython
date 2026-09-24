"""Convert server-authorized tools into OpenHands SDK specs.

Runtime-neutral decisions belong to ToolAuthorizationPolicy. Missing policy
or capabilities fail closed. The SDK receives specs and opaque context IDs,
never the authorization policy. Model/provider metadata is not an input.
"""

from typing import Any

from ava.contracts.runtimes import RuntimeCapabilities
from ava.execution.command_policy import CommandExecutionPolicy
from ava.execution.sandbox import SandboxedCommandRunnerPort
from ava.execution.tool_security import ToolAuthorizationPolicy, ToolRunContext
from ava.workspaces.contracts import RuntimeWorkspaceBinding

FILE_EDITOR_TOOL_NAME = "file_editor"
"""Canonical OpenHands FileEditorTool name used in the agent tool list."""


def build_openhands_tools(
    workspace: RuntimeWorkspaceBinding | None,
    *,
    authorization_policy: ToolAuthorizationPolicy | None = None,
    capabilities: RuntimeCapabilities | None = None,
    context: ToolRunContext | None = None,
    command_policy: CommandExecutionPolicy | None = None,
    command_runner: SandboxedCommandRunnerPort | None = None,
) -> list[Any]:
    """Decide the exact OpenHands tool specs from an approved AVA workspace.

    Rules (task Step 33, §4/§9/§10/§11/§12):
    - no binding, or a binding without a concrete local path → ``[]`` (no tools);
    - binding present but ``read == False`` → ``[]`` (0 filesystem tools);
    - ``read == True`` and ``write == False`` → FileEditorTool in read-only mode;
    - ``read == True`` and ``write == True`` → FileEditorTool (read/write).

    The controlled AVA terminal is added only when an approved local workspace
    has shell permission and composition supplied both a policy and runner.
    It is never the raw OpenHands TerminalTool. The returned list is a plain ``openhands.sdk.Tool``
    spec list; the concrete contained implementation is registered for the
    ``file_editor`` name by the ``file_tools`` module (adapter-local).
    """
    capabilities = capabilities or RuntimeCapabilities()
    decisions = {}
    for tool_id in (FILE_EDITOR_TOOL_NAME, "ava_terminal"):
        decision = authorization_policy.evaluate(
            tool_id=tool_id, capabilities=capabilities, workspace=workspace
        ) if authorization_policy is not None else None
        allowed = decision is not None and decision.allowed
        reason = decision.reason_code if decision else "tool_disabled"
        if allowed and tool_id == "ava_terminal" and (command_policy is None or command_runner is None):
            allowed, reason = False, "tool_disabled"
        decisions[tool_id] = allowed
        if context:
            context.record(tool_id, "tool.activate", "authorized" if allowed else "denied", reason)
    if workspace is None:
        return []
    tools: list[Any] = []
    if decisions[FILE_EDITOR_TOOL_NAME]:
        tools.extend(_tool_spec(read_only=not workspace.permissions.write))
        if context:
            from ava.runtimes.adapters.openhands.tool_context import register_context

            tools[-1].params["security_context_id"] = register_context(context)
    if decisions["ava_terminal"]:
        assert command_policy is not None and command_runner is not None
        from openhands.sdk import Tool

        from ava.runtimes.adapters.openhands.controlled_terminal import (
            AVA_TERMINAL_TOOL_NAME,
            register_terminal_context,
        )

        tools.append(Tool(name=AVA_TERMINAL_TOOL_NAME, params={
            "terminal_context_id": register_terminal_context(
                workspace=workspace, policy=command_policy, runner=command_runner, context=context
            ),
        }))
    return tools


def _tool_spec(*, read_only: bool) -> list[Any]:
    """Build the single FileEditorTool spec (name + params) for the agent."""
    from openhands.sdk import Tool

    if read_only:
        return [Tool(name=FILE_EDITOR_TOOL_NAME, params={"read_only": True})]
    return [Tool(name=FILE_EDITOR_TOOL_NAME)]
