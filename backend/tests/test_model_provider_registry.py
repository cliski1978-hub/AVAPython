"""ModelProviderRegistry tests.

Verify that the central backend registry (Phase 3 Step 5) registers, looks up,
and lists model providers under AVA provider identities, and that it behaves
correctly for duplicates and unknown ids.
"""

import asyncio

from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelMessage,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.models.contracts import ModelProviderPort
from ava.models.registry import ModelProviderRegistry

# ============================================================
# BEGIN: Registry Provider Stub
# ============================================================


class RegistryProvider(ModelProviderPort):
    """Minimal test-only ModelProviderPort implementation.

    The registry is a pure container over the port abstraction, so tests
    register a stub that only needs to satisfy the port shape.
    """

    def __init__(self, model_id: str = "registry-provider") -> None:
        self._model_id = model_id

    def name(self) -> str:
        return "registry-provider"

    async def health(self) -> ModelProviderHealth:
        return ModelProviderHealth(
            available=True,
            status=ModelProviderHealthStatus.HEALTHY,
        )

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider_name=self.name(),
            model_id=self._model_id,
            capabilities=self.get_capabilities(),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content="reply", model_id=self._model_id)


# ============================================================
# END: Registry Provider Stub
# ============================================================


# ============================================================
# BEGIN: Registry Tests
# ============================================================


def test_register_and_get() -> None:
    """A registered provider is retrievable by its AVA provider identity."""
    registry = ModelProviderRegistry()
    provider = RegistryProvider()
    registry.register("mock", provider)
    assert registry.get("mock") is provider


def test_unknown_provider_returns_none() -> None:
    """Getting an unregistered provider id returns ``None``."""
    registry = ModelProviderRegistry()
    assert registry.get("not-registered") is None


def test_contains() -> None:
    """``contains`` reflects what is registered."""
    registry = ModelProviderRegistry()
    assert not registry.contains("mock")
    registry.register("mock", RegistryProvider())
    assert registry.contains("mock")
    assert not registry.contains("external")


def test_list_returns_insertion_order() -> None:
    """``list`` returns registered provider ids in insertion order."""
    registry = ModelProviderRegistry()
    assert registry.list() == []
    for provider_id, model_id in (
        ("mock", "mock-model"),
        ("local", "local-model"),
        ("corporate", "corporate-model"),
        ("external", "external-model"),
    ):
        registry.register(provider_id, RegistryProvider(model_id=model_id))
    assert registry.list() == ["mock", "local", "corporate", "external"]


def test_duplicate_provider_id_is_rejected() -> None:
    """Registering the same provider id twice raises ``ValueError``."""
    registry = ModelProviderRegistry()
    registry.register("mock", RegistryProvider())
    try:
        registry.register("mock", RegistryProvider())
    except ValueError as error:
        assert "mock" in str(error)
    else:
        raise AssertionError("duplicate registration did not raise ValueError")


def test_blank_provider_id_is_rejected() -> None:
    """Registering with a blank provider id raises ``ValueError``."""
    registry = ModelProviderRegistry()
    for blank in ("", "   "):
        try:
            registry.register(blank, RegistryProvider())
        except ValueError as error:
            assert "non-blank" in str(error)
        else:
            raise AssertionError(f"blank id {blank!r} did not raise ValueError")


def test_each_registry_is_state_independent() -> None:
    """Registries do not share provider state across instances."""
    first = ModelProviderRegistry()
    second = ModelProviderRegistry()
    first.register("mock", RegistryProvider())
    assert first.contains("mock")
    assert not second.contains("mock")


def test_get_returns_model_provider_port() -> None:
    """Retrieved providers satisfy the AVA model-provider port boundary."""
    registry = ModelProviderRegistry()
    registry.register("mock", RegistryProvider())
    provider = registry.get("mock")
    assert isinstance(provider, ModelProviderPort)
    assert provider is not None
    assert provider.get_model_info().capabilities == provider.get_capabilities()
    asyncio.run(_exercise(provider))


async def _exercise(provider: ModelProviderPort) -> None:
    """Drive the retrieved provider through its async port methods."""
    health = await provider.health()
    assert health.available
    response = await provider.generate(
        ModelRequest(messages=[ModelMessage(role="user", content="hi")]),
    )
    assert response.content == "reply"


# ============================================================
# END: Registry Tests
# ============================================================