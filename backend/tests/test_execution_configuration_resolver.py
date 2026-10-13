"""Phase 5.16: persisted configuration joins, policy, credentials and authority."""

import asyncio
import logging
import traceback
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from ava.configuration.execution_defaults import ApplicationExecutionDefaults
from ava.configuration.settings import Settings
from ava.contracts.execution import RunExecutionOverride
from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.execution.hosting import ModelHostingRequirement
from ava.execution.persisted_execution import (
    ConfiguredModelIneligibleError,
    ConfiguredReferenceDisabledError,
    ConfiguredReferenceMissingError,
    CredentialResolutionFailedError,
    ExecutionConfigurationSource,
    ExecutionDefaultsNotConfiguredError,
    ModelProviderMismatchError,
    ProviderAdapterNotRegisteredError,
    ProviderConstructionFailedError,
    RuntimeAdapterNotRegisteredError,
)
from ava.execution.selector import ExecutionSelector, ResolvedExecution
from ava.infrastructure.composition import (
    create_application_persistence,
    create_execution_configuration_resolver,
    create_model_orchestrator,
    create_model_qualification_store,
    create_model_registry,
    create_runtime_registry,
)
from ava.infrastructure.credentials import EnvironmentCredentialResolver
from ava.infrastructure.model_provider_factory import ConfiguredModelProviderFactory
from ava.models.bindings import ModelBindingResolver, bind_model_provider, model_binding_from_profile
from ava.models.credentials import CredentialError
from ava.models.model_configurations import ModelConfiguration
from ava.models.provider_connections import ProviderConnection
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.runtimes.configurations import RuntimeConfiguration
from ava.runtimes.resolver import RuntimeResolver

SECRET = "phase516-private-key-not-for-output"


@pytest.fixture(params=["memory", "relational"])
def setup(request: pytest.FixtureRequest, tmp_path: Path):
    settings = Settings(
        persistence_provider=request.param,
        persistence_database_url=str(tmp_path / "settings.sqlite3"),
        attachment_storage="memory",
        model_provider="local",
        model_name="bootstrap-native",
        model_id="bootstrap-model",
    )
    persistence = create_application_persistence(settings)
    connection = ProviderConnection("configured-connection", "local", "Gateway", "https://gateway.test/v1")
    model = ModelConfiguration(
        "configured-model",
        connection.provider_connection_id,
        "vendor/deployment",
        "Configured model",
        ModelHostingMode.COMPANY_HOSTED,
        ModelCapabilities(chat=True, tool_calling=True),
    )
    runtime = RuntimeConfiguration("configured-runtime", "native", "Configured runtime")
    persistence.provider_connection_repository.create(connection)
    persistence.model_configuration_repository.create(model)
    persistence.runtime_configuration_repository.create(runtime)
    defaults = ApplicationExecutionDefaults(
        connection.provider_connection_id, model.model_id, runtime.runtime_configuration_id
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("resolution must not perform HTTP")))
    factory = ConfiguredModelProviderFactory(
        installed_provider_ids=frozenset({"local"}),
        default_endpoint="https://bootstrap.test/v1",
        http_client=client,
    )
    registry = create_runtime_registry()
    models = create_model_registry(settings)
    orchestrator = create_model_orchestrator(
        models, create_model_qualification_store(models), default_model_id=settings.resolved_model_id
    )
    environment: dict[str, str] = {}
    credentials = EnvironmentCredentialResolver(environment)
    resolver = create_execution_configuration_resolver(
        persistence,
        runtime_resolver=RuntimeResolver(registry),
        provider_factory=factory,
        credential_resolver=credentials,
        model_orchestrator=orchestrator,
    )
    bootstrap_provider = factory.create(
        provider_id="local", endpoint=None, model_name=settings.model_name, credential=None
    )
    providers = ModelProviderRegistry()
    providers.register("local", bootstrap_provider)
    selector = ExecutionSelector(
        runtime_resolver=RuntimeResolver(registry),
        model_provider_resolver=ModelProviderResolver(providers),
        model_binding_resolver=ModelBindingResolver(models, default_model_id=settings.resolved_model_id),
        default_runtime_id="native",
        default_model_provider_id="local",
        model_orchestrator=orchestrator,
        persisted_configuration_resolver=resolver,
    )
    yield {
        "persistence": persistence,
        "connection": connection,
        "model": model,
        "runtime": runtime,
        "defaults": defaults,
        "resolver": resolver,
        "registry": registry,
        "models": models,
        "factory": factory,
        "credentials": credentials,
        "environment": environment,
        "orchestrator": orchestrator,
        "selector": selector,
    }
    persistence.dispose()
    asyncio.run(client.aclose())


def save_defaults(setup):
    setup["persistence"].execution_defaults_repository.set(setup["defaults"])


def test_absence_is_the_only_bootstrap_fallback(setup):
    assert setup["resolver"].resolve_persisted() is None
    with pytest.raises(ExecutionDefaultsNotConfiguredError):
        setup["resolver"].resolve_required()
    result = setup["selector"].resolve()
    assert result.source is ExecutionConfigurationSource.BOOTSTRAP
    assert result.model_binding.model_id == "bootstrap-model"
    assert result.provider_connection_id is None


@pytest.mark.parametrize("override", [None, RunExecutionOverride()])
def test_valid_defaults_override_bootstrap_and_use_existing_abstractions(setup, monkeypatch, override):
    save_defaults(setup)
    calls = []
    select = setup["orchestrator"].select

    def observe(request, **kwargs):
        decision = select(request, **kwargs)
        calls.append(decision)
        return decision

    monkeypatch.setattr(setup["orchestrator"], "select", observe)
    result = setup["selector"].resolve(override)
    assert result.source is ExecutionConfigurationSource.PERSISTED
    assert result.model_binding == model_binding_from_profile(result.model_profile)
    assert result.model_profile.capabilities == setup["model"].capabilities
    assert result.model_profile.hosting_mode is ModelHostingMode.COMPANY_HOSTED
    assert result.model_profile.provider_id == "local"
    assert result.model_binding.provider_model_name == "vendor/deployment"
    assert result.model_binding.model_id == "configured-model"
    assert result.runtime is setup["registry"].get("native")
    assert result.runtime_configuration_id == "configured-runtime"
    assert result.provider_connection_id == "configured-connection"
    assert calls[0].model_id == "configured-model"
    assert len(calls) == 1
    assert setup["models"].get("configured-model") is None  # no shared catalog mutation
    binding = bind_model_provider(result.model_provider, result.model_binding)
    assert binding.endpoint == "https://gateway.test/v1"
    assert binding.api_key is None


@pytest.mark.parametrize(
    "domain,kind",
    [
        ("provider_connection", "provider connection"),
        ("model_configuration", "model configuration"),
        ("runtime_configuration", "runtime configuration"),
    ],
)
def test_missing_reference_is_distinct_and_never_falls_back(setup, monkeypatch, domain, kind):
    save_defaults(setup)
    monkeypatch.setattr(getattr(setup["persistence"], domain + "_repository"), "get", lambda _: None)
    with pytest.raises(ConfiguredReferenceMissingError) as error:
        setup["selector"].resolve()
    assert error.value.kind == kind


@pytest.mark.parametrize(
    "domain,record",
    [
        ("provider_connection", "connection"),
        ("model_configuration", "model"),
        ("runtime_configuration", "runtime"),
    ],
)
@pytest.mark.parametrize("override", [None, RunExecutionOverride(runtime_id="native")])
def test_disable_after_save_rejected_even_with_legacy_override(setup, domain, record, override):
    save_defaults(setup)
    getattr(setup["persistence"], domain + "_repository").update(replace(setup[record], enabled=False))
    with pytest.raises(ConfiguredReferenceDisabledError):
        setup["selector"].resolve(override)


def test_inconsistent_restored_defaults_rejected(setup, monkeypatch):
    save_defaults(setup)
    other = replace(setup["connection"], provider_connection_id="other-connection")
    setup["persistence"].provider_connection_repository.create(other)
    bad = replace(setup["defaults"], default_provider_connection_id="other-connection")
    monkeypatch.setattr(setup["persistence"].execution_defaults_repository, "get", lambda: bad)
    with pytest.raises(ModelProviderMismatchError):
        setup["selector"].resolve()


def test_missing_adapter_not_confused_with_missing_runtime_record(setup, monkeypatch):
    save_defaults(setup)
    runtime = replace(setup["runtime"], runtime_type="not-installed")
    monkeypatch.setattr(setup["persistence"].runtime_configuration_repository, "get", lambda _: runtime)
    with pytest.raises(RuntimeAdapterNotRegisteredError) as error:
        setup["selector"].resolve()
    assert error.value.runtime_configuration_id == "configured-runtime"
    assert error.value.runtime_type == "not-installed"


def test_unknown_provider_adapter_fails_without_substitution(setup, monkeypatch):
    save_defaults(setup)
    connection = replace(setup["connection"], provider_id="not-installed")
    monkeypatch.setattr(setup["persistence"].provider_connection_repository, "get", lambda _: connection)
    with pytest.raises(ProviderAdapterNotRegisteredError):
        setup["selector"].resolve()


def test_credential_free_connection_does_not_resolve_a_secret(setup, monkeypatch):
    save_defaults(setup)
    resolve = Mock(side_effect=AssertionError("must not resolve"))
    monkeypatch.setattr(setup["credentials"], "resolve", resolve)
    setup["resolver"].resolve_required()
    resolve.assert_not_called()


def test_credential_rotates_per_execution_and_repr_is_safe(setup, monkeypatch, caplog):
    save_defaults(setup)
    setup["persistence"].provider_connection_repository.update(
        replace(setup["connection"], credential_reference="env:AVA_TEST_KEY")
    )
    setup["environment"]["AVA_TEST_KEY"] = SECRET
    caplog.set_level(logging.DEBUG)
    first = setup["resolver"].resolve_required()
    first_binding = bind_model_provider(first.model_provider, first.model_binding)
    assert first_binding.api_key == SECRET
    # Even an adapter with a poor repr cannot leak through either result.
    monkeypatch.setattr(type(first.model_provider), "__repr__", lambda _: SECRET)
    assert SECRET not in repr(first)
    assert SECRET not in repr(ResolvedExecution.from_persisted_configuration(first))
    assert SECRET not in repr(first_binding)
    setup["environment"]["AVA_TEST_KEY"] = "rotated-" + SECRET
    second = setup["resolver"].resolve_required()
    assert second.model_provider is not first.model_provider
    assert bind_model_provider(second.model_provider, second.model_binding).api_key == "rotated-" + SECRET
    assert SECRET not in caplog.text
    p = setup["persistence"]
    assert SECRET not in repr(p.provider_connection_repository.list())
    assert SECRET not in repr(p.model_configuration_repository.list())
    assert SECRET not in repr(p.runtime_configuration_repository.list())
    assert SECRET not in repr(p.execution_defaults_repository.get())


@pytest.mark.parametrize("reference,value", [("env:MISSING", None), ("env:BLANK", " "), ("vault:key", None)])
def test_credential_failure_never_falls_back(setup, reference, value):
    save_defaults(setup)
    setup["persistence"].provider_connection_repository.update(
        replace(setup["connection"], credential_reference=reference)
    )
    if value is not None:
        setup["environment"][reference.split(":")[1]] = value
    with pytest.raises(CredentialResolutionFailedError):
        setup["selector"].resolve()


@pytest.mark.parametrize("boundary", ["credential", "factory"])
def test_resolution_errors_suppress_sensitive_exception_details(setup, monkeypatch, boundary):
    save_defaults(setup)
    if boundary == "credential":
        setup["persistence"].provider_connection_repository.update(
            replace(setup["connection"], credential_reference="env:KEY")
        )
        monkeypatch.setattr(setup["credentials"], "resolve", Mock(side_effect=CredentialError(SECRET)))
        error_type = CredentialResolutionFailedError
    else:
        monkeypatch.setattr(setup["factory"], "create", Mock(side_effect=RuntimeError(SECRET)))
        error_type = ProviderConstructionFailedError
    with pytest.raises(error_type) as error:
        setup["selector"].resolve()
    assert SECRET not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize(
    "endpoint,expected", [(None, "https://bootstrap.test/v1"), ("opaque:deployment", "opaque:deployment")]
)
def test_endpoint_is_passed_to_existing_provider_without_new_validation(setup, endpoint, expected):
    save_defaults(setup)
    setup["persistence"].provider_connection_repository.update(replace(setup["connection"], endpoint=endpoint))
    result = setup["resolver"].resolve_required()
    assert bind_model_provider(result.model_provider, result.model_binding).endpoint == expected


def test_legacy_override_is_explicit_not_a_persisted_default(setup):
    save_defaults(setup)
    result = setup["selector"].resolve(RunExecutionOverride(model_id="bootstrap-model"))
    assert result.source is ExecutionConfigurationSource.BOOTSTRAP
    assert result.model_binding.model_id == "bootstrap-model"


def test_omitted_execution_still_resolves_persisted_defaults(setup):
    """The default path is unchanged: no override means persisted defaults."""
    save_defaults(setup)
    result = setup["selector"].resolve()
    assert result.source is ExecutionConfigurationSource.PERSISTED
    assert result.model_binding.model_id == "configured-model"
    assert result.runtime_configuration_id == "configured-runtime"
    assert result.provider_connection_id == "configured-connection"


def test_partial_runtime_override_keeps_persisted_model_and_provider(setup):
    """Naming only a runtime must not silently swap the configured model.

    ``Model: application default`` means the persisted application default. It
    used to resolve through the bootstrap catalog instead, so the run executed
    the same underlying model but recorded its bootstrap identity, losing the
    configured provider connection and misreporting where execution came from.
    """
    save_defaults(setup)
    result = setup["selector"].resolve(RunExecutionOverride(runtime_id="openhands"))
    assert result.runtime is setup["registry"].get("openhands")
    assert result.model_binding.model_id == "configured-model"
    assert result.model_profile.capabilities.tool_calling is True
    assert result.source is ExecutionConfigurationSource.PERSISTED
    assert result.provider_connection_id == "configured-connection"
    # No configured runtime instance backs an explicitly chosen adapter key.
    assert result.runtime_configuration_id is None


def test_partial_model_override_keeps_the_persisted_runtime_instance(setup):
    """Naming only a model must not swap the configured runtime back to bootstrap."""
    save_defaults(setup)
    result = setup["selector"].resolve(RunExecutionOverride(model_id="bootstrap-model"))
    assert result.model_binding.model_id == "bootstrap-model"
    assert result.source is ExecutionConfigurationSource.BOOTSTRAP
    assert result.provider_connection_id is None
    assert result.runtime is setup["registry"].get("native")
    assert result.runtime_configuration_id == "configured-runtime"


def test_runtime_override_naming_the_persisted_runtime_keeps_its_configured_instance(setup):
    save_defaults(setup)
    result = setup["selector"].resolve(RunExecutionOverride(runtime_id="native"))
    assert result.runtime_configuration_id == "configured-runtime"
    assert result.model_binding.model_id == "configured-model"
    assert result.source is ExecutionConfigurationSource.PERSISTED


def test_partial_override_is_absent_without_persisted_defaults(setup):
    """With nothing persisted there is nothing to keep, so bootstrap still answers."""
    result = setup["selector"].resolve(RunExecutionOverride(runtime_id="openhands"))
    assert result.source is ExecutionConfigurationSource.BOOTSTRAP
    assert result.model_binding.model_id == "bootstrap-model"
    assert result.provider_connection_id is None
    assert result.runtime is setup["registry"].get("openhands")


def test_hosting_policy_rejects_saved_model_before_credentials_or_provider_construction(setup, monkeypatch):
    save_defaults(setup)
    resolver = create_execution_configuration_resolver(
        setup["persistence"],
        runtime_resolver=RuntimeResolver(setup["registry"]),
        provider_factory=setup["factory"],
        credential_resolver=setup["credentials"],
        model_orchestrator=setup["orchestrator"],
        hosting_requirement=ModelHostingRequirement.local_only(),
    )
    create = Mock(side_effect=AssertionError("policy must run first"))
    monkeypatch.setattr(setup["factory"], "create", create)
    with pytest.raises(ConfiguredModelIneligibleError):
        resolver.resolve_required()
    create.assert_not_called()


def test_repository_failure_is_not_absence(setup, monkeypatch):
    monkeypatch.setattr(
        setup["persistence"].execution_defaults_repository, "get", Mock(side_effect=RuntimeError("storage unavailable"))
    )
    with pytest.raises(RuntimeError, match="storage unavailable"):
        setup["selector"].resolve()


# ============================================================
# Explicitly chosen configured models
# ============================================================


def _add_model(setup, model_id, *, provider_model_name, enabled=True, context_window_tokens=None):
    """Persist a second configured model on the same provider connection."""
    configuration = ModelConfiguration(
        model_id,
        setup["connection"].provider_connection_id,
        provider_model_name,
        f"Display {model_id}",
        ModelHostingMode.LOCAL,
        ModelCapabilities(chat=True),
        enabled,
        context_window_tokens,
    )
    setup["persistence"].model_configuration_repository.create(configuration)
    return configuration


def test_an_explicitly_chosen_configured_model_runs_that_exact_record(setup):
    # The defect: a model added in Settings could not be chosen at all. Naming it
    # must resolve the persisted record, not the bootstrap model that shares a
    # provider.
    save_defaults(setup)
    _add_model(setup, "second-model", provider_model_name="vendor/second")

    result = setup["selector"].resolve(RunExecutionOverride(model_id="second-model"))

    assert result.source is ExecutionConfigurationSource.PERSISTED
    assert result.model_binding.model_id == "second-model"
    assert result.model_binding.provider_model_name == "vendor/second"
    assert result.model_profile.display_name == "Display second-model"
    assert result.provider_connection_id == setup["connection"].provider_connection_id


def test_configured_context_window_is_carried_into_the_resolved_profile(setup):
    save_defaults(setup)
    configured = _add_model(
        setup,
        "windowed-model",
        provider_model_name="vendor/windowed",
        context_window_tokens=32768,
    )

    result = setup["selector"].resolve(RunExecutionOverride(model_id=configured.model_id))

    assert result.model_profile.context_window_tokens == 32768


def test_configured_models_are_chosen_independently_of_the_application_default(setup):
    save_defaults(setup)
    _add_model(setup, "second-model", provider_model_name="vendor/second")

    result = setup["selector"].resolve(RunExecutionOverride(model_id="second-model"))

    # The saved default is still the first model; the explicit choice wins.
    assert setup["defaults"].default_model_id == "configured-model"
    assert result.model_binding.model_id == "second-model"


def test_several_configured_models_behind_one_connection_are_each_selectable(setup):
    save_defaults(setup)
    _add_model(setup, "second-model", provider_model_name="vendor/second")
    _add_model(setup, "third-model", provider_model_name="vendor/third")

    seen = {
        model_id: setup["selector"].resolve(RunExecutionOverride(model_id=model_id)).model_binding.provider_model_name
        for model_id in ("configured-model", "second-model", "third-model")
    }

    assert seen == {
        "configured-model": "vendor/deployment",
        "second-model": "vendor/second",
        "third-model": "vendor/third",
    }


def test_a_configured_model_is_selectable_before_any_defaults_are_saved(setup):
    # Adding a model in Settings must not depend on the user also having set an
    # application default.
    assert setup["resolver"].resolve_persisted() is None
    _add_model(setup, "second-model", provider_model_name="vendor/second")

    result = setup["selector"].resolve(RunExecutionOverride(model_id="second-model"))

    assert result.source is ExecutionConfigurationSource.PERSISTED
    assert result.model_binding.provider_model_name == "vendor/second"


def test_a_disabled_configured_model_fails_loudly_rather_than_falling_back(setup):
    # Silent substitution would run something the user did not ask for.
    save_defaults(setup)
    _add_model(setup, "off-model", provider_model_name="vendor/off", enabled=False)

    with pytest.raises(ConfiguredReferenceDisabledError):
        setup["selector"].resolve(RunExecutionOverride(model_id="off-model"))


def test_an_unknown_model_id_still_resolves_through_the_legacy_catalog(setup):
    # Bootstrap ids are still selectable; only configured records take priority.
    save_defaults(setup)
    result = setup["selector"].resolve(RunExecutionOverride(model_id="bootstrap-model"))

    assert result.source is ExecutionConfigurationSource.BOOTSTRAP
    assert result.model_binding.model_id == "bootstrap-model"


def test_a_configured_model_keeps_an_explicit_runtime_and_rejects_a_conflicting_provider(setup):
    save_defaults(setup)
    _add_model(setup, "second-model", provider_model_name="vendor/second")

    combined = setup["selector"].resolve(RunExecutionOverride(runtime_id="native", model_id="second-model"))
    assert combined.runtime is setup["registry"].get("native")
    assert combined.model_binding.model_id == "second-model"

    with pytest.raises(ValueError, match="same provider"):
        setup["selector"].resolve(
            RunExecutionOverride(model_id="second-model", model_provider_id="some-other-provider")
        )


def test_a_configured_model_on_a_disabled_connection_is_rejected(setup):
    save_defaults(setup)
    _add_model(setup, "second-model", provider_model_name="vendor/second")
    disabled = setup["persistence"].provider_connection_repository.get(setup["connection"].provider_connection_id)
    setup["persistence"].provider_connection_repository.update(replace(disabled, enabled=False))

    with pytest.raises(ConfiguredReferenceDisabledError):
        setup["selector"].resolve(RunExecutionOverride(model_id="second-model"))


# ============================================================
# BEGIN: Charter B - declared streaming capability must reach the adapter
# ============================================================


def test_a_configured_streaming_model_reaches_the_provider_adapter_as_streaming(setup):
    """The profile is only half the contract; the adapter must report it too.

    ``NativeRuntime.execute_streaming`` branches on
    ``model_provider.get_capabilities().streaming``. If resolution drops the
    operator's declared capabilities, the adapter reports chat-only and every
    configured streaming model silently completes in one shot at the end.
    """
    streaming_model = ModelConfiguration(
        "streaming-model",
        setup["connection"].provider_connection_id,
        "vendor/streaming",
        "Streaming model",
        ModelHostingMode.COMPANY_HOSTED,
        ModelCapabilities(chat=True, streaming=True),
    )
    setup["persistence"].model_configuration_repository.create(streaming_model)
    setup["persistence"].execution_defaults_repository.set(
        ApplicationExecutionDefaults(
            setup["connection"].provider_connection_id,
            streaming_model.model_id,
            setup["runtime"].runtime_configuration_id,
        )
    )

    resolved = setup["resolver"].resolve_required()

    assert resolved.model_profile.capabilities.streaming is True
    assert resolved.model_provider.get_capabilities().streaming is True


def test_a_configured_model_without_declared_streaming_stays_chat_only(setup):
    """The conservative default must survive resolution unchanged."""
    save_defaults(setup)
    resolved = setup["resolver"].resolve_required()
    assert setup["model"].capabilities.streaming is False
    assert resolved.model_provider.get_capabilities().streaming is False
    assert resolved.model_provider.get_capabilities().chat is True


# ============================================================
# END: Charter B - declared streaming capability must reach the adapter
# ============================================================
