"""Model provider adapter contracts (Ports).

AVA-owned, framework-neutral interfaces that future model providers
(local, company AI gateway, authorized external provider) must implement.

Provider SDK types must never escape adapters. Inputs and outputs use
AVA-owned contracts (see ava.contracts.models).
"""

from abc import ABC, abstractmethod

from ava.contracts.capabilities import CapabilityName
from ava.contracts.models import (
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
    def get_capabilities(self) -> set[CapabilityName]:
        """Return the capabilities the provider actually supports."""
        raise NotImplementedError

    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate a model response from an AVA-owned request.

        Args:
            request: An AVA-owned ModelRequest contract.

        Returns:
            An AVA-owned ModelResponse contract.
        """
        raise NotImplementedError


# ============================================================
# END: Model Provider Port
# ============================================================