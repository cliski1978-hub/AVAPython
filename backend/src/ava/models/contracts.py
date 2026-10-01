"""Model provider adapter contracts (Ports).

AVA-owned, framework-neutral interfaces that future model providers
(local, company AI gateway, authorized external provider) must implement.

Provider SDK types must never escape adapters. Inputs and outputs use
AVA-owned contracts (see ava.contracts.models).
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelProviderHealth,
    ModelRequest,
    ModelResponse,
)

# ============================================================
# BEGIN: Model Provider Port
# ============================================================


class ModelProviderPort(ABC):
    """Port that all AVA model providers must implement.

    Providers integrate through adapters that translate between AVA contracts
    and provider SDK types. AVA Core never depends on vendor SDKs.
    """

    @abstractmethod
    def name(self) -> str:
        """Return the provider name."""
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> ModelProviderHealth:
        """Report whether the provider is reachable and healthy.

        Health checks may require I/O against a local runtime, a company
        gateway, or an external provider, so the method is asynchronous.
        """
        raise NotImplementedError

    @abstractmethod
    def get_model_info(self) -> ModelInfo:
        """Return AVA-owned information about the provider's model."""
        raise NotImplementedError

    @abstractmethod
    def get_capabilities(self) -> ModelCapabilities:
        """Return the normalized capabilities the provider's model supports.

        The result is an AVA-owned ``ModelCapabilities`` contract, not a set
        of ``CapabilityName`` values: ``CapabilityName`` describes application
        capabilities (health, runs, cancellations), while this method reports
        the provider's model capabilities (chat, streaming, tool calling, ...).
        """
        raise NotImplementedError

    @abstractmethod
    async def generate(
        self, request: ModelRequest, *, model_name: str | None = None
    ) -> ModelResponse:
        """Generate a model response from an AVA-owned request.

        Args:
            request: An AVA-owned ModelRequest contract.
            model_name: Optional provider-native model name to target. A provider
                must not own a single model; it sends the request to exactly the
                deployment named here. When omitted, the provider's configured
                bootstrap model name is used. Providers never choose a model.

        Returns:
            An AVA-owned ModelResponse contract.
        """
        raise NotImplementedError

    async def stream(
        self, request: ModelRequest, *, model_name: str | None = None
    ) -> AsyncIterator[str]:
        """Yield provider-originated text deltas.

        Providers without a streaming transport retain a truthful final-only
        fallback; streaming-capable adapters override this method.
        """
        response = await self.generate(request, model_name=model_name)
        if response.content:
            yield response.content


# ============================================================
# END: Model Provider Port
# ============================================================
