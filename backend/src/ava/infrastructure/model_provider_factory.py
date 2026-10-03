"""Concrete provider adapter construction for configured connections.

Phase 5.16 needs a *new* ``ModelProviderPort`` for each resolved connection,
which the single startup instance in ``ModelProviderRegistry`` cannot supply: it
is already bound to one endpoint and one credential. Constructing an adapter per
resolution has one real hazard — an adapter that creates its own
``httpx.AsyncClient`` would leak a connection pool on every run — so this
module's factory owns one shared client for the application's lifetime and
injects it into every adapter it builds. That is also what the adapter's own
contract expects: an injected client is never closed by the adapter, so the
factory is the single place pooled connections are released.

Built-in constructor support is independent of the selected environment
provider. The registry can additionally contribute compatible adapter aliases;
unrelated protocols require their own factory implementation. Bootstrap and
persisted connections use the same construction function.
"""

from __future__ import annotations

import logging

import httpx

from ava.contracts.models import ModelCapabilities
from ava.models.contracts import ModelProviderPort
from ava.models.credentials import SecretValue
from ava.models.provider_factory import ModelProviderFactory, UnknownProviderAdapterError
from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider, _base_url_config_valid
from ava.models.registry import ModelProviderRegistry

logger = logging.getLogger(__name__)

# Installed constructor support is independent of the selected legacy default.
BUILTIN_PROVIDER_IDS = frozenset({"local"})

# Persisted connections share a factory-owned client.  HTTPX's implicit client
# timeout is five seconds, which is too short for a healthy local model's first
# streamed token while it is loading or evaluating a substantial context.  Keep
# every timeout finite, but give a stream a realistic idle-read window.
_CONFIGURED_PROVIDER_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=120.0,
    write=30.0,
    pool=30.0,
)


def bootstrap_provider_config_valid(provider_id: str, endpoint: str) -> bool:
    """Reuse the adapter's structural check; never probe a server at startup."""
    try:
        return provider_id in BUILTIN_PROVIDER_IDS and _base_url_config_valid(endpoint.strip())
    except ValueError:
        return False


def construct_compatible_provider(
    *,
    provider_id: str,
    endpoint: str,
    model_name: str,
    credential: SecretValue | None = None,
    http_client: httpx.AsyncClient | None = None,
    capabilities: ModelCapabilities | None = None,
) -> OpenAICompatibleModelProvider:
    """Single construction boundary shared by bootstrap and persisted flows.

    ``capabilities`` is threaded all the way to the adapter because the adapter
    is what answers "can this model stream?". An adapter constructed without it
    reports chat-only, and the runtime then completes the run in one shot.
    """
    return OpenAICompatibleModelProvider(
        base_url=endpoint,
        model_name=model_name,
        provider_name=provider_id,
        api_key=credential.reveal() if credential is not None else None,
        http_client=http_client,
        capabilities=capabilities,
    )


class ConfiguredModelProviderFactory(ModelProviderFactory):
    """Build model provider adapters for configured connections.

    One instance is composed per application and reused for every resolution, so
    every adapter it builds shares one connection pool. It also owns that pool's
    shutdown via :meth:`aclose`, called from the application lifespan.

    Args:
        installed_provider_ids: The provider adapter types this deployment
            installs, supplied by composition from built-ins and compatible aliases. A connection naming
            anything else is reported as an uninstalled adapter.
        default_endpoint: The deployment's configured default endpoint, used only
            when a connection declares no endpoint of its own. Passed through
            unchanged; no URL parsing, normalization, or validation happens here.
        http_client: Optional pre-built client to share instead of creating one.
            An injected client is never closed by this factory.
    """

    def __init__(
        self,
        *,
        installed_provider_ids: frozenset[str],
        default_endpoint: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._installed = installed_provider_ids
        self._default_endpoint = default_endpoint
        self._http_client = http_client or httpx.AsyncClient(timeout=_CONFIGURED_PROVIDER_TIMEOUT)
        self._owns_http_client = http_client is None

    def create(
        self,
        *,
        provider_id: str,
        endpoint: str | None,
        model_name: str,
        credential: SecretValue | None,
        capabilities: ModelCapabilities | None = None,
    ) -> ModelProviderPort:
        """Construct one adapter for one connection.

        The credential is revealed here and nowhere else: this is the boundary
        where a resolved secret becomes a provider's authentication header. The
        plaintext goes straight into the adapter and is not retained, so the
        factory's own state never holds a secret.
        """
        if provider_id not in self._installed:
            raise UnknownProviderAdapterError(provider_id)
        return construct_compatible_provider(
            endpoint=endpoint if endpoint is not None else self._default_endpoint,
            model_name=model_name,
            provider_id=provider_id,
            credential=credential,
            http_client=self._http_client,
            capabilities=capabilities,
        )

    async def aclose(self) -> None:
        """Release the shared HTTP client during application shutdown.

        A no-op once closed, and a no-op for an injected client, which belongs to
        whoever injected it. Adapters built by this factory share the client and
        never close it themselves, so this is the only place pooled connections
        are released.
        """
        if self._owns_http_client:
            await self._http_client.aclose()
            self._owns_http_client = False
            logger.debug("Closed shared model provider HTTP client")


def installed_provider_adapter_ids(registry: ModelProviderRegistry) -> frozenset[str]:
    """The provider adapter types a deployment has installed.

    Read from the registry rather than re-derived from settings, so the set of
    adapter types reported by discovery and the set this factory serves can
    never disagree. An empty registry yields an empty set, which makes every
    configured connection fail as an uninstalled adapter instead of being served
    by whatever happens to be available.
    """
    # A different registered port must never be reinterpreted as this protocol.
    return frozenset(
        provider_id
        for provider_id in registry.list()
        if isinstance(registry.get(provider_id), OpenAICompatibleModelProvider)
    )
