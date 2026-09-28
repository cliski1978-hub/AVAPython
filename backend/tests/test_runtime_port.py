"""Offline runtime contract tests; no production runtime implementation."""

import asyncio
import inspect
from typing import get_args, get_type_hints

import pytest
from test_model_provider_port import FakeModelProvider

from ava.contracts.conversations import RunContext
from ava.contracts.models import ModelMessage, ModelRequest
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo
from ava.models.bindings import ConfiguredModelBinding
from ava.models.contracts import ModelProviderPort
from ava.runtimes import AgentRuntimePort, RuntimeRunResult
from ava.workspaces.contracts import RuntimeWorkspaceBinding


class StubRuntime(AgentRuntimePort):
    """Test-only proof that the runtime chooses neither model nor provider."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, RunRequest, ModelProviderPort]] = []
        self.cancelled_ids: list[str] = []

    def get_runtime_info(self) -> RuntimeInfo:
        return RuntimeInfo(runtime_id="test-runtime")

    async def execute(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
        context: RunContext | None = None,
    ) -> RuntimeRunResult:
        del workspace, model_binding, context
        self.calls.append((run_id, request, model_provider))
        response = await model_provider.generate(
            ModelRequest(messages=[ModelMessage(role="user", content=request.prompt)])
        )
        return RuntimeRunResult(status=RunStatus.COMPLETED, content=response.content)

    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        self.cancelled_ids.append(run_id)
        return RuntimeRunResult(status=RunStatus.CANCELLED)


def test_runtime_port_is_abstract() -> None:
    assert inspect.isabstract(AgentRuntimePort)
    with pytest.raises(TypeError):
        AgentRuntimePort()  # type: ignore[abstract]


@pytest.mark.parametrize("omitted", ["get_runtime_info", "execute", "cancel_run"])
def test_each_runtime_method_is_required(omitted: str) -> None:
    methods = {
        name: getattr(StubRuntime, name)
        for name in ("get_runtime_info", "execute", "cancel_run")
        if name != omitted
    }
    incomplete = type("IncompleteRuntime", (AgentRuntimePort,), methods)
    with pytest.raises(TypeError, match=omitted):
        incomplete()


def test_runtime_interface_uses_exact_ava_types_and_execution_injection() -> None:
    expected_hints = {
        "run_id": str,
        "request": RunRequest,
        "model_provider": ModelProviderPort,
        "return": RuntimeRunResult,
    }
    hints = get_type_hints(AgentRuntimePort.execute)
    for name, expected in expected_hints.items():
        assert hints[name] == expected, name
    # An optional RuntimeWorkspaceBinding is appended after the required inputs;
    # runtimes receive only that already-approved binding and never a resolver.
    workspace_type = hints["workspace"]
    assert RuntimeWorkspaceBinding in get_args(workspace_type)
    assert type(None) in get_args(workspace_type)
    # An optional stable model binding carries identity + provider-native name.
    model_binding_type = hints["model_binding"]
    assert ConfiguredModelBinding in get_args(model_binding_type)
    assert type(None) in get_args(model_binding_type)
    assert get_type_hints(AgentRuntimePort.get_runtime_info) == {"return": RuntimeInfo}
    assert get_type_hints(AgentRuntimePort.cancel_run) == {"run_id": str, "return": RuntimeRunResult}
    assert inspect.iscoroutinefunction(AgentRuntimePort.execute)
    assert inspect.iscoroutinefunction(AgentRuntimePort.cancel_run)
    parameters = inspect.signature(AgentRuntimePort.execute).parameters
    for name in ("run_id", "request", "model_provider"):
        assert parameters[name].kind == inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default == inspect.Parameter.empty
    assert parameters["workspace"].kind == inspect.Parameter.KEYWORD_ONLY
    assert parameters["workspace"].default is None
    assert parameters["model_binding"].kind == inspect.Parameter.KEYWORD_ONLY
    assert parameters["model_binding"].default is None
    assert "__init__" not in AgentRuntimePort.__dict__


def test_same_runtime_accepts_different_provider_instances() -> None:
    async def scenario() -> None:
        runtime = StubRuntime()
        first = FakeModelProvider(model_id="first-model")
        second = FakeModelProvider(model_id="second-model")
        request = RunRequest(prompt="Hello")
        for run_id, provider in (("run-one", first), ("run-two", second)):
            result = await runtime.execute(run_id=run_id, request=request, model_provider=provider)
            assert isinstance(result, RuntimeRunResult)
            assert result.status == RunStatus.COMPLETED
            assert result.content == "reply to Hello"
            assert runtime.calls[-1] == (run_id, request, provider)
            assert runtime.calls[-1][2] is provider
        info = runtime.get_runtime_info()
        assert isinstance(info, RuntimeInfo)
        assert info.runtime_id == "test-runtime"
        assert isinstance(info.capabilities, RuntimeCapabilities)
        assert info.capabilities == RuntimeCapabilities()
        assert (await runtime.cancel_run("run-one")).status == RunStatus.CANCELLED
        assert runtime.cancelled_ids == ["run-one"]

    asyncio.run(scenario())


@pytest.mark.parametrize("status,content", [
    (RunStatus.COMPLETED, "Answer"),
    (RunStatus.FAILED, "Execution failed"),
    (RunStatus.FAILED, None),
    (RunStatus.CANCELLED, None),
])
def test_runtime_result_serializes_minimal_internal_contract(status: RunStatus, content: str | None) -> None:
    result = RuntimeRunResult(status=status, content=content)
    assert result.model_dump(mode="json") == {"status": status.value, "content": content}
    assert RuntimeRunResult.model_validate_json(result.model_dump_json()) == result
    assert set(RuntimeRunResult.model_fields) == {"status", "content"}
    assert RuntimeRunResult(status=status).content is None
