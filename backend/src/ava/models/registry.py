"""Model provider registry.

Central backend registry of available model providers. Providers register
under an AVA provider identity (e.g. ``mock``, ``local``, ``corporate``,
``external``); callers program against the ``ModelProviderPort`` abstraction
that a registered provider implements. The registry is a pure container: it
holds no provider logic and never imports vendor SDKs. Provider choice stays
a configuration decision resolved later (resolver step) through this registry.
"""

from ava.models.contracts import ModelProviderPort

# ============================================================
# BEGIN: Model Provider Registry
# ============================================================


class ModelProviderRegistry:
    """In-memory registry of model providers keyed by provider id."""

    def __init__(self) -> None:
        self._providers: dict[str, ModelProviderPort] = {}

    def register(self, provider_id: str, provider: ModelProviderPort) -> None:
        """Register a model provider under an AVA provider identity.

        Args:
            provider_id: The AVA identity for the provider (e.g. ``"mock"``).
                Provider ids are AVA identities, not framework classes.
            provider: The ``ModelProviderPort`` implementation to register.

        Raises:
            ValueError: If the provider id is empty/blank or already
                registered.
        """
        if not provider_id or not provider_id.strip():
            raise ValueError("Provider id must be a non-blank string")
        if provider_id in self._providers:
            raise ValueError(f"Provider already registered: {provider_id!r}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> ModelProviderPort | None:
        """Return the provider registered under ``provider_id``.

        Returns:
            The registered ``ModelProviderPort``, or ``None`` if no provider
            is registered under this id.
        """
        return self._providers.get(provider_id)

    def contains(self, provider_id: str) -> bool:
        """Return whether a provider is registered under ``provider_id``."""
        return provider_id in self._providers

    def list(self) -> list[str]:
        """Return the ids of all registered providers in insertion order."""
        return list(self._providers)


# ============================================================
# END: Model Provider Registry
# ============================================================
