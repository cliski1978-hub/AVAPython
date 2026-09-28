"""Step 44 integrated proof for two AVA models behind one provider."""

import asyncio
from dataclasses import dataclass

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.contracts.conversations import RunContext
from ava.contracts.execution import RunExecutionOverride
from ava.contracts.models import (
    ModelCapabilities,
    ModelHostingMode,
    ModelInfo,
    ModelProviderHealth,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo
from ava.execution.model_orchestrator import ModelOrchestrator, ModelSelectionRequest
from ava.execution.model_resources import (
    ModelResourceAdapterRegistry,
    ModelResourceDescriptor,
    ModelResourceManager,
    ModelResourceState,
)
from ava.execution.selector import ExecutionSelector
from ava.models.bindings import ConfiguredModelBinding, ModelBindingResolver, model_binding_from_profile
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.qualifications import ModelQualificationStore
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.runtimes.contracts import AgentRuntimePort, RuntimeRunResult
from ava.runtimes.registry import RuntimeRegistry
from ava.runtimes.resolver import RuntimeResolver
from ava.workspaces.contracts import RuntimeWorkspaceBinding

MODEL_A = "local-coder-a"
MODEL_B = "local-coder-b"
PROVIDER_ID = "local"
NATIVE_A = "qwen-coder-a"
NATIVE_B = "qwen-coder-b"


class RecordingResourceAdapter:
    def __init__(self) -> None:
        self.states = {MODEL_A: ModelResourceState.COLD, MODEL_B: ModelResourceState.COLD}
        self.loads: list[str] = []
        self.unloads: list[str] = []

    async def get_state(self, model_id: str) -> ModelResourceState:
        return self.states[model_id]

    async def load(self, model_id: str) -> None:
        self.loads.append(model_id)
        self.states[model_id] = ModelResourceState.HOT

    async def unload(self, model_id: str) -> None:
        self.unloads.append(model_id)
        self.states[model_id] = ModelResourceState.COLD


class RecordingProvider(ModelProviderPort):
    def __init__(self, *, failure: bool = False, blocking: bool = False) -> None:
        self.failure = failure
        self.blocking = blocking
        self.started = asyncio.Event()
        self.cancelled = False
        self.model_names: list[str | None] = []

    def name(self) -> str:
        return PROVIDER_ID

    async def health(self) -> ModelProviderHealth:
        raise AssertionError("Provider health is outside the execution proof")

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=MODEL_A,
            provider_name=PROVIDER_ID,
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        del request
        self.model_names.append(model_name)
        self.started.set()
        if self.blocking:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.failure:
            raise RuntimeError("execution failed")
        return ModelResponse(content="ok", model_id=model_name or "")


@dataclass(frozen=True)
class Invocation:
    model_id: str
    provider_id: str
    provider_model_name: str


class RecordingRuntime(AgentRuntimePort):
    """Execution edge that records the binding AVA supplied before invoking the provider."""

    def __init__(self) -> None:
        self.invocations: list[Invocation] = []

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
        context: RunContext | None = None,
    ) -> RuntimeRunResult:
        del run_id, workspace, context
        assert model_binding is not None
        self.invocations.append(
            Invocation(
                model_id=model_binding.model_id,
                provider_id=model_binding.provider_id,
                provider_model_name=model_binding.provider_model_name,
            )
        )
        response = await model_provider.generate(
            ModelRequest(messages=[]), model_name=model_binding.provider_model_name
        )
        return RuntimeRunResult(status=RunStatus.COMPLETED, content=response.content)

    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        del run_id
        return RuntimeRunResult(status=RunStatus.CANCELLED)


@dataclass
class ExecutionHarness:
    agent: NativeAgentAdapter
    orchestrator: ModelOrchestrator
    registry: ModelRegistry
    resources: ModelResourceManager
    resource_adapter: RecordingResourceAdapter
    runtime: RecordingRuntime
    provider: RecordingProvider


def _profile(model_id: str, provider_model_name: str) -> ModelProfile:
    return ModelProfile(
        model_id=model_id,
        display_name=model_id,
        provider_id=PROVIDER_ID,
        provider_model_name=provider_model_name,
        hosting_mode=ModelHostingMode.LOCAL,
        capabilities=ModelCapabilities(chat=True),
    )


def _harness(*, failure: bool = False, blocking: bool = False) -> ExecutionHarness:
    registry = ModelRegistry((_profile(MODEL_A, NATIVE_A), _profile(MODEL_B, NATIVE_B)))
    orchestrator = ModelOrchestrator(
        registry=registry,
        qualification_store=ModelQualificationStore(registry),
        default_model_id=MODEL_A,
    )
    provider = RecordingProvider(failure=failure, blocking=blocking)
    provider_registry = ModelProviderRegistry()
    provider_registry.register(PROVIDER_ID, provider)
    runtime = RecordingRuntime()
    runtime_registry = RuntimeRegistry()
    runtime_registry.register("recording", runtime)
    selector = ExecutionSelector(
        runtime_resolver=RuntimeResolver(runtime_registry),
        model_provider_resolver=ModelProviderResolver(provider_registry),
        model_binding_resolver=ModelBindingResolver(registry, default_model_id=MODEL_A),
        default_runtime_id="recording",
        default_model_provider_id=PROVIDER_ID,
        model_orchestrator=orchestrator,
    )
    resource_adapter = RecordingResourceAdapter()
    resources = ModelResourceManager(
        registry=registry,
        descriptors=(
            ModelResourceDescriptor(MODEL_A, "recording"),
            ModelResourceDescriptor(MODEL_B, "recording"),
        ),
        adapters=ModelResourceAdapterRegistry({"recording": resource_adapter}),
    )
    return ExecutionHarness(
        agent=NativeAgentAdapter(selector, model_resource_manager=resources),
        orchestrator=orchestrator,
        registry=registry,
        resources=resources,
        resource_adapter=resource_adapter,
        runtime=runtime,
        provider=provider,
    )


async def _assert_selected_model_b_is_released(harness: ExecutionHarness) -> None:
    assert await harness.resources.get_state(MODEL_B) is ModelResourceState.HOT
    await harness.resources.unload(MODEL_B)
    assert harness.resource_adapter.unloads == [MODEL_B]
    assert await harness.resources.get_state(MODEL_A) is ModelResourceState.COLD
    assert harness.resource_adapter.loads == [MODEL_B]


def test_selected_model_id_drives_shared_provider_execution_and_lease() -> None:
    async def scenario() -> None:
        harness = _harness()
        decision = harness.orchestrator.select(ModelSelectionRequest(explicit_model_id=MODEL_B))
        profile = harness.registry.get(decision.model_id)
        assert profile is not None
        binding = model_binding_from_profile(profile)

        result = await harness.agent.start_run(
            "run", RunRequest(prompt="execute model b", execution=RunExecutionOverride(model_id=MODEL_B))
        )

        assert result.status is RunStatus.COMPLETED
        assert decision.model_id == MODEL_B == profile.model_id == binding.model_id
        assert binding.provider_id == profile.provider_id == PROVIDER_ID
        assert binding.provider_model_name == profile.provider_model_name == NATIVE_B
        assert harness.runtime.invocations == [Invocation(MODEL_B, PROVIDER_ID, NATIVE_B)]
        assert harness.provider.model_names == [NATIVE_B]
        assert harness.resource_adapter.loads == [MODEL_B]
        await _assert_selected_model_b_is_released(harness)

    asyncio.run(scenario())


def test_selected_model_lease_is_released_when_execution_fails() -> None:
    async def scenario() -> None:
        harness = _harness(failure=True)

        result = await harness.agent.start_run(
            "run", RunRequest(prompt="fail", execution=RunExecutionOverride(model_id=MODEL_B))
        )

        assert result.status is RunStatus.FAILED
        assert harness.runtime.invocations == [Invocation(MODEL_B, PROVIDER_ID, NATIVE_B)]
        assert harness.provider.model_names == [NATIVE_B]
        await _assert_selected_model_b_is_released(harness)

    asyncio.run(scenario())


def test_selected_model_lease_is_released_when_execution_is_cancelled() -> None:
    async def scenario() -> None:
        harness = _harness(blocking=True)
        task = asyncio.create_task(
            harness.agent.start_run(
                "run", RunRequest(prompt="cancel", execution=RunExecutionOverride(model_id=MODEL_B))
            )
        )
        await asyncio.wait_for(harness.provider.started.wait(), 1)

        task.cancel()
        result = await asyncio.wait_for(task, 1)

        assert result.status is RunStatus.CANCELLED
        assert harness.provider.cancelled
        assert harness.runtime.invocations == [Invocation(MODEL_B, PROVIDER_ID, NATIVE_B)]
        assert harness.provider.model_names == [NATIVE_B]
        await _assert_selected_model_b_is_released(harness)

    asyncio.run(scenario())
