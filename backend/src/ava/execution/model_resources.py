"""Runtime-neutral model residency, leases, and capacity transitions.

This module owns operational availability for an already selected model. It
does not inspect a request, choose a model, or grant workspace/tool authority.
Provider-specific lifecycle calls remain behind ``ModelResourceAdapter``.
"""

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ava.contracts.models import ModelHostingMode
from ava.models.model_registry import ModelRegistry


class ModelResourceState(StrEnum):
    COLD = "cold"
    WARM = "warm"
    LOADING = "loading"
    HOT = "hot"
    UNLOADING = "unloading"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ResourceCapacity:
    """Optional adapter-supplied capacity; ``None`` means unknown."""

    vram_mb: int | None = None
    ram_mb: int | None = None


@dataclass(frozen=True)
class ModelResourceDescriptor:
    """Operational metadata kept separate from descriptive ``ModelProfile``."""

    model_id: str
    resource_adapter_id: str
    estimated_vram_mb: int | None = None
    estimated_ram_mb: int | None = None


class ModelResourceAdapter(Protocol):
    """Provider/inference-specific lifecycle port with no credentials in its API."""

    async def get_state(self, model_id: str) -> ModelResourceState: ...

    async def load(self, model_id: str) -> None: ...

    async def unload(self, model_id: str) -> None: ...


class ModelResourceError(RuntimeError):
    """Base safe internal resource failure."""


class ModelResourceUnavailableError(ModelResourceError):
    pass


class ModelCapacityExceededError(ModelResourceError):
    pass


class ModelLeaseConflictError(ModelResourceError):
    pass


class ModelLoadError(ModelResourceError):
    pass


class ModelUnloadError(ModelResourceError):
    pass


class ModelLeaseReleasedError(ModelResourceError):
    pass


class ModelResourceAdapterRegistry:
    """Small, separate registry for lifecycle adapters."""

    def __init__(self, adapters: Mapping[str, ModelResourceAdapter]) -> None:
        self._adapters = dict(adapters)

    def get(self, adapter_id: str) -> ModelResourceAdapter | None:
        return self._adapters.get(adapter_id)


@dataclass(frozen=True)
class ModelLease:
    """One active use of a selected model; release prevents lease leaks."""

    model_id: str
    lease_id: str
    _manager: "ModelResourceManager"

    async def release(self) -> None:
        await self._manager.release(self)

    async def __aenter__(self) -> "ModelLease":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.release()


_ALLOWED_TRANSITIONS: dict[ModelResourceState, frozenset[ModelResourceState]] = {
    ModelResourceState.COLD: frozenset({ModelResourceState.LOADING, ModelResourceState.UNAVAILABLE}),
    ModelResourceState.WARM: frozenset({ModelResourceState.LOADING, ModelResourceState.UNAVAILABLE}),
    ModelResourceState.LOADING: frozenset({ModelResourceState.HOT, ModelResourceState.UNAVAILABLE}),
    ModelResourceState.HOT: frozenset({ModelResourceState.UNLOADING, ModelResourceState.UNAVAILABLE}),
    ModelResourceState.UNLOADING: frozenset({ModelResourceState.COLD, ModelResourceState.UNAVAILABLE}),
    ModelResourceState.UNAVAILABLE: frozenset(),
}


class ModelResourceManager:
    """Serialize selected-model lifecycle transitions and account for leases.

    Local models with known estimates are admitted only when the sum of known
    HOT local usage fits configured capacity. v1 does not evict a different
    model: capacity pressure fails closed. Remote models are adapter-owned and
    do not consume AVA-local capacity.
    """

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        descriptors: tuple[ModelResourceDescriptor, ...],
        adapters: ModelResourceAdapterRegistry,
        capacity: ResourceCapacity | None = None,
    ) -> None:
        self._registry = registry
        self._descriptors = {descriptor.model_id: descriptor for descriptor in descriptors}
        if len(self._descriptors) != len(descriptors):
            raise ValueError("duplicate resource descriptor model_id")
        for model_id, descriptor in self._descriptors.items():
            if registry.get(model_id) is None:
                raise ValueError(f"resource descriptor references unknown model: {model_id!r}")
            if adapters.get(descriptor.resource_adapter_id) is None:
                raise ValueError(f"unknown resource adapter: {descriptor.resource_adapter_id!r}")
        self._adapters = adapters
        self._capacity = capacity or ResourceCapacity()
        self._states: dict[str, ModelResourceState] = {}
        self._leases: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def get_state(self, model_id: str) -> ModelResourceState:
        async with self._lock:
            return await self._state_for(model_id)

    async def acquire(self, model_id: str) -> ModelLease:
        """Ensure the selected model is ready, then issue one active lease."""
        async with self._lock:
            state = await self._state_for(model_id)
            if state is ModelResourceState.UNAVAILABLE:
                raise ModelResourceUnavailableError("Selected model resource is unavailable")
            if state in {ModelResourceState.COLD, ModelResourceState.WARM}:
                await self._ensure_capacity(model_id)
                self._transition(model_id, ModelResourceState.LOADING)
                try:
                    await self._adapter_for(model_id).load(model_id)
                except Exception as error:
                    self._transition(model_id, ModelResourceState.UNAVAILABLE)
                    raise ModelLoadError("Selected model resource could not load") from error
                self._transition(model_id, ModelResourceState.HOT)
            elif state is not ModelResourceState.HOT:
                raise ModelResourceUnavailableError("Selected model resource is transitioning")
            lease_id = str(uuid.uuid4())
            self._leases[lease_id] = model_id
            return ModelLease(model_id=model_id, lease_id=lease_id, _manager=self)

    async def release(self, lease: ModelLease) -> None:
        """Release exactly one lease; models remain HOT until explicit unload."""
        async with self._lock:
            model_id = self._leases.get(lease.lease_id)
            if model_id != lease.model_id:
                raise ModelLeaseReleasedError("Model lease is already released or invalid")
            del self._leases[lease.lease_id]

    async def unload(self, model_id: str) -> None:
        """Explicitly unload an idle model; active leases always deny unload."""
        async with self._lock:
            if any(leased_model_id == model_id for leased_model_id in self._leases.values()):
                raise ModelLeaseConflictError("Cannot unload a model with active leases")
            state = await self._state_for(model_id)
            if state in {ModelResourceState.COLD, ModelResourceState.WARM}:
                return
            if state is not ModelResourceState.HOT:
                raise ModelResourceUnavailableError("Selected model resource is transitioning")
            self._transition(model_id, ModelResourceState.UNLOADING)
            try:
                await self._adapter_for(model_id).unload(model_id)
            except Exception as error:
                self._transition(model_id, ModelResourceState.UNAVAILABLE)
                raise ModelUnloadError("Selected model resource could not unload") from error
            self._transition(model_id, ModelResourceState.COLD)

    def _descriptor_for(self, model_id: str) -> ModelResourceDescriptor:
        descriptor = self._descriptors.get(model_id)
        if descriptor is None:
            raise ModelResourceUnavailableError("Selected model resource is not configured")
        return descriptor

    def _adapter_for(self, model_id: str) -> ModelResourceAdapter:
        descriptor = self._descriptor_for(model_id)
        adapter = self._adapters.get(descriptor.resource_adapter_id)
        if adapter is None:  # constructor validates; preserve fail-closed behavior.
            raise ModelResourceUnavailableError("Selected model resource is unavailable")
        return adapter

    async def _state_for(self, model_id: str) -> ModelResourceState:
        self._descriptor_for(model_id)
        if model_id not in self._states:
            self._states[model_id] = await self._adapter_for(model_id).get_state(model_id)
        return self._states[model_id]

    async def _ensure_capacity(self, model_id: str) -> None:
        profile = self._registry.get(model_id)
        descriptor = self._descriptor_for(model_id)
        if profile is None or profile.hosting_mode is not ModelHostingMode.LOCAL:
            return
        used_vram = used_ram = 0
        for other_id, other_descriptor in self._descriptors.items():
            other_profile = self._registry.get(other_id)
            if (
                other_id == model_id
                or other_profile is None
                or other_profile.hosting_mode is not ModelHostingMode.LOCAL
            ):
                continue
            if await self._state_for(other_id) is ModelResourceState.HOT:
                used_vram += other_descriptor.estimated_vram_mb or 0
                used_ram += other_descriptor.estimated_ram_mb or 0
        if (
            self._capacity.vram_mb is not None
            and descriptor.estimated_vram_mb is not None
            and used_vram + descriptor.estimated_vram_mb > self._capacity.vram_mb
        ):
            raise ModelCapacityExceededError("Insufficient local VRAM capacity")
        if (
            self._capacity.ram_mb is not None
            and descriptor.estimated_ram_mb is not None
            and used_ram + descriptor.estimated_ram_mb > self._capacity.ram_mb
        ):
            raise ModelCapacityExceededError("Insufficient local RAM capacity")

    def _transition(self, model_id: str, target: ModelResourceState) -> None:
        current = self._states[model_id]
        if target not in _ALLOWED_TRANSITIONS[current]:
            raise ModelResourceError(f"Invalid resource transition: {current.value} -> {target.value}")
        self._states[model_id] = target


class ProviderManagedResourceAdapter:
    """Pass-through adapter for providers that own their own residency.

    It reports AVA's lifecycle boundary as ready without claiming GPU/RAM
    telemetry or controlling remote/provider memory. Production uses it until a
    concrete provider lifecycle adapter is deliberately installed.
    """

    async def get_state(self, model_id: str) -> ModelResourceState:
        del model_id
        return ModelResourceState.HOT

    async def load(self, model_id: str) -> None:
        del model_id

    async def unload(self, model_id: str) -> None:
        del model_id
