"""AVA models package.

Future model providers must implement an AVA-owned model-provider contract.
The ``ModelProviderRegistry`` is the central container of registered
providers, and ``ModelProviderResolver`` turns a configured provider id into
the registered port through the registry.

``ModelRegistry`` (Step 40) is the read-only catalog of configured
``ModelProfile``s keyed by the stable AVA ``model_id`` (Step 38). It is the
single source of truth for configured models. ``ava.models.bindings`` derives
execution bindings from a profile via a thin ``ModelBindingResolver``.

Provider identity (``provider_id → provider implementation``) and model
identity (``model_id → model deployment metadata``) stay separate registries.
"""

from ava.models.bindings import (
    ConfiguredModelBinding,
    ModelBindingResolver,
    NoModelConfiguredForProviderError,
    RuntimeModelBinding,
    RuntimeModelBindingPort,
    UnknownModelError,
    UnsupportedRuntimeModelBindingError,
    bind_model_provider,
    model_binding_from_profile,
)
from ava.models.model_registry import (
    ModelDisabledError,
    ModelProfile,
    ModelRegistry,
)
from ava.models.provider_connections import ProviderConnection
from ava.models.qualifications import ModelQualification, ModelQualificationStore
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver, UnknownModelProviderError

__all__ = [
    "ConfiguredModelBinding",
    "ModelBindingResolver",
    "ModelDisabledError",
    "ModelProfile",
    "ModelProviderRegistry",
    "ModelProviderResolver",
    "ProviderConnection",
    "ModelRegistry",
    "ModelQualification",
    "ModelQualificationStore",
    "NoModelConfiguredForProviderError",
    "RuntimeModelBinding",
    "RuntimeModelBindingPort",
    "UnknownModelError",
    "UnknownModelProviderError",
    "UnsupportedRuntimeModelBindingError",
    "bind_model_provider",
    "model_binding_from_profile",
]
