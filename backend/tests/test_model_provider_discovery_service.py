"""Model provider discovery service tests.

Verify (Phase 3 Step 10) that the discovery service enumerates registered
providers through the registry's public surface, reports model info and health
through the ``ModelProviderPort``, truthfully represents the configured
default provider id (including unknown/unregistered defaults), and isolates a
failing provider's health check so it never breaks discovery for the rest.
"""

import asyncio

from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.responses import ModelProviderDiscoveryResponse
from ava.models.contracts import ModelProviderPort
from ava.models.registry import ModelProviderRegistry
from ava.services.model_provider_discovery_service import ModelProviderDiscoveryService

# ============================================================
# BEGIN: Discovery Service Provider Stub
# ============================================================


class DiscoveryProvider(ModelProviderPort):
    """Minimal test-only provider with a controllable health result or failure."""

    def __init__(
        self,
        *,
        provider_name: str = "discovery-provider",
        model_id: str = "discovery-model",
        health: ModelProviderHealth | None = None,
        health_error: Exception | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._model_id = model_id
        self._health = health or ModelProviderHealth(
            available=True,
            status=ModelProviderHealthStatus.HEALTHY,
        )
        self._health_error = health_error

    def name(self) -> str:
        return self._provider_name

    async def health(self) -> ModelProviderHealth:
        if self._health_error is not None:
            raise self._health_error
        return self._health

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
# END: Discovery Service Provider Stub
# ============================================================


def _discover(
    registry: ModelProviderRegistry,
    default_provider_id: str = "local",
) -> ModelProviderDiscoveryResponse:
    """Run discovery through the service using the synchronous test harness."""
    service = ModelProviderDiscoveryService(
        registry=registry,
        default_provider_id=default_provider_id,
    )
    return asyncio.run(service.discover())


# ============================================================
# BEGIN: Discovery Service Tests
# ============================================================


def test_discovery_reports_single_healthy_provider() -> None:
    """A registered provider is reported with its model info and health."""
    registry = ModelProviderRegistry()
    registry.register("local", DiscoveryProvider(provider_name="local", model_id="local-model"))

    response = _discover(registry)

    assert response.default_provider_id == "local"
    assert [item.provider_id for item in response.providers] == ["local"]
    item = response.providers[0]
    assert item.is_default is True
    assert item.health.available is True
    assert item.health.status is ModelProviderHealthStatus.HEALTHY
    assert item.model_info.provider_name == "local"
    assert item.model_info.model_id == "local-model"


def test_discovery_marks_only_the_configured_default() -> None:
    """Exactly one provider is flagged default, matching the configured id."""
    registry = ModelProviderRegistry()
    registry.register("primary", DiscoveryProvider(provider_name="primary", model_id="p-model"))
    registry.register("local", DiscoveryProvider(provider_name="local", model_id="l-model"))

    response = _discover(registry, default_provider_id="local")

    assert response.default_provider_id == "local"
    assert [item.provider_id for item in response.providers] == ["primary", "local"]
    assert [item.is_default for item in response.providers] == [False, True]


def test_discovery_preserves_registry_insertion_order() -> None:
    """Providers are reported in registry insertion order."""
    registry = ModelProviderRegistry()
    registry.register("a", DiscoveryProvider(provider_name="a", model_id="a-model"))
    registry.register("b", DiscoveryProvider(provider_name="b", model_id="b-model"))
    registry.register("c", DiscoveryProvider(provider_name="c", model_id="c-model"))

    response = _discover(registry)

    assert [item.provider_id for item in response.providers] == ["a", "b", "c"]


def test_discovery_propagates_unhealthy_provider_report() -> None:
    """A provider's unhealthy report is passed through without alteration."""
    registry = ModelProviderRegistry()
    registry.register(
        "local",
        DiscoveryProvider(
            provider_name="local",
            model_id="local-model",
            health=ModelProviderHealth(
                available=False,
                status=ModelProviderHealthStatus.RUNTIME_UNAVAILABLE,
                message="runtime unreachable",
            ),
        ),
    )

    item = _discover(registry).providers[0]

    assert item.health.available is False
    assert item.health.status is ModelProviderHealthStatus.RUNTIME_UNAVAILABLE
    assert item.health.message == "runtime unreachable"


def test_discovery_isolates_failing_provider_health() -> None:
    """A raising health check becomes a sanitized report; others still return."""
    registry = ModelProviderRegistry()
    registry.register(
        "broken",
        DiscoveryProvider(
            provider_name="broken",
            model_id="broken-model",
            health_error=RuntimeError("secret transport detail"),
        ),
    )
    registry.register(
        "local",
        DiscoveryProvider(provider_name="local", model_id="healthy-model"),
    )

    response = _discover(registry)

    assert [item.provider_id for item in response.providers] == ["broken", "local"]
    broken, healthy = response.providers
    assert broken.health.available is False
    assert broken.health.status is ModelProviderHealthStatus.UNAVAILABLE
    assert broken.health.message == "Model provider health check failed"
    assert "secret transport detail" not in (broken.health.message or "")
    assert healthy.health.available is True
    assert healthy.health.status is ModelProviderHealthStatus.HEALTHY
    assert healthy.model_info.model_id == "healthy-model"


def test_discovery_reports_per_provider_model_info() -> None:
    """Each provider's model metadata comes from its own adapter."""
    registry = ModelProviderRegistry()
    registry.register("local", DiscoveryProvider(provider_name="local", model_id="model-xyz"))
    registry.register("gateway", DiscoveryProvider(provider_name="gateway", model_id="model-abc"))

    response = _discover(registry)

    infos = [(item.provider_id, item.model_info.model_id) for item in response.providers]
    assert infos == [("local", "model-xyz"), ("gateway", "model-abc")]


def test_discovery_empty_registry_is_truthful() -> None:
    """An empty registry yields no provider items and no fabricated default."""
    response = _discover(ModelProviderRegistry())

    assert response.providers == []
    assert response.default_provider_id == "local"


def test_discovery_unknown_configured_default_is_truthful_and_harmless() -> None:
    """An unknown default id is reported as-is; no provider is flagged default."""
    registry = ModelProviderRegistry()
    registry.register("local", DiscoveryProvider(provider_name="local", model_id="local-model"))

    response = _discover(registry, default_provider_id="corporate")

    assert response.default_provider_id == "corporate"
    assert response.providers  # other providers still discovered
    assert all(item.is_default is False for item in response.providers)


# ============================================================
# END: Discovery Service Tests
# ============================================================