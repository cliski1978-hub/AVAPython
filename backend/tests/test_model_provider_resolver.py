"""ModelProviderResolver tests.

Verify (Phase 3 Step 7) that the resolver turns a configured model provider id
into the registered ``ModelProviderPort`` through the registry, fails
explicitly for unknown and blank ids, never mutates the registry, and stays
independent of model-name selection.
"""

import asyncio

import pytest

from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelMessage,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.core.application import ApplicationConfig
from ava.models.contracts import ModelProviderPort
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver, UnknownModelProviderError

# ============================================================
# BEGIN: Resolver Provider Stub
# ============================================================


class ResolverProvider(ModelProviderPort):
    """Minimal test-only implementation of ModelProviderPort.

    Provides deterministic AVA-owned values so resolution tests never touch
    the network or a real provider.
    """

    def __init__(self, model_id: str = "resolver-provider") -> None:
        self._model_id = model_id

    def name(self) -> str:
        return "resolver-provider"

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
# END: Resolver Provider Stub
# ============================================================


def _registry_with(
    *provider_ids: str,
) -> tuple[ModelProviderRegistry, ModelProviderResolver, dict[str, ResolverProvider]]:
    """Build a registry+resolver populated with distinguishable providers."""
    registry = ModelProviderRegistry()
    providers: dict[str, ResolverProvider] = {}
    for provider_id in provider_ids:
        provider = ResolverProvider(model_id=f"{provider_id}-model")
        registry.register(provider_id, provider)
        providers[provider_id] = provider
    return registry, ModelProviderResolver(registry), providers


# ============================================================
# BEGIN: Resolution Tests
# ============================================================


def test_registered_provider_resolves() -> None:
    """Resolving a registered id returns the same provider instance."""
    registry, resolver, providers = _registry_with("provider-a")
    resolved = resolver.resolve("provider-a")
    assert resolved is providers["provider-a"]


def test_multiple_providers_resolve_independently() -> None:
    """Each registered provider resolves to its own object; none is derived."""
    registry, resolver, providers = _registry_with("provider-a", "provider-b")
    a = resolver.resolve("provider-a")
    b = resolver.resolve("provider-b")
    assert a is providers["provider-a"]
    assert b is providers["provider-b"]
    assert a is not b
    assert a.get_model_info().model_id == "provider-a-model"
    assert b.get_model_info().model_id == "provider-b-model"


def test_unknown_provider_fails_explicitly() -> None:
    """An unregistered id fails with the AVA-owned error, never a default."""
    registry, resolver, _ = _registry_with("provider-a")
    with pytest.raises(UnknownModelProviderError) as exc_info:
        resolver.resolve("missing-provider")
    assert exc_info.value.provider_id == "missing-provider"
    assert "missing-provider" in str(exc_info.value)


def test_blank_provider_id_fails_explicitly() -> None:
    """Blank and whitespace ids fail explicitly; no default is substituted."""
    registry, resolver, _ = _registry_with("local", "mock")
    for blank in ("", "   "):
        with pytest.raises(UnknownModelProviderError) as exc_info:
            resolver.resolve(blank)
        assert exc_info.value.provider_id == blank


def test_resolution_does_not_mutate_registry() -> None:
    """Resolution never registers, replaces, removes, or reorders providers."""
    registry, resolver, _ = _registry_with("provider-a", "provider-b")
    before = registry.list()
    resolver.resolve("provider-a")
    resolver.resolve("provider-b")
    with pytest.raises(UnknownModelProviderError):
        resolver.resolve("missing-provider")
    assert registry.list() == before
    assert registry.contains("provider-a")
    assert registry.contains("provider-b")


def test_resolved_provider_is_used_through_port_boundary() -> None:
    """Callers interact with the result only as a ModelProviderPort."""
    registry, resolver, _ = _registry_with("provider-a")
    provider = resolver.resolve("provider-a")
    assert isinstance(provider, ModelProviderPort)
    asyncio.run(_exercise_port(provider))


async def _exercise_port(provider: ModelProviderPort) -> None:
    """Drive the resolved provider through its async port methods."""
    health = await provider.health()
    assert health.available
    response = await provider.generate(
        ModelRequest(messages=[ModelMessage(role="user", content="hi")]),
    )
    assert response.content == "reply"


def test_config_provider_selects_configured_model_provider() -> None:
    """resolver.resolve(config.model_provider) selects the configured provider."""
    registry, resolver, providers = _registry_with("provider-a")
    config = ApplicationConfig(
        agent_provider="mock",
        model_provider="provider-a",
        model_name="model-a",
    )
    resolved = resolver.resolve(config.model_provider)
    assert resolved is providers["provider-a"]


def test_model_name_does_not_affect_resolution() -> None:
    """Changing model_name never changes which provider resolves."""
    registry, resolver, providers = _registry_with("provider-a")
    first = ApplicationConfig(
        agent_provider="mock",
        model_provider="provider-a",
        model_name="model-one",
    )
    second = ApplicationConfig(
        agent_provider="different-agent",
        model_provider="provider-a",
        model_name="model-two",
    )
    assert resolver.resolve(first.model_provider) is resolver.resolve(second.model_provider)
    assert resolver.resolve(first.model_provider) is providers["provider-a"]


# ============================================================
# END: Resolution Tests
# ============================================================