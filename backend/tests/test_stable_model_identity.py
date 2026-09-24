"""Step 38/40: stable model identity, provider cardinality, registry resolution.

These tests exercise the real ``ModelProfile`` / ``ModelRegistry`` /
``ModelBindingResolver`` seams and the execution path that consumes them. They
prove:

- a stable AVA ``model_id`` is distinct from the provider-native model name and
  from the provider id;
- one provider object can serve multiple model profiles;
- the provider receives the explicitly selected provider-native name and never
  chooses the model itself;
- run metadata records the stable identity, not the provider-native name;
- an unknown or conflicting explicit identity fails cleanly with no fallback;
- the legacy single-model configuration still works unchanged.
"""

import asyncio

import pytest

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.contracts.execution import RunExecutionOverride
from ava.contracts.models import (
    ModelCapabilities,
    ModelHostingMode,
    ModelInfo,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.execution.selector import ExecutionSelector
from ava.models.bindings import (
    ConfiguredModelBinding,
    ModelBindingResolver,
    NoModelConfiguredForProviderError,
    UnknownModelError,
)
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.registry import RuntimeRegistry
from ava.runtimes.resolver import RuntimeResolver


def _profile(
    model_id: str,
    provider_id: str,
    provider_model_name: str,
    hosting_mode: ModelHostingMode = ModelHostingMode.LOCAL,
    *,
    enabled: bool = True,
) -> ModelProfile:
    return ModelProfile(
        model_id=model_id,
        display_name=model_id,
        provider_id=provider_id,
        provider_model_name=provider_model_name,
        hosting_mode=hosting_mode,
        capabilities=ModelCapabilities(chat=True),
        enabled=enabled,
    )


def _resolver(*profiles: ModelProfile, default: str | None = None) -> ModelBindingResolver:
    return ModelBindingResolver(ModelRegistry(profiles), default_model_id=default)


# ============================================================
# BEGIN: Binding Resolver Tests
# ============================================================


def test_binding_identity_is_distinct_from_native_name_and_provider() -> None:
    binding = ConfiguredModelBinding(
        model_id="ava/qwen-small", provider_id="local", provider_model_name="qwen3.5:9b-q4_K_M"
    )
    assert binding.model_id != binding.provider_model_name
    assert binding.model_id != binding.provider_id
    assert binding.provider_model_name != binding.provider_id


def test_configured_binding_carries_no_connection_or_credential_data() -> None:
    fields = set(ConfiguredModelBinding.__dataclass_fields__)
    assert fields == {"model_id", "provider_id", "provider_model_name", "hosting_mode"}
    assert not (fields & {"api_key", "endpoint", "protocol", "base_url"})


def test_hosting_mode_is_independent_of_provider_identity() -> None:
    resolver = _resolver(
        _profile("ava/local", "shared", "local-native", ModelHostingMode.LOCAL),
        _profile("ava/company", "shared", "company-native", ModelHostingMode.COMPANY_HOSTED),
        _profile("ava/cloud", "shared", "cloud-native", ModelHostingMode.EXTERNAL),
        default="ava/local",
    )
    assert resolver.resolve("ava/local").hosting_mode is ModelHostingMode.LOCAL
    assert resolver.resolve("ava/company").hosting_mode is ModelHostingMode.COMPANY_HOSTED
    assert resolver.resolve("ava/cloud").hosting_mode is ModelHostingMode.EXTERNAL
    assert resolver.default_for_provider("shared").provider_id == "shared"


def test_one_provider_serves_multiple_model_bindings() -> None:
    resolver = ModelBindingResolver(
        ModelRegistry(
            [
                _profile("ava/small", "shared", "small-native"),
                _profile("ava/large", "shared", "large-native"),
                _profile("ava/remote", "other", "remote-native"),
            ]
        ),
        default_model_id="ava/small",
    )
    assert resolver.list_model_ids() == ["ava/small", "ava/large", "ava/remote"]
    assert resolver.default() == ConfiguredModelBinding("ava/small", "shared", "small-native")
    assert resolver.resolve("ava/large").provider_model_name == "large-native"
    assert resolver.default_for_provider("shared").model_id == "ava/small"
    assert resolver.resolve("ava/remote").provider_id == "other"


def test_unknown_explicit_identity_never_falls_back_to_default() -> None:
    resolver = _resolver(_profile("ava/one", "p", "native-one"))
    with pytest.raises(UnknownModelError):
        resolver.resolve("does-not-exist")
    with pytest.raises(UnknownModelError):
        resolver.resolve("")
    assert not resolver.contains("does-not-exist")
    assert resolver.contains("ava/one")


def test_default_identity_must_be_configured_when_supplied() -> None:
    with pytest.raises(UnknownModelError):
        ModelBindingResolver(
            ModelRegistry([_profile("ava/one", "p", "native-one")]), default_model_id="missing"
        )


def test_registry_rejects_duplicate_and_blank_profiles() -> None:
    with pytest.raises(ValueError):
        ModelRegistry([_profile("ava/one", "p", "n"), _profile("ava/one", "q", "m")])
    with pytest.raises(ValueError):
        ModelRegistry([_profile("  ", "p", "n")])
    with pytest.raises(ValueError):
        ModelRegistry([_profile("ava/one", " ", "n")])
    with pytest.raises(ValueError):
        ModelRegistry(
            [
                ModelProfile(
                    model_id="ava/one",
                    display_name="One",
                    provider_id="p",
                    provider_model_name="",
                    hosting_mode=ModelHostingMode.LOCAL,
                )
            ]
        )


def test_missing_provider_binding_fails_with_provider_specific_error() -> None:
    resolver = _resolver(_profile("ava/one", "p", "native-one"))
    with pytest.raises(NoModelConfiguredForProviderError):
        resolver.default_for_provider("unconfigured")


# ============================================================
# END: Binding Resolver Tests
# ============================================================


# ============================================================
# BEGIN: Execution Selection Tests
# ============================================================


class _RecordingProvider(ModelProviderPort):
    """Provider that records the provider-native name it is asked to run."""

    def __init__(self, provider_name: str, model_id: str) -> None:
        self._provider_name = provider_name
        self._model_id = model_id
        self.received_model_names: list[str | None] = []

    def name(self) -> str:
        return self._provider_name

    async def health(self) -> ModelProviderHealth:
        return ModelProviderHealth(status=ModelProviderHealthStatus.HEALTHY, available=True)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._model_id,
            provider_name=self._provider_name,
            display_name=self._provider_name,
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        self.received_model_names.append(model_name)
        return ModelResponse(content="ok", model_id=model_name or self._model_id)


def _shared_provider_agent() -> tuple[NativeAgentAdapter, _RecordingProvider]:
    """One provider, two configured models, composed through the real selector."""
    provider = _RecordingProvider("shared", "shared-native")
    provider_registry = ModelProviderRegistry()
    provider_registry.register("shared", provider)
    runtime_registry = RuntimeRegistry()
    runtime_registry.register("native", NativeRuntime())
    selector = ExecutionSelector(
        runtime_resolver=RuntimeResolver(runtime_registry),
        model_provider_resolver=ModelProviderResolver(provider_registry),
        model_binding_resolver=ModelBindingResolver(
            ModelRegistry(
                [
                    _profile("ava/small", "shared", "small-native"),
                    _profile("ava/large", "shared", "large-native"),
                ]
            ),
            default_model_id="ava/small",
        ),
        default_runtime_id="native",
        default_model_provider_id="shared",
        runtime_registry=runtime_registry,
        model_provider_registry=provider_registry,
    )
    return NativeAgentAdapter(execution_selector=selector), provider


def test_explicit_model_id_selects_binding_and_provider_native_name() -> None:
    async def scenario() -> None:
        agent, provider = _shared_provider_agent()
        result = await agent.start_run(
            "run", RunRequest(prompt="Hi", execution=RunExecutionOverride(model_id="ava/large"))
        )
        assert result.status == RunStatus.COMPLETED
        assert result.execution_selection is not None
        assert result.execution_selection.model_id == "ava/large"
        assert result.execution_selection.model_provider_id == "shared"
        assert provider.received_model_names == ["large-native"]

    asyncio.run(scenario())


def test_provider_only_selection_binds_that_providers_default_model() -> None:
    async def scenario() -> None:
        agent, provider = _shared_provider_agent()
        result = await agent.start_run(
            "run", RunRequest(prompt="Hi", execution=RunExecutionOverride(model_provider_id="shared"))
        )
        assert result.status == RunStatus.COMPLETED
        assert result.execution_selection is not None
        assert result.execution_selection.model_id == "ava/small"
        assert provider.received_model_names == ["small-native"]

    asyncio.run(scenario())


def test_unknown_explicit_model_id_fails_without_executing() -> None:
    async def scenario() -> None:
        agent, provider = _shared_provider_agent()
        result = await agent.start_run(
            "run", RunRequest(prompt="Hi", execution=RunExecutionOverride(model_id="unknown/model"))
        )
        assert result.status == RunStatus.FAILED
        assert result.content == "Requested execution unavailable"
        assert provider.received_model_names == []

    asyncio.run(scenario())


def test_conflicting_model_and_provider_ids_fail_cleanly() -> None:
    async def scenario() -> None:
        agent, provider = _shared_provider_agent()
        result = await agent.start_run(
            "run",
            RunRequest(
                prompt="Hi",
                execution=RunExecutionOverride(model_id="ava/small", model_provider_id="other"),
            ),
        )
        assert result.status == RunStatus.FAILED
        assert result.content == "Requested execution unavailable"
        assert provider.received_model_names == []

    asyncio.run(scenario())


def test_auto_mode_rejects_explicit_model_identity() -> None:
    async def scenario() -> None:
        agent, provider = _shared_provider_agent()
        result = await agent.start_run(
            "run", RunRequest(prompt="Hi", execution=RunExecutionOverride(mode="auto", model_id="ava/small"))
        )
        assert result.status == RunStatus.FAILED
        assert provider.received_model_names == []

    asyncio.run(scenario())


# ============================================================
# END: Execution Selection Tests
# ============================================================


# ============================================================
# BEGIN: Legacy Bootstrap Tests
# ============================================================


def test_legacy_single_model_settings_still_compose_one_binding() -> None:
    from ava.configuration.settings import Settings
    from ava.infrastructure.composition import (
        create_configured_model_profiles,
        create_model_registry,
    )

    settings = Settings(model_provider="local", model_name="local-model", model_id="")
    registry = create_model_registry(settings, profiles=create_configured_model_profiles(settings))
    resolver = ModelBindingResolver(registry, default_model_id=settings.resolved_model_id)
    binding = resolver.default()
    assert binding.provider_id == "local"
    assert binding.provider_model_name == "local-model"
    assert binding.model_id == "local-local-model"
    assert resolver.resolve("local-local-model") == binding


def test_explicit_model_id_setting_overrides_derived_identity() -> None:
    from ava.configuration.settings import Settings

    settings = Settings(model_provider="local", model_name="local-model", model_id="ava/default")
    assert settings.resolved_model_id == "ava/default"
    assert Settings(model_provider="local", model_name="m", model_id="   ").resolved_model_id == "local-m"


# ============================================================
# END: Legacy Bootstrap Tests
# ============================================================
