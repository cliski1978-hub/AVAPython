"""Step 40: Model Registry v1 unit tests.

Prove the read-only catalog is truthful and closed:

- ``ModelProfile`` is the single authoritative configured-model record and
  carries no credential/permission/resource fields;
- ``ModelRegistry`` indexes by stable ``model_id`` in insertion order, is
  read-only over its profiles, allows an empty catalog, and fails fast on
  duplicate or blank identity;
- ``ModelBindingResolver`` derives execution bindings from the registry and
  enforces unknown/disabled/no-default failure rules without fallback.
"""

import dataclasses

import pytest

from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.models.bindings import (
    ModelBindingResolver,
    NoModelConfiguredForProviderError,
    model_binding_from_profile,
)
from ava.models.model_registry import (
    ModelDisabledError,
    ModelProfile,
    ModelRegistry,
    UnknownModelError,
)

_FORBIDDEN_PROFILE_FIELDS = {
    "api_key",
    "credential",
    "token",
    "endpoint",
    "base_url",
    "protocol",
    "permissions",
    "write",
    "network",
    "shell",
    "sandbox",
    "workspace",
    "cost",
    "latency",
    "resource_state",
    "gpu",
    "ram",
    "license",
    "qualification",
}


def _profile(model_id: str, provider_id: str = "p", *, enabled: bool = True) -> ModelProfile:
    return ModelProfile(
        model_id=model_id,
        display_name=model_id,
        provider_id=provider_id,
        provider_model_name=f"{model_id}-native",
        hosting_mode=ModelHostingMode.LOCAL,
        capabilities=ModelCapabilities(chat=True),
        enabled=enabled,
    )


# ============================================================
# BEGIN: Model Profile Tests
# ============================================================


def test_profile_is_frozen_and_minimal() -> None:
    profile = _profile("ava/one")
    assert dataclasses.is_dataclass(profile)
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.enabled = False  # type: ignore[misc]
    with pytest.raises(Exception, match="frozen"):
        profile.capabilities.chat = False


def test_profile_carries_no_credential_or_permission_fields() -> None:
    fields = set(ModelProfile.__dataclass_fields__)
    assert not (fields & _FORBIDDEN_PROFILE_FIELDS)
    assert fields == {
        "model_id",
        "display_name",
        "provider_id",
        "provider_model_name",
        "hosting_mode",
        "capabilities",
        "enabled",
    }


def test_profile_defaults_are_conservative() -> None:
    profile = ModelProfile(
        model_id="ava/one",
        display_name="One",
        provider_id="p",
        provider_model_name="native",
        hosting_mode=ModelHostingMode.LOCAL,
    )
    assert profile.enabled is True
    assert profile.capabilities == ModelCapabilities()


# ============================================================
# END: Model Profile Tests
# ============================================================


# ============================================================
# BEGIN: Registry Container Tests
# ============================================================


def test_registry_indexes_and_preserves_insertion_order() -> None:
    registry = ModelRegistry([_profile("z-last"), _profile("a-first"), _profile("m-middle")])
    assert registry.contains("a-first")
    assert registry.get("m-middle") is not None
    assert [p.model_id for p in registry.list()] == ["z-last", "a-first", "m-middle"]


def test_empty_registry_is_truthful() -> None:
    registry = ModelRegistry([])
    assert registry.list() == []
    assert registry.enabled_models() == []
    assert registry.get("anything") is None
    assert not registry.contains("anything")


def test_enabled_models_filters_disabled_profiles() -> None:
    registry = ModelRegistry(
        [_profile("ava/on"), _profile("ava/off", enabled=False), _profile("ava/on2")]
    )
    assert [p.model_id for p in registry.enabled_models()] == ["ava/on", "ava/on2"]
    assert [p.model_id for p in registry.list()] == ["ava/on", "ava/off", "ava/on2"]


def test_duplicate_model_id_fails_fast() -> None:
    with pytest.raises(ValueError):
        ModelRegistry([_profile("ava/one"), _profile("ava/one", provider_id="q")])


def test_blank_identity_fields_fail_fast() -> None:
    for field in ("model_id", "display_name", "provider_id", "provider_model_name"):
        kwargs = {
            "model_id": "ava/one",
            "display_name": "One",
            "provider_id": "p",
            "provider_model_name": "native",
            "hosting_mode": ModelHostingMode.LOCAL,
        }
        kwargs[field] = "   "
        with pytest.raises(ValueError):
            ModelRegistry([ModelProfile(**kwargs)])  # type: ignore[arg-type]


def test_provider_model_name_may_alias_across_identities() -> None:
    registry = ModelRegistry(
        [
            ModelProfile("ava/a", "A", "p", "same-native", ModelHostingMode.LOCAL),
            ModelProfile("ava/b", "B", "p", "same-native", ModelHostingMode.LOCAL),
        ]
    )
    assert len(registry.list()) == 2


# ============================================================
# END: Registry Container Tests
# ============================================================


# ============================================================
# BEGIN: Resolver Tests
# ============================================================


def test_resolver_requires_a_default_when_none_configured() -> None:
    with pytest.raises(ValueError):
        ModelBindingResolver(ModelRegistry([]))
    with pytest.raises(ValueError):
        ModelBindingResolver(ModelRegistry([_profile("ava/off", enabled=False)]))


def test_resolver_defaults_to_first_enabled_profile() -> None:
    resolver = ModelBindingResolver(ModelRegistry([_profile("ava/off", enabled=False), _profile("ava/on")]))
    assert resolver.default_profile().model_id == "ava/on"


def test_resolver_rejects_disabled_explicit_identity_without_fallback() -> None:
    resolver = ModelBindingResolver(ModelRegistry([_profile("ava/on"), _profile("ava/off", enabled=False)]))
    with pytest.raises(ModelDisabledError) as exc:
        resolver.resolve("ava/off")
    assert exc.value.reason == "model_disabled"
    assert exc.value.model_id == "ava/off"


def test_disabled_default_identity_fails_construction() -> None:
    with pytest.raises(ModelDisabledError):
        ModelBindingResolver(
            ModelRegistry([_profile("ava/on"), _profile("ava/off", enabled=False)]),
            default_model_id="ava/off",
        )


def test_provider_default_skips_disabled_and_raises_when_absent() -> None:
    resolver = ModelBindingResolver(
        ModelRegistry(
            [
                _profile("ava/off", "shared", enabled=False),
                _profile("ava/on", "shared"),
                _profile("ava/other", "other"),
            ]
        ),
        default_model_id="ava/on",
    )
    assert resolver.default_profile_for_provider("shared").model_id == "ava/on"
    assert resolver.default_for_provider("shared").model_id == "ava/on"
    with pytest.raises(NoModelConfiguredForProviderError):
        resolver.default_for_provider("unconfigured")
    with pytest.raises(NoModelConfiguredForProviderError):
        resolver.default_for_provider("missing")


def test_model_binding_from_profile_derives_execution_view() -> None:
    profile = _profile("ava/one")
    binding = model_binding_from_profile(profile)
    assert binding.model_id == profile.model_id
    assert binding.provider_id == profile.provider_id
    assert binding.provider_model_name == profile.provider_model_name
    assert binding.hosting_mode == profile.hosting_mode

    resolver = ModelBindingResolver(ModelRegistry([profile]), default_model_id=profile.model_id)
    assert resolver.default() == binding
    assert resolver.resolve(profile.model_id) == binding


def test_resolver_unknown_identity_is_empty_and_stable() -> None:
    resolver = ModelBindingResolver(ModelRegistry([_profile("ava/on")]), default_model_id="ava/on")
    with pytest.raises(UnknownModelError):
        resolver.resolve("nope")
    assert not resolver.contains("nope")
    assert resolver.list_model_ids() == ["ava/on"]


# ============================================================
# END: Resolver Tests
# ============================================================
