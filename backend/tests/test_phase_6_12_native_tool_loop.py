"""Native tool-loop tests use only isolated AVA contracts and a bridge fake."""

import asyncio
import json

import pytest

from ava.contracts.execution import ExecutionMode
from ava.contracts.models import ModelCapabilities, ModelResponse, ModelToolCall
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.tools import ToolDefinition, ToolExecutionCategory, ToolRisk
from ava.runtimes.adapters.native.native_runtime import NativeRuntime, NativeToolLoopLimits
from ava.runtimes.contracts import RuntimeToolDisposition, RuntimeToolOutcome


def _definition() -> ToolDefinition:
    return ToolDefinition(
        tool_id="workspace.read",
        name="Read workspace file",
        description="Read a file from the authorized workspace",
        tool_version="1",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        output_schema={"type": "object"},
        required_capabilities=("file_read",),
        risk=ToolRisk.LOW,
        execution_category=ToolExecutionCategory.DETERMINISTIC,
    )


class _Bridge:
    def __init__(self, outcomes: list[RuntimeToolOutcome] | None = None) -> None:
        self.outcomes = outcomes or []
        self.calls: list[dict[str, object]] = []
        self.rejections: list[dict[str, object]] = []

    def discover_tools(self, *, run_id, request, context, workspace):
        return [_definition()]

    async def execute_tool(
        self, *, run_id, request, context, workspace, tool_id, tool_version, call_id, arguments_json
    ):
        self.calls.append({
            "run_id": run_id, "tool_id": tool_id, "tool_version": tool_version,
            "call_id": call_id, "arguments_json": arguments_json,
        })
        return self.outcomes.pop(0)

    def reject_unadvertised_tool(self, **kwargs):
        self.rejections.append(kwargs)
        return _outcome(disposition=RuntimeToolDisposition.DENIED, reason_code=kwargs["reason_code"])


class _Provider:
    def __init__(self, responses: list[ModelResponse], *, tool_calling: bool = True) -> None:
        self.responses = responses
        self.requests = []
        self.capabilities = ModelCapabilities(chat=True, tool_calling=tool_calling)

    def get_capabilities(self):
        return self.capabilities

    async def generate(self, request, *, model_name=None):
        self.requests.append(request)
        return self.responses.pop(0)


def _outcome(*, disposition=RuntimeToolDisposition.EXECUTED, output=None, reason_code=None):
    from ava.contracts.tools import ToolResult, ToolStatus

    result = None
    if disposition == RuntimeToolDisposition.EXECUTED:
        result = ToolResult(
            invocation_id="ava-invocation-1", tool_id="workspace.read", tool_version="1",
            status=ToolStatus.COMPLETED, output=output or {"text": "hello"},
        )
    return RuntimeToolOutcome(
        invocation_id="ava-invocation-1", tool_id="workspace.read", tool_version="1",
        disposition=disposition, result=result, reason_code=reason_code,
    )


@pytest.mark.asyncio
async def test_native_runtime_translates_calls_and_returns_normalized_tool_result() -> None:
    bridge = _Bridge([_outcome()])
    provider = _Provider([
        ModelResponse(content="", model_id="m", tool_calls=[ModelToolCall(
            id="provider-call-1", name="workspace.read", arguments='{"path":"a.txt"}',
        )]),
        ModelResponse(content="Found it", model_id="m"),
    ])

    result = await NativeRuntime(tool_bridge=bridge).execute(
        run_id="run-1", request=RunRequest(prompt="read a.txt", execution_mode=ExecutionMode.AGENT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=True),
    )

    assert result.status == RunStatus.COMPLETED
    assert result.content == "Found it"
    assert len(bridge.calls) == 1
    assert bridge.calls[0]["run_id"] == "run-1"
    assert bridge.calls[0]["tool_id"] == "workspace.read"
    assert provider.requests[0].tools[0].name == "workspace.read"
    assert provider.requests[1].messages[-1].role == "tool"
    assert json.loads(provider.requests[1].messages[-1].content)["output"] == {"text": "hello"}


@pytest.mark.asyncio
async def test_native_runtime_does_not_expose_tools_to_chat_or_execute_unexpected_calls() -> None:
    bridge = _Bridge([_outcome()])
    provider = _Provider([ModelResponse(
        content="", model_id="m", tool_calls=[ModelToolCall(
            id="unexpected", name="workspace.read", arguments='{"path":"a.txt"}',
        )],
    )])

    result = await NativeRuntime(tool_bridge=bridge).execute(
        run_id="run-1", request=RunRequest(prompt="hello", execution_mode=ExecutionMode.CHAT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=True),
    )

    assert result.status == RunStatus.FAILED
    assert provider.requests[0].tools == []
    assert bridge.calls == []
    assert bridge.rejections[0]["reason_code"] == "tool_request_not_advertised"


@pytest.mark.asyncio
async def test_native_runtime_does_not_advertise_tools_to_unsupported_provider() -> None:
    bridge = _Bridge()
    provider = _Provider([ModelResponse(content="Hello", model_id="m")], tool_calling=False)
    result = await NativeRuntime(tool_bridge=bridge).execute(
        run_id="run-1", request=RunRequest(prompt="hello", execution_mode=ExecutionMode.AGENT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=True),
    )
    assert result.status == RunStatus.COMPLETED
    assert provider.requests[0].tools == []


@pytest.mark.asyncio
async def test_native_runtime_requires_selected_model_and_provider_capabilities() -> None:
    bridge = _Bridge()
    provider = _Provider([ModelResponse(content="Hello", model_id="m")])
    result = await NativeRuntime(tool_bridge=bridge).execute(
        run_id="run-1",
        request=RunRequest(prompt="hello", execution_mode=ExecutionMode.AGENT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=False),
    )
    assert result.status == RunStatus.COMPLETED
    assert provider.requests[0].tools == []


@pytest.mark.asyncio
async def test_native_runtime_terminates_on_approval_pending_without_faking_success() -> None:
    bridge = _Bridge([_outcome(disposition=RuntimeToolDisposition.AWAITING_APPROVAL, reason_code="approval_required")])
    provider = _Provider([ModelResponse(
        content="", model_id="m", tool_calls=[ModelToolCall(
            id="approval-call", name="workspace.read", arguments='{"path":"a.txt"}',
        )],
    )])
    result = await NativeRuntime(tool_bridge=bridge).execute(
        run_id="run-1", request=RunRequest(prompt="read", execution_mode=ExecutionMode.AGENT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=True),
    )
    assert result.status == RunStatus.FAILED
    assert "approval" in (result.content or "").lower()
    assert result.runtime_response is not None


@pytest.mark.asyncio
async def test_native_runtime_bounds_tool_call_iterations() -> None:
    bridge = _Bridge([_outcome()])
    call = ModelToolCall(id="c", name="workspace.read", arguments='{"path":"a.txt"}')
    provider = _Provider([
        ModelResponse(content="", model_id="m", tool_calls=[call]),
        ModelResponse(content="", model_id="m", tool_calls=[call]),
    ])
    runtime = NativeRuntime(
        tool_bridge=bridge,
        tool_loop_limits=NativeToolLoopLimits(max_tool_call_iterations=1),
    )
    result = await runtime.execute(
        run_id="run-1", request=RunRequest(prompt="read", execution_mode=ExecutionMode.AGENT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=True),
    )
    assert result.status == RunStatus.FAILED
    assert len(bridge.calls) == 1
    assert result.runtime_response == {"tool_loop_terminated": "tool_call_iteration_limit_exceeded"}


@pytest.mark.asyncio
async def test_native_runtime_bounds_total_tool_requests() -> None:
    bridge = _Bridge([_outcome()])
    calls = [
        ModelToolCall(id=f"c{i}", name="workspace.read", arguments='{"path":"a.txt"}')
        for i in range(2)
    ]
    provider = _Provider([ModelResponse(content="", model_id="m", tool_calls=calls)])
    runtime = NativeRuntime(
        tool_bridge=bridge,
        tool_loop_limits=NativeToolLoopLimits(max_tool_requests_per_run=1),
    )
    result = await runtime.execute(
        run_id="run-1", request=RunRequest(prompt="read", execution_mode=ExecutionMode.AGENT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=True),
    )
    assert result.status == RunStatus.FAILED
    assert len(bridge.calls) == 1
    assert result.runtime_response == {"tool_loop_terminated": "tool_request_limit_exceeded"}


@pytest.mark.asyncio
async def test_native_runtime_stops_after_consecutive_failures() -> None:
    bridge = _Bridge([
        _outcome(disposition=RuntimeToolDisposition.DENIED, reason_code="policy_denied"),
        _outcome(disposition=RuntimeToolDisposition.DENIED, reason_code="policy_denied"),
    ])
    provider = _Provider([
        ModelResponse(
            content="",
            model_id="m",
            tool_calls=[ModelToolCall(id=f"c{i}", name="workspace.read", arguments='{"path":"a.txt"}')],
        )
        for i in range(2)
    ])
    runtime = NativeRuntime(
        tool_bridge=bridge,
        tool_loop_limits=NativeToolLoopLimits(max_consecutive_tool_failures=2),
    )
    result = await runtime.execute(
        run_id="run-1", request=RunRequest(prompt="read", execution_mode=ExecutionMode.AGENT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=True),
    )
    assert result.status == RunStatus.FAILED
    assert result.runtime_response == {"tool_loop_terminated": "consecutive_tool_failure_limit_exceeded"}
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_native_runtime_bounds_serialized_results_and_omits_raw_output_from_diagnostics() -> None:
    bridge = _Bridge([_outcome(output={"text": "secret" * 100})])
    call = ModelToolCall(id="c", name="workspace.read", arguments='{"path":"a.txt"}')
    provider = _Provider([
        ModelResponse(content="", model_id="m", tool_calls=[call]),
        ModelResponse(content="Done", model_id="m"),
    ])
    runtime = NativeRuntime(
        tool_bridge=bridge,
        tool_loop_limits=NativeToolLoopLimits(max_serialized_tool_result_bytes=64),
    )
    result = await runtime.execute(
        run_id="run-1", request=RunRequest(prompt="read", execution_mode=ExecutionMode.AGENT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=True),
    )
    reply = json.loads(provider.requests[1].messages[-1].content)
    assert reply["reason_code"] == "tool_result_size_limit_exceeded"
    assert "secret" not in str(result.runtime_response)


@pytest.mark.asyncio
async def test_native_runtime_cancellation_stops_active_bridge_call() -> None:
    class BlockingBridge(_Bridge):
        def __init__(self) -> None:
            super().__init__([_outcome()])
            self.started = asyncio.Event()
            self.cancelled = False

        async def execute_tool(self, **kwargs):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    bridge = BlockingBridge()
    provider = _Provider([ModelResponse(
        content="", model_id="m", tool_calls=[ModelToolCall(
            id="c", name="workspace.read", arguments='{"path":"a.txt"}',
        )],
    )])
    runtime = NativeRuntime(tool_bridge=bridge)
    task = asyncio.create_task(runtime.execute(
        run_id="run-1", request=RunRequest(prompt="read", execution_mode=ExecutionMode.AGENT),
        model_provider=provider,
        model_capabilities=ModelCapabilities(chat=True, tool_calling=True),
    ))
    await asyncio.wait_for(bridge.started.wait(), 1)
    assert (await runtime.cancel_run("run-1")).status == RunStatus.CANCELLED
    assert (await asyncio.wait_for(task, 1)).status == RunStatus.CANCELLED
    assert bridge.cancelled
