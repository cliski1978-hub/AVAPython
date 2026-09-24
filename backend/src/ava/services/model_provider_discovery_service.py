"""Model provider discovery service.

Answers "what model providers are available, and are they healthy?" entirely
through the ``ModelProviderPort`` abstraction — never a concrete provider. The
service depends only on the ``ModelProviderRegistry`` (a pure container), the
port, and AVA contracts; it does not import adapters, HTTP clients,
configuration, agent layers, or runtime frameworks.

The configured default provider id is supplied at composition, never derived
here. It is reported truthfully in the response even when nothing is
registered under it (an unknown or unregistered default never fabricates an
entry and never fails discovery).
"""

import logging

from ava.contracts.models import ModelProviderHealth, ModelProviderHealthStatus
from ava.contracts.responses import (
    ModelProviderDiscoveryItem,
    ModelProviderDiscoveryResponse,
)
from ava.models.contracts import ModelProviderPort
from ava.models.registry import ModelProviderRegistry

logger = logging.getLogger(__name__)

# ============================================================
# BEGIN: Model Provider Discovery Service
# ============================================================


class ModelProviderDiscoveryService:
    """Enumerate registered model providers with model info and health."""

    def __init__(
        self,
        *,
        registry: ModelProviderRegistry,
        default_provider_id: str,
    ) -> None:
        """Construct the discovery service over the application's registry.

        Args:
            registry: The application's ``ModelProviderRegistry``. The service
                reads it through its public surface (``list()`` / ``get()``)
                and never inspects or mutates registry internals.
            default_provider_id: The configured default provider identity
                (e.g. ``Settings.model_provider``). Decided at composition;
                the service neither reads configuration nor knows which ids
                are special.
        """
        self._registry = registry
        self._default_provider_id = default_provider_id

    async def discover(self) -> ModelProviderDiscoveryResponse:
        """Build a discovery snapshot over the registered providers.

        Providers are enumerated in registry insertion order. Health checks
        run sequentially per provider; a failing provider is isolated so the
        remaining providers are still reported.

        Returns:
            A ``ModelProviderDiscoveryResponse`` carrying the configured
            default provider id and one item per registered provider.
        """
        providers: list[ModelProviderDiscoveryItem] = []
        for provider_id in self._registry.list():
            provider = self._registry.get(provider_id)
            if provider is None:
                continue
            providers.append(
                ModelProviderDiscoveryItem(
                    provider_id=provider_id,
                    is_default=provider_id == self._default_provider_id,
                    model_info=provider.get_model_info(),
                    health=await self._probe(provider),
                )
            )
        return ModelProviderDiscoveryResponse(
            default_provider_id=self._default_provider_id,
            providers=providers,
        )

    async def _probe(self, provider: ModelProviderPort) -> ModelProviderHealth:
        """Return ``provider.health()``, sanitized at the AVA boundary.

        ``health()`` normally never raises (adapters return a
        ``ModelProviderHealth``), but a third-party port implementation may
        fail. A bare ``except Exception`` here is the isolation boundary: raw
        exceptions must never escape discovery, and clients must only ever see
        an AVA-owned, sanitized report.
        """
        try:
            return await provider.health()
        except Exception:
            logger.exception("Model provider health check failed for %r", provider.name())
            return ModelProviderHealth(
                available=False,
                status=ModelProviderHealthStatus.UNAVAILABLE,
                message="Model provider health check failed",
            )


# ============================================================
# END: Model Provider Discovery Service
# ============================================================