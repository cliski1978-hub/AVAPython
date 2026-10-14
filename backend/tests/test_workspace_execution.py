"""Step 32 — workspace resolution wired into the agent execution path.

Proves that an opaque ``RunRequest.workspace_id`` is resolved by the
``WorkspaceResolver`` inside the ``NativeAgentAdapter`` into an approved
``RuntimeWorkspaceBinding`` that reaches the selected ``AgentRuntimePort`` as
``workspace``. No workspace results in ``workspace=None``; an unknown (or
path-like, unregistered) id fails cleanly without executing a runtime or
falling back to any filesystem location.
"""

import asyncio
import sys
import types
from pathlib import Path

import pytest

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.contracts.conversations import RunContext
from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelProviderHealth,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo
from ava.models.bindings import ConfiguredModelBinding, RuntimeModelBinding
from ava.models.contracts import ModelProviderPort
from ava.models.errors import ModelProviderError
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.adapters.openhands.openhands_runtime import OpenHandsRuntime, _workspace_path
from ava.runtimes.contracts import AgentRuntimePort, RuntimeRunResult
from ava.workspaces import (
    ResolvedWorkspace,
    RuntimeWorkspaceBinding,
    UnknownWorkspaceError,
    WorkspaceInfo,
    WorkspaceKind,
    WorkspacePermissions,
    WorkspaceRegistry,
    WorkspaceResolver,
    bind_workspace,
)


class EchoProvider(ModelProviderPort):
    """Port-valid provider for offline execution tests."""

    __test__ = False

    def name(self) -> str:
        return "test"

    async def health(self) -> ModelProviderHealth:
        return ModelProviderHealth(status="healthy", available=True)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id="test-model",
            provider_name="test",
            display_name="Test",
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        del model_name
        return ModelResponse(content=f"reply to {request.messages[0].content}", model_id="test-model")


class RecordingRuntime(AgentRuntimePort):
    """Records the workspace binding each execution receives."""

    def __init__(self, status: RunStatus = RunStatus.COMPLETED, content: str = "ok") -> None:
        self.received: list[RuntimeWorkspaceBinding | None] = []
        self.calls = 0
        self._status = status
        self._content = content

    def get_runtime_info(self) -> RuntimeInfo:
        return RuntimeInfo(runtime_id="recording", display_name="Recording", capabilities=RuntimeCapabilities())

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
        del model_provider, model_binding, model_capabilities, context
        self.calls += 1
        self.received.append(workspace)
        return RuntimeRunResult(status=self._status, content=self._content)

    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        return RuntimeRunResult(status=RunStatus.CANCELLED)


def _registry_with(*workspaces: ResolvedWorkspace) -> WorkspaceRegistry:
    registry = WorkspaceRegistry()
    for workspace in workspaces:
        registry.register(workspace)
    return registry


def _local_workspace(
    workspace_id: str,
    *,
    read: bool = False,
    write: bool = False,
    shell: bool = False,
    network: bool = False,
) -> ResolvedWorkspace:
    return ResolvedWorkspace(
        info=WorkspaceInfo(workspace_id=workspace_id, display_name=workspace_id, kind=WorkspaceKind.LOCAL),
        root_path=Path(f"/srv/ava/workspaces/{workspace_id}"),
        permissions=WorkspacePermissions(read=read, write=write, shell=shell, network=network),
    )


# ============================================================
# BEGIN: Binding Conversion
# ============================================================


def test_bind_workspace_converts_resolved_workspace_to_binding() -> None:
    """ResolvedWorkspace → RuntimeWorkspaceBinding is a pure value mapping."""
    resolved = _local_workspace("w1", read=True)
    binding = bind_workspace(resolved)
    assert binding.workspace_id == "w1"
    assert binding.kind == WorkspaceKind.LOCAL
    assert binding.local_path == resolved.root_path
    assert binding.permissions == resolved.permissions


# ============================================================
# BEGIN: No Workspace Selected
# ============================================================


def test_no_workspace_reaches_runtime_as_none() -> None:
    async def scenario() -> None:
        registry = _registry_with(_local_workspace("w1"))
        runtime = RecordingRuntime()
        agent = NativeAgentAdapter(runtime, EchoProvider(), workspace_resolver=WorkspaceResolver(registry))
        result = await agent.start_run("run", RunRequest(prompt="hello"))
        assert result.status == RunStatus.COMPLETED
        assert runtime.calls == 1
        assert runtime.received == [None]

    asyncio.run(scenario())


def test_no_workspace_without_resolver_still_executes_normally() -> None:
    async def scenario() -> None:
        runtime = RecordingRuntime()
        agent = NativeAgentAdapter(runtime, EchoProvider())
        result = await agent.start_run("run", RunRequest(prompt="hello"))
        assert result.status == RunStatus.COMPLETED
        assert runtime.received == [None]

    asyncio.run(scenario())


# ============================================================
# BEGIN: Known Workspace
# ============================================================


def test_known_workspace_resolves_and_reaches_selected_runtime() -> None:
    async def scenario() -> None:
        workspace = _local_workspace("known-workspace", read=True)
        registry = _registry_with(workspace)
        runtime = RecordingRuntime()
        agent = NativeAgentAdapter(runtime, EchoProvider(), workspace_resolver=WorkspaceResolver(registry))
        result = await agent.start_run(
            "run", RunRequest(prompt="hello", workspace_id="known-workspace")
        )
        assert result.status == RunStatus.COMPLETED
        assert runtime.calls == 1
        binding = runtime.received[0]
        assert isinstance(binding, RuntimeWorkspaceBinding)
        assert binding.workspace_id == "known-workspace"
        assert binding.kind == workspace.info.kind
        assert binding.local_path == workspace.root_path
        assert binding.permissions == workspace.permissions

    asyncio.run(scenario())


def test_known_workspace_resolution_goes_through_registered_resolver() -> None:
    """The runtime receives the exact resolved workspace, not a re-lookup."""
    resolved = _local_workspace("w1", read=True)
    registry = _registry_with(resolved)
    resolver = WorkspaceResolver(registry)
    binding = bind_workspace(resolver.resolve("w1"))
    assert binding.workspace_id == "w1"
    assert binding.permissions.read is True
    assert resolver.resolve("w1") is resolved


# ============================================================
# BEGIN: Unknown Workspace
# ============================================================


@pytest.mark.parametrize("workspace_id", ["missing-workspace", "", "   "])
def test_unknown_workspace_fails_cleanly_without_execution(workspace_id: str) -> None:
    async def scenario() -> None:
        registry = _registry_with(_local_workspace("w1"))
        runtime = RecordingRuntime()
        agent = NativeAgentAdapter(runtime, EchoProvider(), workspace_resolver=WorkspaceResolver(registry))
        result = await agent.start_run(
            "run", RunRequest(prompt="hello", workspace_id=workspace_id)
        )
        assert result.status == RunStatus.FAILED
        assert result.content == "Requested workspace is unavailable"
        assert runtime.calls == 0

    asyncio.run(scenario())


def test_unknown_workspace_raises_unknown_workspace_error_from_resolver() -> None:
    resolver = WorkspaceResolver(_registry_with(_local_workspace("w1")))
    with pytest.raises(UnknownWorkspaceError) as exc_info:
        resolver.resolve("missing-workspace")
    assert exc_info.value.workspace_id == "missing-workspace"


def test_requested_workspace_without_resolver_fails_cleanly() -> None:
    """A requested workspace can never be silently granted without a resolver."""

    async def scenario() -> None:
        runtime = RecordingRuntime()
        agent = NativeAgentAdapter(runtime, EchoProvider())
        result = await agent.start_run(
            "run", RunRequest(prompt="hello", workspace_id="anything")
        )
        assert result.status == RunStatus.FAILED
        assert runtime.calls == 0

    asyncio.run(scenario())


# ============================================================
# BEGIN: Path-Like Values Are Opaque Workspace Ids
# ============================================================


@pytest.mark.parametrize(
    "workspace_id",
    ["/home/bizon/AvaUi", "../project", "/tmp/test", "C:\\host\\path", "./relative"],
)
def test_path_like_workspace_ids_are_opaque_and_fail_if_unregistered(workspace_id: str) -> None:
    async def scenario() -> None:
        registry = _registry_with(_local_workspace("w1"))
        with pytest.raises(UnknownWorkspaceError):
            WorkspaceResolver(registry).resolve(workspace_id)
        runtime = RecordingRuntime()
        agent = NativeAgentAdapter(runtime, EchoProvider(), workspace_resolver=WorkspaceResolver(registry))
        result = await agent.start_run(
            "run", RunRequest(prompt="hello", workspace_id=workspace_id)
        )
        assert result.status == RunStatus.FAILED
        assert runtime.calls == 0

    asyncio.run(scenario())


# ============================================================
# BEGIN: Permission Preservation
# ============================================================


@pytest.mark.parametrize(
    "permissions",
    [
        WorkspacePermissions(),
        WorkspacePermissions(read=True),
        WorkspacePermissions(read=True, write=True),
        WorkspacePermissions(read=True, write=True, shell=True),
        WorkspacePermissions(read=True, write=True, shell=True, network=True),
    ],
)
def test_permissions_arrive_unchanged_in_binding(permissions: WorkspacePermissions) -> None:
    async def scenario() -> None:
        resolved = ResolvedWorkspace(
            info=WorkspaceInfo("conservative", "conservative", WorkspaceKind.LOCAL),
            root_path=None,
            permissions=permissions,
        )
        registry = _registry_with(resolved)
        runtime = RecordingRuntime()
        agent = NativeAgentAdapter(runtime, EchoProvider(), workspace_resolver=WorkspaceResolver(registry))
        result = await agent.start_run(
            "run", RunRequest(prompt="hello", workspace_id="conservative")
        )
        assert result.status == RunStatus.COMPLETED
        binding = runtime.received[0]
        assert isinstance(binding, RuntimeWorkspaceBinding)
        assert binding.permissions == permissions

    asyncio.run(scenario())


def test_binding_never_elevates_permissions() -> None:
    """Conservative workspace permissions must not widen at the adapter."""
    resolved = _local_workspace("no-perms")
    assert resolved.permissions == WorkspacePermissions()
    binding = bind_workspace(resolved)
    assert binding.permissions == WorkspacePermissions()
    assert binding.permissions.write is False
    assert binding.permissions.shell is False
    assert binding.permissions.network is False


# ============================================================
# BEGIN: Native Runtime
# ============================================================


def test_native_runtime_receives_binding_but_execution_is_unchanged() -> None:
    async def scenario() -> None:
        registry = _registry_with(_local_workspace("w1", read=True))
        agent = NativeAgentAdapter(NativeRuntime(), EchoProvider(), workspace_resolver=WorkspaceResolver(registry))
        result = await agent.start_run(
            "run", RunRequest(prompt="Hello", workspace_id="w1")
        )
        assert result.status == RunStatus.COMPLETED
        assert result.content == "reply to Hello"
        assert agent._selector._runtime._run_tasks == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("binding", [None, bind_workspace(_local_workspace("w1"))])
def test_native_runtime_accepts_and_ignores_workspace_no_filesystem(binding: RuntimeWorkspaceBinding | None) -> None:
    async def scenario() -> None:
        runtime = NativeRuntime()
        result = await runtime.execute(
            run_id="run",
            request=RunRequest(prompt="Hello"),
            model_provider=EchoProvider(),
            workspace=binding,
        )
        assert result.status == RunStatus.COMPLETED
        assert result.content == "reply to Hello"
        assert runtime._run_tasks == {}

    asyncio.run(scenario())


def test_native_runtime_failure_content_has_no_workspace_or_path() -> None:
    class FailingProvider(EchoProvider):
        async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
            del request, model_name
            raise ModelProviderError("http://localhost/secret")

    async def scenario() -> None:
        runtime = NativeRuntime()
        result = await runtime.execute(
            run_id="run",
            request=RunRequest(prompt="Hello"),
            model_provider=FailingProvider(),
            workspace=bind_workspace(_local_workspace("w1")),
        )
        assert result.status == RunStatus.FAILED
        assert result.content == "Model provider request failed"

    asyncio.run(scenario())


# ============================================================
# BEGIN: OpenHands Runtime
# ============================================================


def test_openhands_workspace_path_uses_approved_local_path() -> None:
    binding = bind_workspace(_local_workspace("ava-workspace"))
    assert binding.local_path is not None
    assert _workspace_path(binding) == str(binding.local_path)


def test_openhands_workspace_path_uses_isolated_fallback_when_absent() -> None:
    """No workspace → OpenHands' isolated default, never a host path."""
    assert _workspace_path(None) == "workspace/project"
    # A binding without a local path keeps the isolated default too.
    empty = RuntimeWorkspaceBinding(
        workspace_id="ephemeral",
        kind=WorkspaceKind.EPHEMERAL,
        local_path=None,
        permissions=WorkspacePermissions(),
    )
    assert _workspace_path(empty) == "workspace/project"
    assert not Path(_workspace_path(empty)).is_absolute()


def _stub_sdk_binding(
    provider: ModelProviderPort, binding: ConfiguredModelBinding
) -> RuntimeModelBinding:
    """Deterministic model binding so tests focus on workspace behavior."""
    del provider
    return RuntimeModelBinding(
        model_id=binding.model_id,
        provider_id=binding.provider_id,
        provider_model_name=binding.provider_model_name,
        protocol="openai",
        endpoint="http://localhost/v1",
        api_key=None,
    )


def _stub_openhands_sdk(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Inject a deterministic fake for the optional OpenHands SDK module."""

    class _Part:
        def __init__(self, text: str) -> None:
            self.text = text

    class _LLMMessage:
        def __init__(self, text: str) -> None:
            self.content = [_Part(text)]

    class _Event:
        source = "agent"
        llm_message = _LLMMessage("OpenHands answer")

    class _State:
        events = [_Event()]

    class _Conversation:
        def __init__(self, agent: object, workspace: str) -> None:
            self.agent = agent
            self.workspace = workspace
            self.state = _State()
            self.prompt: str | None = None

        def send_message(self, prompt: str) -> None:
            self.prompt = prompt

        def run(self) -> None:
            return None

    class _Agent:
        def __init__(
            self,
            llm: object,
            tools: list[object],
            include_default_tools: list[str],
            agent_context: object | None = None,
        ) -> None:
            assert include_default_tools == []
            self.llm = llm
            self.tools = tools
            self.agent_context = agent_context

    class _LLM:
        def __init__(self, model: str, base_url: str, api_key: str) -> None:
            self.model = model
            self.base_url = base_url
            self.api_key = api_key

    stub = types.ModuleType("openhands.sdk")
    stub.LLM = _LLM
    stub.Agent = _Agent
    stub.Conversation = _Conversation
    monkeypatch.setitem(sys.modules, "openhands.sdk", stub)
    sdk_context = types.ModuleType("openhands.sdk.context")

    class _AgentContext:
        def __init__(self, **values: object) -> None:
            self.values = values

    sdk_context.AgentContext = _AgentContext
    monkeypatch.setitem(sys.modules, "openhands.sdk.context", sdk_context)
    controlled = types.ModuleType("ava.runtimes.adapters.openhands.conversation")
    controlled.ControlledAgent = _Agent
    controlled.ControlledConversation = lambda **kwargs: stub.Conversation(
        agent=kwargs["agent"], workspace=kwargs["workspace"])
    monkeypatch.setitem(sys.modules, controlled.__name__, controlled)
    return stub


def test_openhands_receives_approved_binding_when_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ava.runtimes.adapters.openhands import openhands_runtime

    stub = _stub_openhands_sdk(monkeypatch)
    real_conversation = stub.Conversation
    captured = {}

    def fake_conversation(agent: object, workspace: str) -> object:
        captured["workspace"] = workspace
        captured["tools_empty"] = getattr(agent, "tools", None) == []
        captured["llm_model"] = getattr(getattr(agent, "llm", None), "model", None)
        return real_conversation(agent=agent, workspace=workspace)

    monkeypatch.setattr(stub, "Conversation", fake_conversation)
    monkeypatch.setattr(openhands_runtime, "bind_model_provider", _stub_sdk_binding)
    binding = bind_workspace(_local_workspace("ava-workspace"))
    runtime = OpenHandsRuntime()

    async def scenario() -> RuntimeRunResult:
        return await runtime.execute(
            run_id="run",
            request=RunRequest(prompt="Hello"),
            model_provider=EchoProvider(),
            workspace=binding,
            model_binding=ConfiguredModelBinding(
                model_id="ava/selected", provider_id="test", provider_model_name="selected-native"
            ),
        )

    result = asyncio.run(scenario())
    assert result.status == RunStatus.COMPLETED, result.content
    assert result.content == "OpenHands answer"
    assert captured["workspace"] == str(binding.local_path)
    assert captured["tools_empty"] is True
    assert captured["llm_model"] == "openai/selected-native"


def test_openhands_isolated_fallback_when_no_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    from ava.runtimes.adapters.openhands import openhands_runtime

    stub = _stub_openhands_sdk(monkeypatch)
    real_conversation = stub.Conversation
    captured = {}

    def fake_conversation(agent: object, workspace: str) -> object:
        captured["workspace"] = workspace
        return real_conversation(agent=agent, workspace=workspace)

    monkeypatch.setattr(stub, "Conversation", fake_conversation)
    monkeypatch.setattr(openhands_runtime, "bind_model_provider", _stub_sdk_binding)
    runtime = OpenHandsRuntime()

    async def scenario() -> RuntimeRunResult:
        return await runtime.execute(
            run_id="run",
            request=RunRequest(prompt="Hello"),
            model_provider=EchoProvider(),
            workspace=None,
        )

    result = asyncio.run(scenario())
    assert result.status == RunStatus.COMPLETED
    assert result.content == "OpenHands answer"
    assert captured["workspace"] == "workspace/project"


def test_openhands_read_workspace_requests_tools_and_fails_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    from ava.runtimes.adapters.openhands import file_policy, openhands_runtime

    stub = _stub_openhands_sdk(monkeypatch)
    # Explicitly simulate the missing optional dependency, independent of test order.
    monkeypatch.setitem(sys.modules, "ava.runtimes.adapters.openhands.file_tools", None)
    import ava.runtimes.adapters.openhands as adapter_package
    monkeypatch.delattr(adapter_package, "file_tools", raising=False)
    requested: list[RuntimeWorkspaceBinding | None] = []
    conversation_built: list[object] = []

    def fake_build(workspace: RuntimeWorkspaceBinding | None, **kwargs: object) -> list[object]:
        requested.append(workspace)
        return ["file_editor"]  # non-empty spec list -> contained impl must load

    monkeypatch.setattr(file_policy, "build_openhands_tools", fake_build)

    def fake_conversation(agent: object, workspace: str) -> object:
        conversation_built.append(agent)
        return stub.Conversation(agent=agent, workspace=workspace)

    monkeypatch.setattr(stub, "Conversation", fake_conversation)
    monkeypatch.setattr(openhands_runtime, "bind_model_provider", _stub_sdk_binding)
    binding = bind_workspace(_local_workspace("w1", read=True))

    async def scenario() -> RuntimeRunResult:
        return await OpenHandsRuntime().execute(
            run_id="run",
            request=RunRequest(prompt="Hello"),
            model_provider=EchoProvider(),
            workspace=binding,
        )

    result = asyncio.run(scenario())
    assert result.status == RunStatus.FAILED
    assert result.content == "OpenHands file tools are unavailable"
    assert requested == [binding]
    assert conversation_built == []  # never silently reaches the agent tool-less


# ============================================================
# BEGIN: Side-Effect-Free Resolution
# ============================================================


def test_resolution_does_not_mutate_registry_or_touch_filesystem(tmp_path: Path) -> None:
    workspace = _local_workspace("w1", read=True)
    registry = _registry_with(workspace)
    resolver = WorkspaceResolver(registry)
    before = registry.list()
    resolved = resolver.resolve("w1")
    assert registry.list() == before
    assert resolved is workspace
    # The advertised path exists only as an approved reference; resolving never
    # creates or reads the directory.
    assert not workspace.root_path.exists()


def test_runtimes_receive_binding_via_agent_port_end_to_end() -> None:
    """RunRequest.workspace_id → resolver → binding → AgentRuntimePort."""
    workspace = _local_workspace("selected", read=True, write=False)
    registry = _registry_with(workspace)
    runtime = RecordingRuntime()
    agent = NativeAgentAdapter(runtime, EchoProvider(), workspace_resolver=WorkspaceResolver(registry))
    request = RunRequest(prompt="hello", workspace_id="selected")

    result = asyncio.run(agent.start_run("run", request))
    assert result.status == RunStatus.COMPLETED
    binding = runtime.received[0]
    assert isinstance(binding, RuntimeWorkspaceBinding)
    assert binding.workspace_id == "selected"
    assert binding.permissions == WorkspacePermissions(read=True, write=False, shell=False, network=False)
