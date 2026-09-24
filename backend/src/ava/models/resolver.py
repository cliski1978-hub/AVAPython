"""Model provider resolver.

Resolves a configured model provider id into the registered
``ModelProviderPort`` implementation through the ``ModelProviderRegistry``.

The resolver knows only AVA provider identities and AVA-owned abstractions. It
never imports vendor SDKs, constructs providers, registers providers, performs
health checks, or validates that a configured ``model_name`` exists. Provider
resolution and model selection are deliberately separate concerns (see the
Step 6 configuration); default selection belongs to configuration, never to
the resolver.
"""

from ava.models.contracts import ModelProviderPort
from ava.models.registry import ModelProviderRegistry

# ============================================================
# BEGIN: Unknown Model Provider Error
# ============================================================


class UnknownModelProviderError(ValueError):
    """Raised when a model provider id cannot be resolved to a provider.

    Explicit, AVA-owned failure for unknown or blank provider ids. Consistent
    with the repository's ``ValueError`` conventions for unknown domain ids
    while staying specializable. Carries only the unresolved provider id —
    never registry contents or implementation internals.
    """

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"Unknown model provider: {provider_id!r}")


# ============================================================
# END: Unknown Model Provider Error
# ============================================================


# ============================================================
# BEGIN: Model Provider Resolver
# ============================================================


class ModelProviderResolver:
    """Resolves a configured model provider id into a ``ModelProviderPort``.

    Depends on the registry only through composition; there is no global or
    hidden registry state.
    """

    def __init__(self, registry: ModelProviderRegistry) -> None:
        """Construct the resolver over the given provider registry.

        Args:
            registry: The AVA provider registry to resolve through.
        """
        self._registry = registry

    def resolve(self, provider_id: str) -> ModelProviderPort:
        """Resolve ``provider_id`` to its registered provider.

        Args:
            provider_id: The AVA provider identity to resolve. Blank ids are
                never remapped to a default here; default selection is
                configuration's job.

        Returns:
            The registered ``ModelProviderPort`` for ``provider_id``.

        Raises:
            UnknownModelProviderError: If the id is blank or not registered.
        """
        if not provider_id or not provider_id.strip():
            raise UnknownModelProviderError(provider_id)
        provider = self._registry.get(provider_id)
        if provider is None:
            raise UnknownModelProviderError(provider_id)
        return provider


# ============================================================
# END: Model Provider Resolver
# ============================================================