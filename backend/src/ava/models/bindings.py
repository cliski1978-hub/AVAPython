"""Internal model-identity bindings and their runtime bridge.

Step 38 separates two concepts that were previously conflated:

- the **stable AVA model identity** (``model_id``) — opaque, provider-neutral,
  configuration/debug friendly; and
- the **provider-native model name** (``provider_model_name``) — a
  deployment-specific string such as ``qwen3.5:9b-q4_K_M``.

Step 40 makes ``ModelRegistry``/``ModelProfile`` (``ava.models.model_registry``)
the single source of truth for configured models. ``ConfiguredModelBinding`` is
now a *derived execution view* of a ``ModelProfile`` (identity + hosting place)
and is never stored independently. ``ModelBindingResolver`` is a thin,
registry-backed adapter that turns a ``ModelProfile`` into that execution view
and owns the bootstrap default identity and the enabled/unknown failure rules.

``RuntimeModelBinding`` is the internal execution contract from AVA composition
to a runtime adapter. It carries identity plus the provider connection data a
runtime needs. It is never a public metadata object, and its credential field
(``api_key``) must never be serialized to clients.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ava.contracts.models import ModelHostingMode
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import (
    ModelDisabledError,
    ModelProfile,
    ModelRegistry,
    UnknownModelError,
)

# ============================================================
# BEGIN: Configured Model Binding
# ============================================================


@dataclass(frozen=True)
class ConfiguredModelBinding:
    """The execution-facing view of a configured model deployment.

    Derived from a ``ModelProfile`` via ``model_binding_from_profile``. It
    answers "for this AVA ``model_id``, which provider, which provider-native
    model name, and where does inference execute?" — never qualification,
    hardware, resource, permission, or routing data.

    ``hosting_mode`` is server-owned and explicit; it is never inferred from the
    ``provider_id``, the protocol, or the endpoint. The default is ``LOCAL``
    only to keep the legacy single-model bootstrap path working; production
    composition always sets it explicitly from the profile.
    """

    model_id: str
    provider_id: str
    provider_model_name: str
    hosting_mode: ModelHostingMode = ModelHostingMode.LOCAL


def model_binding_from_profile(profile: ModelProfile) -> ConfiguredModelBinding:
    """Derive the execution binding view from an authoritative profile."""
    return ConfiguredModelBinding(
        model_id=profile.model_id,
        provider_id=profile.provider_id,
        provider_model_name=profile.provider_model_name,
        hosting_mode=profile.hosting_mode,
    )


# ============================================================
# END: Configured Model Binding
# ============================================================


# ============================================================
# BEGIN: Model Binding Errors
# ============================================================


class NoModelConfiguredForProviderError(ValueError):
    """No enabled configured model binding references the requested provider.

    Separate from ``UnknownModelError`` so an explicit provider selection that
    has no configured model fails with an accurate reason.
    """

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"No configured model for provider: {provider_id!r}")


# ============================================================
# END: Model Binding Errors
# ============================================================


# ============================================================
# BEGIN: Model Binding Resolver
# ============================================================


class ModelBindingResolver:
    """Resolve registry profiles to execution bindings (registry-backed).

    A thin adapter over ``ModelRegistry``. The registry is the single source of
    truth; this class owns only the bootstrap *default* identity and the failure
    rules: an unknown explicit identity fails closed (``UnknownModelError``), a
    configured-but-disabled identity fails closed (``ModelDisabledError``), and
    neither ever falls back to the default.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        default_model_id: str | None = None,
        allow_unconfigured: bool = False,
    ) -> None:
        """Bind the resolver to a registry and validate the default identity.

        Args:
            registry: The authoritative configured-model catalog.
            default_model_id: The bootstrap default identity. When supplied it
                must resolve to an *enabled* configured profile. When omitted
                the first enabled profile is the default.

        Raises:
            ValueError: If no default identity can be established (empty
                registry or no enabled profiles).
            UnknownModelError: If ``default_model_id`` is not configured.
            ModelDisabledError: If ``default_model_id`` is configured disabled.
        """
        self._registry = registry
        self._default: ModelProfile | None = None
        if allow_unconfigured and not registry.list():
            return
        if default_model_id is not None:
            self._default = self._require(default_model_id)
            return
        enabled = registry.enabled_models()
        if not enabled:
            raise ValueError("At least one enabled model profile is required")
        self._default = enabled[0]

    def _require(self, model_id: str) -> ModelProfile:
        if not model_id or not model_id.strip():
            raise UnknownModelError(model_id)
        profile = self._registry.get(model_id)
        if profile is None:
            raise UnknownModelError(model_id)
        if not profile.enabled:
            raise ModelDisabledError(model_id)
        return profile

    def resolve_profile(self, model_id: str) -> ModelProfile:
        """Return the enabled profile for an explicit ``model_id``.

        Raises:
            UnknownModelError: If the identity is blank or not configured.
            ModelDisabledError: If the identity is configured but disabled. No
                fallback to the default, the first provider, or another model.
        """
        return self._require(model_id)

    def resolve(self, model_id: str) -> ConfiguredModelBinding:
        """Return the execution binding for an explicit ``model_id``."""
        return model_binding_from_profile(self.resolve_profile(model_id))

    def default_profile(self) -> ModelProfile:
        """Return the bootstrap default profile (no explicit identity given)."""
        if self._default is None:
            raise ValueError("No bootstrap model configured; configure execution defaults in Settings")
        return self._default

    def default(self) -> ConfiguredModelBinding:
        """Return the bootstrap default execution binding."""
        return model_binding_from_profile(self.default_profile())

    def default_profile_for_provider(self, provider_id: str) -> ModelProfile:
        """Return the first *enabled* configured profile for ``provider_id``.

        Supports the legacy provider-only selection path. Raises
        ``NoModelConfiguredForProviderError`` when the provider has no enabled
        binding; it never substitutes an unrelated model.
        """
        for profile in self._registry.enabled_models():
            if profile.provider_id == provider_id:
                return profile
        raise NoModelConfiguredForProviderError(provider_id)

    def default_for_provider(self, provider_id: str) -> ConfiguredModelBinding:
        """Return the execution binding for a provider's enabled default model."""
        return model_binding_from_profile(self.default_profile_for_provider(provider_id))

    def contains(self, model_id: str) -> bool:
        """Return whether an identity is configured (exact match)."""
        return self._registry.contains(model_id)

    def list_model_ids(self) -> list[str]:
        """Return configured stable identities in registry insertion order."""
        return [profile.model_id for profile in self._registry.list()]


# ============================================================
# END: Model Binding Resolver
# ============================================================


# ============================================================
# BEGIN: Runtime Model Binding
# ============================================================


@dataclass(frozen=True)
class RuntimeModelBinding:
    """Internal provider→runtime execution binding (identity + connection).

    Carries both the stable AVA identity (``model_id``) and the provider-native
    model name (``provider_model_name``), plus the connection data a runtime
    needs. INTERNAL ONLY: ``api_key`` is a credential and this object must never
    be exposed through a public contract, run response, ``ModelInfo``, or the
    frontend.
    """

    model_id: str
    provider_id: str
    provider_model_name: str
    protocol: str
    endpoint: str
    api_key: str | None = field(default=None, repr=False)


@runtime_checkable
class RuntimeModelBindingPort(Protocol):
    """A provider that can describe how a runtime should connect to it."""

    def create_runtime_model_binding(
        self, *, model_id: str, provider_id: str, provider_model_name: str
    ) -> RuntimeModelBinding: ...


class UnsupportedRuntimeModelBindingError(ValueError):
    """Selected provider cannot be represented for an external runtime."""


def bind_model_provider(provider: ModelProviderPort, binding: ConfiguredModelBinding) -> RuntimeModelBinding:
    """Bridge a stable AVA binding to an external runtime's model binding.

    The provider owns connection data (protocol, endpoint, credential); the
    binding owns identity. Resolution records the selected provider-native model
    name so the runtime targets exactly the requested deployment.
    """
    binder = provider if isinstance(provider, RuntimeModelBindingPort) else None
    if binder is None:
        raise UnsupportedRuntimeModelBindingError("Selected model provider does not support external runtime binding")
    return binder.create_runtime_model_binding(
        model_id=binding.model_id,
        provider_id=binding.provider_id,
        provider_model_name=binding.provider_model_name,
    )


# ============================================================
# END: Runtime Model Binding
# ============================================================


__all__ = [
    "ConfiguredModelBinding",
    "ModelBindingResolver",
    "ModelDisabledError",
    "NoModelConfiguredForProviderError",
    "RuntimeModelBinding",
    "RuntimeModelBindingPort",
    "UnknownModelError",
    "UnsupportedRuntimeModelBindingError",
    "bind_model_provider",
    "model_binding_from_profile",
]
