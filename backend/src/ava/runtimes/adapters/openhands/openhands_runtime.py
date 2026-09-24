"""OpenHands SDK runtime adapter."""

import asyncio
import logging
from typing import Any, cast

from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo
from ava.execution.command_policy import CommandExecutionPolicy
from ava.execution.sandbox import SandboxedCommandRunnerPort
from ava.execution.tool_security import NoOpToolAuditSink, ToolAuditSink, ToolAuthorizationPolicy, ToolRunContext
from ava.models.bindings import (
    ConfiguredModelBinding,
    UnsupportedRuntimeModelBindingError,
    bind_model_provider,
)
from ava.models.contracts import ModelProviderPort
from ava.runtimes.contracts import AgentRuntimePort, RuntimeRunResult
from ava.workspaces.contracts import RuntimeWorkspaceBinding

logger = logging.getLogger(__name__)
_LOCAL_PLACEHOLDER_API_KEY = "local-ava"


def _openhands_api_key(api_key: str | None) -> str:
    """Satisfy LiteLLM's key requirement without changing AVA binding data."""
    return api_key if api_key and api_key.strip() else _LOCAL_PLACEHOLDER_API_KEY


def _workspace_path(workspace: RuntimeWorkspaceBinding | None) -> str:
    """Resolve the AVA-approved workspace path handed to the OpenHands SDK.

    An approved binding supplies its own ``local_path``; a missing binding uses
    OpenHands' isolated default. The value is never derived from prompt text,
    client input, or host environment beyond the binding itself.
    """
    if workspace is not None and workspace.local_path is not None:
        return str(workspace.local_path)
    return "workspace/project"


def _final_agent_text(conversation: Any) -> str | None:
    """Extract the last public agent message from SDK state events."""
    for event in reversed(getattr(conversation.state, "events", [])):
        if getattr(event, "source", None) != "agent":
            continue
        content = getattr(getattr(event, "llm_message", None), "content", None)
        if isinstance(content, list):
            text = "".join(str(getattr(part, "text", "")) for part in content).strip()
            if text:
                return text
    return None


def _legacy_model_binding(provider: ModelProviderPort) -> ConfiguredModelBinding:
    """Build a bootstrap binding for callers that pass no explicit identity.

    Preserves the pre-Step-38 single-model path: the provider's reported
    ``model_id`` is used as the stable identity and the provider-native name.
    """
    provider_id = provider.name()
    try:
        model_name = provider.get_model_info().model_id
    except Exception:
        model_name = provider_id
    return ConfiguredModelBinding(
        model_id=model_name, provider_id=provider_id, provider_model_name=model_name
    )


class OpenHandsRuntime(AgentRuntimePort):
    """Execute an OpenHands conversation with policy-controlled file access."""

    def __init__(
        self,
        *,
        authorization_policy: ToolAuthorizationPolicy | None = None,
        audit_sink: ToolAuditSink | None = None,
        command_policy: CommandExecutionPolicy | None = None,
        command_runner: SandboxedCommandRunnerPort | None = None,
    ) -> None:
        self._authorization_policy = authorization_policy
        self._audit_sink = audit_sink or NoOpToolAuditSink()
        self._contexts: dict[str, ToolRunContext] = {}
        self._command_policy = command_policy
        self._command_runner = command_runner

    def get_runtime_info(self) -> RuntimeInfo:
        return RuntimeInfo(
            runtime_id="openhands",
            display_name="OpenHands",
            capabilities=RuntimeCapabilities(
                tools=True,
                filesystem=True,
                shell=self._command_policy is not None and self._command_runner is not None,
                code_execution=self._command_policy is not None and self._command_runner is not None,
            ),
        )

    async def execute(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
    ) -> RuntimeRunResult:
        tools: list[Any] = []
        context = ToolRunContext(run_id, self.get_runtime_info().runtime_id, self._audit_sink)
        self._contexts[run_id] = context
        try:
            try:
                identity = model_binding or _legacy_model_binding(model_provider)
                binding = bind_model_provider(model_provider, identity)
            except UnsupportedRuntimeModelBindingError:
                return RuntimeRunResult(status=RunStatus.FAILED, content="Selected model provider cannot be bound")
            try:
                from openhands.sdk import LLM

                from ava.runtimes.adapters.openhands.conversation import ControlledAgent, ControlledConversation
                from ava.runtimes.adapters.openhands.file_policy import build_openhands_tools
            except ImportError:
                return RuntimeRunResult(status=RunStatus.FAILED, content="OpenHands runtime is unavailable")
            tools = build_openhands_tools(
                workspace, authorization_policy=self._authorization_policy,
                capabilities=self.get_runtime_info().capabilities, context=context,
                command_policy=self._command_policy, command_runner=self._command_runner,
            )
            if tools:
                try:
                    from ava.runtimes.adapters.openhands import file_tools

                    file_tools.ensure_registered()
                except ImportError:
                    return RuntimeRunResult(status=RunStatus.FAILED, content="OpenHands file tools are unavailable")
            llm = LLM(
                model=f"openai/{binding.provider_model_name}", base_url=binding.endpoint,
                api_key=_openhands_api_key(binding.api_key),
            )
            agent = ControlledAgent(llm=llm, tools=tools, include_default_tools=[])
            conversation = cast(Any, await asyncio.to_thread(
                ControlledConversation, agent=agent, workspace=_workspace_path(workspace),
                persistence_dir=None, visualizer=None,
            ))
            if context.revoked.is_set():
                return RuntimeRunResult(status=RunStatus.CANCELLED)
            await asyncio.to_thread(conversation.send_message, request.prompt)
            if context.revoked.is_set():
                return RuntimeRunResult(status=RunStatus.CANCELLED)
            await asyncio.to_thread(conversation.run)
            if context.revoked.is_set():
                return RuntimeRunResult(status=RunStatus.CANCELLED)
            content = _final_agent_text(conversation)
            if not content:
                return RuntimeRunResult(status=RunStatus.FAILED, content="OpenHands returned no final response")
            return RuntimeRunResult(status=RunStatus.COMPLETED, content=content)
        except asyncio.CancelledError:
            return RuntimeRunResult(status=RunStatus.CANCELLED)
        except Exception:
            logger.exception("OpenHands execution failed for run %s", run_id)
            return RuntimeRunResult(status=RunStatus.FAILED, content="OpenHands execution failed")
        finally:
            context.revoked.set()
            self._contexts.pop(run_id, None)
            from ava.runtimes.adapters.openhands.tool_context import discard_context

            for tool in tools:
                params = getattr(tool, "params", {})
                key = params.get("security_context_id")
                if isinstance(key, str):
                    discard_context(key)
                terminal_key = params.get("terminal_context_id")
                if isinstance(terminal_key, str):
                    from ava.runtimes.adapters.openhands.controlled_terminal import discard_terminal_context

                    discard_terminal_context(terminal_key)

    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        context = self._contexts.get(run_id)
        if context is not None:
            context.revoked.set()
        return RuntimeRunResult(status=RunStatus.CANCELLED)
