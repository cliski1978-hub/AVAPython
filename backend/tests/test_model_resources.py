"""Step 43 deterministic resource-manager lifecycle tests."""

import asyncio

import pytest

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
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
from ava.execution.model_resources import (
    ModelCapacityExceededError,
    ModelLeaseConflictError,
    ModelLoadError,
    ModelResourceAdapterRegistry,
    ModelResourceDescriptor,
    ModelResourceError,
    ModelResourceManager,
    ModelResourceState,
    ModelResourceUnavailableError,
    ResourceCapacity,
)
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.runtimes.adapters.native.native_runtime import NativeRuntime


class FakeResourceAdapter:
    def __init__(
        self, states: dict[str, ModelResourceState], *, fail_load: bool = False, fail_unload: bool = False
    ) -> None:
        self.states = states
        self.fail_load = fail_load
        self.fail_unload = fail_unload
        self.loads: list[str] = []
        self.unloads: list[str] = []

    async def get_state(self, model_id: str) -> ModelResourceState:
        return self.states[model_id]

    async def load(self, model_id: str) -> None:
        self.loads.append(model_id)
        if self.fail_load:
            raise RuntimeError("load failed")
        self.states[model_id] = ModelResourceState.HOT

    async def unload(self, model_id: str) -> None:
        self.unloads.append(model_id)
        if self.fail_unload:
            raise RuntimeError("unload failed")
        self.states[model_id] = ModelResourceState.COLD


class FailingProvider(ModelProviderPort):
    def name(self) -> str:
        return "provider"

    async def health(self) -> ModelProviderHealth:
        raise AssertionError("not used")

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(provider_name="provider", model_id="ava/a", capabilities=ModelCapabilities(chat=True))

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        del request, model_name
        raise RuntimeError("provider failure")


class BlockingProvider(ModelProviderPort):
    """Blocks inside generation so a run can be cancelled while leased."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    def name(self) -> str:
        return "provider"

    async def health(self) -> ModelProviderHealth:
        raise AssertionError("not used")

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(provider_name="provider", model_id="ava/a", capabilities=ModelCapabilities(chat=True))

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        del request, model_name
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return ModelResponse(content="ok", model_id="ava/a")


def _profile(model_id: str, hosting: ModelHostingMode = ModelHostingMode.LOCAL) -> ModelProfile:
    return ModelProfile(
        model_id=model_id,
        display_name=model_id,
        provider_id="provider",
        provider_model_name=f"{model_id}-native",
        hosting_mode=hosting,
        capabilities=ModelCapabilities(chat=True),
    )


def _manager(
    profiles: tuple[ModelProfile, ...],
    adapter: FakeResourceAdapter,
    *,
    capacity: ResourceCapacity | None = None,
    vram: int | None = None,
) -> ModelResourceManager:
    registry = ModelRegistry(profiles)
    return ModelResourceManager(
        registry=registry,
        descriptors=tuple(
            ModelResourceDescriptor(profile.model_id, "fake", estimated_vram_mb=vram) for profile in profiles
        ),
        adapters=ModelResourceAdapterRegistry({"fake": adapter}),
        capacity=capacity,
    )


def test_cold_loads_to_hot_and_idle_hot_unloads_to_cold() -> None:
    async def scenario() -> None:
        adapter = FakeResourceAdapter({"ava/a": ModelResourceState.COLD})
        manager = _manager((_profile("ava/a"),), adapter)
        assert await manager.get_state("ava/a") is ModelResourceState.COLD
        lease = await manager.acquire("ava/a")
        assert adapter.loads == ["ava/a"]
        assert await manager.get_state("ava/a") is ModelResourceState.HOT
        await lease.release()
        await manager.unload("ava/a")
        assert adapter.unloads == ["ava/a"]
        assert await manager.get_state("ava/a") is ModelResourceState.COLD

    asyncio.run(scenario())


def test_concurrent_same_model_acquire_loads_once_and_each_lease_releases() -> None:
    async def scenario() -> None:
        adapter = FakeResourceAdapter({"ava/a": ModelResourceState.COLD})
        manager = _manager((_profile("ava/a"),), adapter)
        first, second = await asyncio.gather(manager.acquire("ava/a"), manager.acquire("ava/a"))
        assert adapter.loads == ["ava/a"]
        with pytest.raises(ModelLeaseConflictError):
            await manager.unload("ava/a")
        await first.release()
        with pytest.raises(ModelLeaseConflictError):
            await manager.unload("ava/a")
        await second.release()
        await manager.unload("ava/a")
        with pytest.raises(Exception, match="already released"):
            await second.release()

    asyncio.run(scenario())


def test_load_failure_becomes_unavailable_without_stuck_loading() -> None:
    async def scenario() -> None:
        adapter = FakeResourceAdapter({"ava/a": ModelResourceState.COLD}, fail_load=True)
        manager = _manager((_profile("ava/a"),), adapter)
        with pytest.raises(ModelLoadError):
            await manager.acquire("ava/a")
        assert await manager.get_state("ava/a") is ModelResourceState.UNAVAILABLE
        with pytest.raises(ModelResourceUnavailableError):
            await manager.acquire("ava/a")

    asyncio.run(scenario())


def test_invalid_transition_is_rejected() -> None:
    async def scenario() -> None:
        adapter = FakeResourceAdapter({"ava/a": ModelResourceState.COLD})
        manager = _manager((_profile("ava/a"),), adapter)
        await manager.get_state("ava/a")
        with pytest.raises(ModelResourceError, match="Invalid resource transition"):
            manager._transition("ava/a", ModelResourceState.HOT)

    asyncio.run(scenario())


def test_capacity_fails_closed_without_evicting_another_hot_model() -> None:
    async def scenario() -> None:
        adapter = FakeResourceAdapter({"ava/a": ModelResourceState.COLD, "ava/b": ModelResourceState.COLD})
        manager = _manager(
            (_profile("ava/a"), _profile("ava/b")), adapter, capacity=ResourceCapacity(vram_mb=8), vram=8
        )
        lease = await manager.acquire("ava/a")
        with pytest.raises(ModelCapacityExceededError):
            await manager.acquire("ava/b")
        assert adapter.unloads == []
        await lease.release()

    asyncio.run(scenario())


def test_remote_model_is_adapter_ready_and_does_not_load_or_consume_local_capacity() -> None:
    async def scenario() -> None:
        adapter = FakeResourceAdapter({"ava/remote": ModelResourceState.HOT})
        manager = _manager(
            (_profile("ava/remote", ModelHostingMode.EXTERNAL),),
            adapter,
            capacity=ResourceCapacity(vram_mb=0),
            vram=100,
        )
        lease = await manager.acquire("ava/remote")
        assert adapter.loads == []
        await lease.release()

    asyncio.run(scenario())


def test_native_execution_failure_releases_lease_in_finally() -> None:
    async def scenario() -> None:
        adapter = FakeResourceAdapter({"ava/a": ModelResourceState.COLD})
        manager = _manager((_profile("ava/a"),), adapter)
        agent = NativeAgentAdapter(NativeRuntime(), FailingProvider(), model_resource_manager=manager)
        result = await agent.start_run("run", RunRequest(prompt="fail"))
        assert result.status.value == "failed"
        await manager.unload("ava/a")
        assert adapter.unloads == ["ava/a"]

    asyncio.run(scenario())


def test_cancelled_run_releases_lease_safely() -> None:
    async def scenario() -> None:
        adapter = FakeResourceAdapter({"ava/a": ModelResourceState.COLD})
        manager = _manager((_profile("ava/a"),), adapter)
        provider = BlockingProvider()
        agent = NativeAgentAdapter(NativeRuntime(), provider, model_resource_manager=manager)

        async def invoke_as_task() -> RunStatus:
            result = await agent.start_run("run", RunRequest(prompt="cancel"))
            return result.status

        task = asyncio.create_task(invoke_as_task())
        await asyncio.wait_for(provider.started.wait(), 1)
        assert provider.cancelled is False
        task.cancel()
        assert (await asyncio.wait_for(task, 1)) is RunStatus.CANCELLED
        assert provider.cancelled
        # Lease must be gone so the idle model can be explicitly unloaded.
        await manager.unload("ava/a")
        assert adapter.unloads == ["ava/a"]

    asyncio.run(scenario())


def test_unknown_model_id_fails_explicitly_without_fallback() -> None:
    async def scenario() -> None:
        adapter = FakeResourceAdapter({"ava/a": ModelResourceState.COLD})
        manager = _manager((_profile("ava/a"),), adapter)
        with pytest.raises(ModelResourceUnavailableError, match="not configured"):
            await manager.get_state("does-not-exist")
        with pytest.raises(ModelResourceUnavailableError, match="not configured"):
            await manager.acquire("does-not-exist")
        with pytest.raises(ModelResourceUnavailableError, match="not configured"):
            await manager.unload("does-not-exist")
        # No adapter work happened and no configured model was silently used.
        assert adapter.loads == []
        assert adapter.unloads == []
        assert adapter.states == {"ava/a": ModelResourceState.COLD}

    asyncio.run(scenario())
