"""Live, opt-in qualification harness for OpenHands native tool calls.

The SDK emits ``ActionEvent`` only after an LLM response contains a structured
``MessageToolCall``. Plain assistant text never enters that path, so it cannot
reach a tool executor.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from ava.contracts.runtimes import RuntimeCapabilities
from ava.execution.command_policy import SandboxedCommandExecutionPolicy
from ava.execution.sandbox import (
    SandboxedCommandRequest,
    SandboxedCommandResult,
    SandboxedCommandRunnerPort,
)
from ava.execution.tool_security import ToolAuthorizationPolicy
from ava.runtimes.adapters.openhands.controlled_terminal import (
    AVA_TERMINAL_TOOL_NAME,
    discard_terminal_context,
)
from ava.runtimes.adapters.openhands.conversation import ControlledAgent, ControlledConversation
from ava.runtimes.adapters.openhands.file_policy import build_openhands_tools
from ava.runtimes.adapters.openhands.openhands_runtime import _final_agent_text
from ava.runtimes.qualification import ToolCallQualificationTrial
from ava.workspaces.contracts import RuntimeWorkspaceBinding

QUALIFICATION_PROMPT = (
    "Use the ava_terminal tool exactly once to run the executable `pwd`. "
    "Do not answer from memory. After the tool returns, report the working directory."
)


@dataclass(frozen=True)
class OpenHandsWorkflowTrace:
    """Public-safe observations from one live agent workflow."""

    tool_names: tuple[str, ...]
    terminal_arguments: tuple[str, ...]
    terminal_failures: int
    sandbox_requests: int
    final_response: str | None
    event_trace: tuple[tuple[str, str | None, int], ...] = ()
    cancelled: bool = False
    run_completed: bool = False
    stall_reason: str | None = None


@dataclass
class RecordingSandboxRunner(SandboxedCommandRunnerPort):
    """Port decorator that proves a qualification trial reached the sandbox."""

    delegate: SandboxedCommandRunnerPort
    requests: list[SandboxedCommandRequest] = field(default_factory=list)

    async def execute(self, request: SandboxedCommandRequest) -> SandboxedCommandResult:
        self.requests.append(request)
        return await self.delegate.execute(request)

    async def cancel(self, command_id: str) -> None:
        await self.delegate.cancel(command_id)


async def run_native_tool_call_trial(
    *,
    model_id: str,
    endpoint: str,
    workspace: RuntimeWorkspaceBinding,
    runner: SandboxedCommandRunnerPort,
    context_window: int = 8192,
    prompt: str = QUALIFICATION_PROMPT,
) -> ToolCallQualificationTrial:
    """Run one real SDK trial and derive evidence from its event stream."""
    from openhands.sdk import LLM

    from ava.runtimes.adapters.openhands import file_tools

    recorder = RecordingSandboxRunner(delegate=runner)
    file_tools.ensure_registered()
    tools = build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=workspace,
        command_policy=SandboxedCommandExecutionPolicy(runner_available=True),
        command_runner=recorder,
    )
    try:
        agent = ControlledAgent(
            llm=LLM(
                model=f"openai/{model_id}",
                base_url=endpoint,
                api_key="local-ava",
                temperature=0,
                # Ollama accepts generic generation options through its
                # OpenAI-compatible extra body; this is not model-specific.
                litellm_extra_body={"options": {"num_ctx": context_window}},
            ),
            tools=tools,
            include_default_tools=[],
        )
        conversation_factory: Any = ControlledConversation
        conversation = await asyncio.to_thread(
            conversation_factory,
            agent=agent,
            workspace=str(workspace.local_path),
            persistence_dir=None,
            visualizer=None,
        )
        await asyncio.to_thread(conversation.send_message, prompt)
        await asyncio.to_thread(conversation.run)
        events = list(conversation.state.events)
        actions = [event for event in events if event.__class__.__name__ == "ActionEvent"]
        terminal_actions = [event for event in actions if getattr(event, "tool_name", None) == AVA_TERMINAL_TOOL_NAME]
        observations = [
            event
            for event in events
            if event.__class__.__name__ == "ObservationEvent"
            and getattr(event, "tool_name", None) == AVA_TERMINAL_TOOL_NAME
        ]
        assistant_text = _final_agent_text(conversation)
        malformed = any(getattr(event, "action", None) is None for event in terminal_actions)
        return ToolCallQualificationTrial(
            native_tool_name=(getattr(terminal_actions[0], "tool_name", None) if terminal_actions else None),
            native_tool_call_observed=bool(terminal_actions),
            malformed_tool_arguments=malformed,
            tool_executed=bool(observations),
            sandbox_receipt_observed=bool(recorder.requests),
            tool_result_observed=bool(observations),
            final_response_observed=bool(assistant_text) and bool(observations),
            assistant_text=assistant_text,
        )
    except Exception:
        return ToolCallQualificationTrial(runtime_failed=True)
    finally:
        for tool in tools:
            context_id = getattr(tool, "params", {}).get("terminal_context_id")
            if isinstance(context_id, str):
                discard_terminal_context(context_id)


async def run_openhands_workflow(
    *,
    model_id: str,
    endpoint: str,
    workspace: RuntimeWorkspaceBinding,
    runner: SandboxedCommandRunnerPort,
    prompt: str,
    context_window: int = 8192,
    temperature: float = 0,
    timeout_seconds: float = 90,
    max_iterations: int = 12,
) -> OpenHandsWorkflowTrace:
    """Run a live workflow and collect SDK event facts without prose parsing."""
    from openhands.sdk import LLM

    from ava.runtimes.adapters.openhands import file_tools

    recorder = RecordingSandboxRunner(delegate=runner)
    file_tools.ensure_registered()
    tools = build_openhands_tools(
        authorization_policy=ToolAuthorizationPolicy(),
        capabilities=RuntimeCapabilities(tools=True, filesystem=True, shell=True),
        workspace=workspace,
        command_policy=SandboxedCommandExecutionPolicy(runner_available=True),
        command_runner=recorder,
    )
    started = time.monotonic()
    observed: list[tuple[str, str | None, int]] = []

    def capture(event: Any) -> None:
        tool_name = getattr(event, "tool_name", None)
        observed.append(
            (
                event.__class__.__name__,
                str(tool_name) if tool_name else None,
                int((time.monotonic() - started) * 1000),
            )
        )

    cancelled = False
    try:
        agent = ControlledAgent(
            llm=LLM(
                model=f"openai/{model_id}",
                base_url=endpoint,
                api_key="local-ava",
                temperature=temperature,
                litellm_extra_body={"options": {"num_ctx": context_window}},
            ),
            tools=tools,
            include_default_tools=[],
        )
        conversation_factory: Any = ControlledConversation
        conversation = await asyncio.to_thread(
            conversation_factory,
            agent=agent,
            workspace=str(workspace.local_path),
            persistence_dir=None,
            visualizer=None,
            callbacks=[capture],
            max_iteration_per_run=max_iterations,
        )
        await asyncio.to_thread(conversation.send_message, prompt)
        try:
            await asyncio.wait_for(asyncio.to_thread(conversation.run), timeout=timeout_seconds)
        except TimeoutError:
            cancelled = True
            await asyncio.to_thread(conversation.interrupt)
        events = list(conversation.state.events)
        actions = [event for event in events if event.__class__.__name__ == "ActionEvent"]
        terminal_actions = [event for event in actions if getattr(event, "tool_name", None) == AVA_TERMINAL_TOOL_NAME]
        observations = [
            event
            for event in events
            if event.__class__.__name__ == "ObservationEvent"
            and getattr(event, "tool_name", None) == AVA_TERMINAL_TOOL_NAME
        ]
        tool_names = tuple(str(getattr(event, "tool_name", "")) for event in actions)
        final_response = _final_agent_text(conversation)
        from ava.runtimes.qualification import classify_workflow_stall

        return OpenHandsWorkflowTrace(
            tool_names=tool_names,
            terminal_arguments=tuple(
                str(getattr(getattr(event, "tool_call", None), "arguments", "")) for event in terminal_actions
            ),
            terminal_failures=sum(
                bool(getattr(getattr(event, "observation", None), "is_error", False)) for event in observations
            ),
            sandbox_requests=len(recorder.requests),
            final_response=final_response,
            event_trace=tuple(observed),
            cancelled=cancelled,
            # A returned SDK loop is not a completed agent workflow unless it
            # produced the required final answer; iteration exhaustion is a
            # bounded stall, not a successful completion.
            run_completed=not cancelled and bool(final_response),
            stall_reason=classify_workflow_stall(
                tool_calls=len(actions),
                file_editor_calls=tool_names.count("file_editor"),
                terminal_calls=tool_names.count(AVA_TERMINAL_TOOL_NAME),
                final_response_emitted=bool(final_response),
                cancelled=cancelled,
            ),
        )
    finally:
        for tool in tools:
            context_id = getattr(tool, "params", {}).get("terminal_context_id")
            if isinstance(context_id, str):
                discard_terminal_context(context_id)
