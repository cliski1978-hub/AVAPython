"""Step 39: hosting mode and model deployment classification.

These tests prove the deployment-placement seam:

- hosting modes are an explicit, closed set with defined semantics;
- a configured model binding carries its hosting mode independently of provider
  identity and model capabilities;
- legacy/local bootstrap defaults to ``LOCAL`` and configuration is strictly
  validated (unknown values fail, never silently inferred);
- a local-only placement requirement rejects a non-local binding *before* the
  provider executes, with no fallback and no public detail leak;
- hosting metadata grants no permissions and never appears on provider
  discovery/capability contracts.
"""

import asyncio

import pytest

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.configuration.settings import Settings
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
from ava.execution.compatibility import ExecutionCompatibilityValidator
from ava.execution.hosting import HostingReason, ModelHostingRequirement
from ava.execution.selector import ExecutionSelector
from ava.infrastructure.composition import (
    create_configured_model_profiles,
    create_model_registry,
)
from ava.models.bindings import ModelBindingResolver
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.registry import RuntimeRegistry
from ava.runtimes.resolver import RuntimeResolver

# ============================================================
# BEGIN: Hosting Mode Type Tests
# ============================================================


def test_hosting_mode_is_a_closed_three_value_set() -> None:
    assert {mode.value for mode in ModelHostingMode} == {"local", "company_hosted", "external"}
    assert len(list(ModelHostingMode)) == 3


def test_hosting_mode_is_not_a_model_capability_or_permission_field() -> None:
    # Step 40 supersedes the Step 39 assertion that hosting_mode was absent from
    # ModelInfo: the read-only catalog now exposes hosting placement as
    # descriptive metadata. It still grants no permissions, so it must never
    # appear on the capability contract.
    assert "hosting_mode" not in ModelCapabilities.model_fields
    assert "hosting_mode" in ModelInfo.model_fields


# ============================================================
# END: Hosting Mode Type Tests
# ============================================================


# ============================================================
# BEGIN: Hosting Requirement Tests
# ============================================================


def test_local_only_requirement_permits_only_local() -> None:
    requirement = ModelHostingRequirement.local_only()
    assert requirement.permits(ModelHostingMode.LOCAL)
    assert not requirement.permits(ModelHostingMode.COMPANY_HOSTED)
    assert not requirement.permits(ModelHostingMode.EXTERNAL)


def test_requirement_rejects_empty_allowed_modes() -> None:
    with pytest.raises(ValueError):
        ModelHostingRequirement(frozenset())


# ============================================================
# END: Hosting Requirement Tests
# ============================================================


# ============================================================
# BEGIN: Compatibility Validator Tests
# ============================================================


class _StubProvider(ModelProviderPort):
    def name(self) -> str:
        return "stub"

    async def health(self) -> ModelProviderHealth:
        return ModelProviderHealth(status=ModelProviderHealthStatus.HEALTHY, available=True)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id="stub-native",
            provider_name="stub",
            display_name="Stub",
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        return ModelResponse(content="ok", model_id=model_name or "stub-native")


def _validate(
    *,
    hosting_mode: ModelHostingMode | None,
    hosting_requirement: ModelHostingRequirement | None,
):
    return ExecutionCompatibilityValidator().validate(
        request=RunRequest(prompt="Hi"),
        runtime=NativeRuntime(),
        model_provider=_StubProvider(),
        hosting_mode=hosting_mode,
        hosting_requirement=hosting_requirement,
    )


def test_no_requirement_leaves_hosting_unconstrained() -> None:
    result = _validate(hosting_mode=ModelHostingMode.EXTERNAL, hosting_requirement=None)
    assert result.compatible


def test_requirement_rejects_disallowed_mode_with_stable_reason() -> None:
    result = _validate(
        hosting_mode=ModelHostingMode.EXTERNAL,
        hosting_requirement=ModelHostingRequirement.local_only(),
    )
    assert not result.compatible
    assert result.reasons == (HostingReason.MODE_NOT_ALLOWED.value,)


def test_requirement_fails_closed_when_classification_is_missing() -> None:
    result = _validate(
        hosting_mode=None,
        hosting_requirement=ModelHostingRequirement.local_only(),
    )
    assert not result.compatible
    assert result.reasons == (HostingReason.CLASSIFICATION_UNAVAILABLE.value,)


def test_requirement_permits_allowed_mode() -> None:
    result = _validate(
        hosting_mode=ModelHostingMode.LOCAL,
        hosting_requirement=ModelHostingRequirement.local_only(),
    )
    assert result.compatible


# ============================================================
# END: Compatibility Validator Tests
# ============================================================


# ============================================================
# BEGIN: Execution Gate Tests
# ============================================================


class _RecordingProvider(ModelProviderPort):
    def __init__(self) -> None:
        self.received_model_names: list[str | None] = []

    def name(self) -> str:
        return "shared"

    async def health(self) -> ModelProviderHealth:
        return ModelProviderHealth(status=ModelProviderHealthStatus.HEALTHY, available=True)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id="shared-native",
            provider_name="shared",
            display_name="Shared",
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
        self.received_model_names.append(model_name)
        return ModelResponse(content="ok", model_id=model_name or "shared-native")


def _local_only_agent() -> tuple[NativeAgentAdapter, _RecordingProvider]:
    provider = _RecordingProvider()
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
                    ModelProfile(
                        "ava/local",
                        "Local",
                        "shared",
                        "local-native",
                        ModelHostingMode.LOCAL,
                        capabilities=ModelCapabilities(chat=True),
                    ),
                    ModelProfile(
                        "ava/cloud",
                        "Cloud",
                        "shared",
                        "cloud-native",
                        ModelHostingMode.EXTERNAL,
                        capabilities=ModelCapabilities(chat=True),
                    ),
                ]
            ),
            default_model_id="ava/local",
        ),
        default_runtime_id="native",
        default_model_provider_id="shared",
        runtime_registry=runtime_registry,
        model_provider_registry=provider_registry,
    )
    return (
        NativeAgentAdapter(
            execution_selector=selector,
            hosting_requirement=ModelHostingRequirement.local_only(),
        ),
        provider,
    )


def test_local_only_agent_completes_on_local_binding_and_records_hosting_mode() -> None:
    async def scenario() -> None:
        agent, provider = _local_only_agent()
        result = await agent.start_run(
            "run", RunRequest(prompt="Hi", execution=RunExecutionOverride(model_id="ava/local"))
        )
        assert result.status == RunStatus.COMPLETED
        assert result.execution_selection is not None
        assert result.execution_selection.hosting_mode is ModelHostingMode.LOCAL
        assert provider.received_model_names == ["local-native"]

    asyncio.run(scenario())


def test_local_only_agent_fails_external_selection_without_executing() -> None:
    async def scenario() -> None:
        agent, provider = _local_only_agent()
        result = await agent.start_run(
            "run", RunRequest(prompt="Hi", execution=RunExecutionOverride(model_id="ava/cloud"))
        )
        assert result.status == RunStatus.FAILED
        assert result.content == "Selected execution configuration is not compatible"
        assert "hosting" not in (result.content or "").lower()
        assert provider.received_model_names == []

    asyncio.run(scenario())


# ============================================================
# END: Execution Gate Tests
# ============================================================


# ============================================================
# BEGIN: Configuration Tests
# ============================================================


def test_hosting_mode_defaults_to_local_when_unset() -> None:
    assert Settings().model_hosting_mode is ModelHostingMode.LOCAL


def test_hosting_mode_reads_strict_environment_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AVA_MODEL_HOSTING_MODE", raising=False)
    monkeypatch.setenv("AVA_MODEL_HOSTING_MODE", "company_hosted")
    assert Settings().model_hosting_mode is ModelHostingMode.COMPANY_HOSTED


def test_hosting_mode_accepts_case_insensitive_explicit_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AVA_MODEL_HOSTING_MODE", raising=False)
    monkeypatch.setenv("AVA_MODEL_HOSTING_MODE", "EXTERNAL")
    assert Settings().model_hosting_mode is ModelHostingMode.EXTERNAL


def test_unknown_hosting_mode_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AVA_MODEL_HOSTING_MODE", raising=False)
    monkeypatch.setenv("AVA_MODEL_HOSTING_MODE", "localhost")
    with pytest.raises(ValueError):
        Settings()


def test_blank_hosting_mode_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AVA_MODEL_HOSTING_MODE", raising=False)
    monkeypatch.setenv("AVA_MODEL_HOSTING_MODE", "   ")
    assert Settings().model_hosting_mode is ModelHostingMode.LOCAL


def test_composition_propagates_hosting_mode_to_the_binding() -> None:
    settings = Settings(
        model_provider="local",
        model_name="local-model",
        model_id="ava/default",
        model_hosting_mode=ModelHostingMode.EXTERNAL,
    )
    registry = create_model_registry(settings, profiles=create_configured_model_profiles(settings))
    resolver = ModelBindingResolver(registry, default_model_id=settings.resolved_model_id)
    assert resolver.default().hosting_mode is ModelHostingMode.EXTERNAL


# ============================================================
# END: Configuration Tests
# ============================================================
