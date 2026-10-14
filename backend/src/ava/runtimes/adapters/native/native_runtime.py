"""Native runtime with provider-neutral, centrally mediated tool calls."""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from ava.contracts.conversations import RunContext, execution_context_messages
from ava.contracts.json_types import JsonValue
from ava.contracts.models import ModelCapabilities, ModelMessage, ModelRequest, ModelResponse, ModelToolDefinition
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo
from ava.contracts.tools import ToolDefinition
from ava.models.bindings import ConfiguredModelBinding
from ava.models.contracts import ModelProviderPort
from ava.models.errors import ModelProviderError
from ava.runtimes.contracts import (
    AgentRuntimePort,
    RuntimeRunResult,
    RuntimeToolBridgePort,
    RuntimeToolDisposition,
    RuntimeToolOutcome,
)
from ava.workspaces.contracts import RuntimeWorkspaceBinding

logger = logging.getLogger(__name__)
_FAILURE_CONTENT = "Model provider request failed"
_TOOL_FAILURE_CONTENT = "AVA could not complete the requested tool operation"
_APPROVAL_CONTENT = "The requested tool operation requires human approval"


@dataclass(frozen=True)
class NativeToolLoopLimits:
    """Server-owned bounds for one native runtime tool loop."""

    max_tool_requests_per_run: int = 12
    max_consecutive_tool_failures: int = 3
    max_tool_call_iterations: int = 6
    max_serialized_tool_result_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if min(
            self.max_tool_requests_per_run,
            self.max_consecutive_tool_failures,
            self.max_tool_call_iterations,
            self.max_serialized_tool_result_bytes,
        ) < 1:
            raise ValueError("native tool-loop limits must be positive")


def _model_messages(context: RunContext | None, prompt: str) -> list[ModelMessage]:
    """Translate the AVA-constructed context into provider message shape."""
    return [
        ModelMessage(role=message.role.value, content=message.content)
        for message in execution_context_messages(context, prompt)
    ]


def _tool_schema(definition: ToolDefinition) -> ModelToolDefinition:
    """Translate a validated AVA definition into the provider-neutral schema."""
    return ModelToolDefinition(
        name=definition.tool_id,
        description=definition.description,
        parameters=definition.input_schema,
    )


def _tool_reply(outcome: RuntimeToolOutcome) -> dict[str, object]:
    """Build a bounded-safe normalized reply without runtime/provider data."""
    body: dict[str, object] = {
        "invocation_id": outcome.invocation_id,
        "tool_id": outcome.tool_id,
        "tool_version": outcome.tool_version,
        "disposition": outcome.disposition.value,
    }
    if outcome.reason_code:
        body["reason_code"] = outcome.reason_code
    if outcome.result is not None:
        body["status"] = outcome.result.status.value
        if outcome.result.output is not None:
            body["output"] = outcome.result.output
        if outcome.result.error is not None:
            body["error"] = {
                "error_code": outcome.result.error.error_code,
                "category": outcome.result.error.category.value,
                "message": outcome.result.error.message,
            }
    return body


class NativeRuntime(AgentRuntimePort):
    """Execute with any supplied model provider through AVA-owned contracts."""

    def __init__(
        self,
        *,
        tool_bridge: RuntimeToolBridgePort | None = None,
        tool_loop_limits: NativeToolLoopLimits | None = None,
    ) -> None:
        self._tool_bridge = tool_bridge
        self._tool_loop_limits = tool_loop_limits or NativeToolLoopLimits()
        self._run_tasks: dict[str, asyncio.Task[RuntimeRunResult]] = {}
        self._final_status: dict[str, RunStatus] = {}

    def get_runtime_info(self) -> RuntimeInfo:
        return RuntimeInfo(
            runtime_id="native",
            display_name="AVA Native Runtime",
            capabilities=RuntimeCapabilities(tools=self._tool_bridge is not None),
        )

    async def execute(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
        model_capabilities: ModelCapabilities | None = None,
        context: RunContext | None = None,
    ) -> RuntimeRunResult:
        if run_id in self._run_tasks:
            return RuntimeRunResult(status=RunStatus.FAILED, content="Run is already active")
        self._final_status.pop(run_id, None)
        model_name = (
            model_binding.provider_model_name
            if model_binding is not None and model_binding.provider_model_name.strip()
            else None
        )
        model_tool_calling = model_capabilities is not None and model_capabilities.tool_calling

        async def run() -> RuntimeRunResult:
            return await self._run_loop(
                run_id=run_id,
                request=request,
                model_provider=model_provider,
                model_name=model_name,
                model_tool_calling=model_tool_calling,
                workspace=workspace,
                context=context,
            )

        task = asyncio.create_task(run())
        self._run_tasks[run_id] = task
        try:
            result = await task
        except asyncio.CancelledError:
            result = RuntimeRunResult(status=RunStatus.CANCELLED)
        except ModelProviderError as exc:
            logger.warning("Model provider failure for run %s: %s", run_id, exc)
            result = RuntimeRunResult(
                status=RunStatus.FAILED,
                content=_FAILURE_CONTENT,
                failure_code=exc.safe_code,
            )
        except Exception:
            logger.exception("Unexpected model provider failure for run %s", run_id)
            result = RuntimeRunResult(status=RunStatus.FAILED, content=_FAILURE_CONTENT)
        finally:
            self._run_tasks.pop(run_id, None)
        if self._final_status.get(run_id) == RunStatus.CANCELLED:
            result = RuntimeRunResult(status=RunStatus.CANCELLED)
        self._final_status[run_id] = result.status
        return result

    async def _run_loop(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        model_name: str | None,
        model_tool_calling: bool,
        workspace: RuntimeWorkspaceBinding | None,
        context: RunContext | None,
        on_content: Callable[[str], None] | None = None,
    ) -> RuntimeRunResult:
        provider_capabilities = model_provider.get_capabilities()
        definitions: list[ToolDefinition] = []
        if (
            self._tool_bridge is not None
            and provider_capabilities.tool_calling
            and model_tool_calling
            and request.execution_mode.value != "chat"
        ):
            definitions = self._tool_bridge.discover_tools(
                run_id=run_id, request=request, context=context, workspace=workspace
            )
        schemas = [_tool_schema(definition) for definition in definitions]
        by_name = {definition.tool_id: definition for definition in definitions}
        messages = _model_messages(context, request.prompt)
        tool_request_count = 0
        iteration_count = 0
        consecutive_failures = 0
        called_tool_ids: list[str] = []
        model_requests: list[ModelRequest] = []
        response: ModelResponse | None = None

        while True:
            model_request = ModelRequest(messages=messages, tools=schemas if definitions else [])
            model_requests.append(model_request)
            response = await model_provider.generate(model_request, model_name=model_name)
            if not response.tool_calls:
                if on_content is not None and response.content:
                    on_content(response.content)
                if tool_request_count:
                    runtime_request: dict[str, JsonValue] = {
                        "model_name": model_name,
                        "tool_request_count": tool_request_count,
                        "tool_ids": cast(JsonValue, sorted(set(called_tool_ids))),
                    }
                    runtime_response: JsonValue = {
                        "content": response.content,
                        "tool_request_count": tool_request_count,
                    }
                else:
                    runtime_request = {
                        "model_request": cast(JsonValue, model_request.model_dump(mode="json")),
                        "model_name": model_name,
                    }
                    runtime_response = cast(JsonValue, response.model_dump(mode="json"))
                return RuntimeRunResult(
                    status=RunStatus.COMPLETED,
                    content=response.content,
                    runtime_request=runtime_request,
                    runtime_response=runtime_response,
                )
            if self._tool_bridge is None or not schemas:
                if self._tool_bridge is not None:
                    for call in response.tool_calls[: self._tool_loop_limits.max_tool_requests_per_run]:
                        self._tool_bridge.reject_unadvertised_tool(
                            run_id=run_id,
                            tool_id=call.name,
                            tool_version="unknown",
                            call_id=call.id,
                            reason_code="tool_request_not_advertised",
                        )
                return RuntimeRunResult(
                    status=RunStatus.FAILED,
                    content="The selected model returned an unavailable tool request",
                    runtime_request={"model_name": model_name, "tool_request_count": tool_request_count},
                    runtime_response={"tool_calls_rejected": len(response.tool_calls)},
                )
            iteration_count += 1
            if iteration_count > self._tool_loop_limits.max_tool_call_iterations:
                return self._tool_loop_failure(
                    "tool_call_iteration_limit_exceeded", tool_request_count, called_tool_ids
                )
            messages.append(
                ModelMessage(role="assistant", content=response.content, tool_calls=response.tool_calls)
            )
            for call in response.tool_calls:
                if tool_request_count >= self._tool_loop_limits.max_tool_requests_per_run:
                    return self._tool_loop_failure("tool_request_limit_exceeded", tool_request_count, called_tool_ids)
                tool_request_count += 1
                called_tool_ids.append(call.name)
                definition = by_name.get(call.name)
                outcome = await self._tool_bridge.execute_tool(
                    run_id=run_id,
                    request=request,
                    context=context,
                    workspace=workspace,
                    tool_id=call.name,
                    tool_version=definition.tool_version if definition is not None else "unknown",
                    call_id=call.id,
                    arguments_json=call.arguments,
                )
                if outcome.disposition == RuntimeToolDisposition.CANCELLED:
                    return RuntimeRunResult(status=RunStatus.CANCELLED)
                if outcome.disposition == RuntimeToolDisposition.AWAITING_APPROVAL:
                    return RuntimeRunResult(
                        status=RunStatus.FAILED,
                        content=_APPROVAL_CONTENT,
                        runtime_request={
                            "model_name": model_name,
                            "tool_request_count": tool_request_count,
                            "tool_ids": cast(JsonValue, sorted(set(called_tool_ids))),
                        },
                        runtime_response={"approval_required": True, "reason_code": outcome.reason_code},
                    )
                if outcome.disposition != RuntimeToolDisposition.EXECUTED or outcome.result is None:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                body = _tool_reply(outcome)
                serialized = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
                if len(serialized.encode("utf-8")) > self._tool_loop_limits.max_serialized_tool_result_bytes:
                    consecutive_failures += 1
                    serialized = json.dumps({
                        "invocation_id": outcome.invocation_id,
                        "tool_id": outcome.tool_id,
                        "disposition": "failed",
                        "reason_code": "tool_result_size_limit_exceeded",
                    }, separators=(",", ":"))
                messages.append(
                    ModelMessage(role="tool", name=call.name, tool_call_id=call.id, content=serialized)
                )
                if consecutive_failures >= self._tool_loop_limits.max_consecutive_tool_failures:
                    return self._tool_loop_failure(
                        "consecutive_tool_failure_limit_exceeded", tool_request_count, called_tool_ids
                    )

    @staticmethod
    def _tool_loop_failure(reason: str, request_count: int, tool_ids: list[str]) -> RuntimeRunResult:
        return RuntimeRunResult(
            status=RunStatus.FAILED,
            content=_TOOL_FAILURE_CONTENT,
            runtime_request={
                "tool_request_count": request_count,
                "tool_ids": cast(JsonValue, sorted(set(tool_ids))),
            },
            runtime_response={"tool_loop_terminated": reason},
        )

    async def execute_streaming(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        on_content: Callable[[str], None],
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
        model_capabilities: ModelCapabilities | None = None,
        context: RunContext | None = None,
    ) -> RuntimeRunResult:
        """Stream ordinary text; structured tool calls use bounded generation."""
        if (
            model_provider.get_capabilities().tool_calling
            and model_capabilities is not None
            and model_capabilities.tool_calling
            and self._tool_bridge is not None
            and request.execution_mode.value != "chat"
        ):
            result = await self.execute(
                run_id=run_id, request=request, model_provider=model_provider,
                workspace=workspace, model_binding=model_binding,
                model_capabilities=model_capabilities, context=context,
            )
            if result.status == RunStatus.COMPLETED and result.content:
                on_content(result.content)
            return result
        if not model_provider.get_capabilities().streaming:
            result = await self.execute(
                run_id=run_id, request=request, model_provider=model_provider,
                workspace=workspace, model_binding=model_binding,
                model_capabilities=model_capabilities, context=context,
            )
            if result.status == RunStatus.COMPLETED and result.content:
                on_content(result.content)
            return result
        if run_id in self._run_tasks:
            return RuntimeRunResult(status=RunStatus.FAILED, content="Run is already active")
        self._final_status.pop(run_id, None)
        model_name = (
            model_binding.provider_model_name
            if model_binding is not None and model_binding.provider_model_name.strip()
            else None
        )
        model_request = ModelRequest(messages=_model_messages(context, request.prompt))

        async def consume() -> RuntimeRunResult:
            snapshot = ""
            async for delta in model_provider.stream(model_request, model_name=model_name):
                snapshot += delta
                on_content(snapshot)
            return RuntimeRunResult(
                status=RunStatus.COMPLETED,
                content=snapshot,
                runtime_request={"model_request": model_request.model_dump(mode="json"), "model_name": model_name},
                runtime_response={"content": snapshot, "model_id": model_name or ""},
            )

        task = asyncio.create_task(consume())
        self._run_tasks[run_id] = task
        try:
            result = await task
        except asyncio.CancelledError:
            result = RuntimeRunResult(status=RunStatus.CANCELLED)
        except ModelProviderError as exc:
            logger.warning("Model provider streaming failure for run %s: %s", run_id, exc)
            result = RuntimeRunResult(status=RunStatus.FAILED, content=_FAILURE_CONTENT, failure_code=exc.safe_code)
        except Exception:
            logger.exception("Unexpected native streaming failure for run %s", run_id)
            result = RuntimeRunResult(status=RunStatus.FAILED, content=_FAILURE_CONTENT)
        finally:
            self._run_tasks.pop(run_id, None)
        if self._final_status.get(run_id) == RunStatus.CANCELLED:
            result = RuntimeRunResult(status=RunStatus.CANCELLED)
        self._final_status[run_id] = result.status
        return result

    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        """Cancel the full generation-and-tool loop, idempotently."""
        task = self._run_tasks.get(run_id)
        if task is not None:
            if self._final_status.get(run_id) != RunStatus.CANCELLED:
                self._final_status[run_id] = RunStatus.CANCELLED
                task.cancel()
            return RuntimeRunResult(status=RunStatus.CANCELLED)
        return RuntimeRunResult(status=self._final_status.get(run_id, RunStatus.RUNNING))
