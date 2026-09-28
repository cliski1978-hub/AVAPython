"""Model provider composition tests.

Verify (Phase 3 Step 9) that production composition builds a real local model
provider from Settings, wires the registry/resolver into the AVA application
without contacting any provider runtime, and cleans up provider-owned HTTP
clients on application shutdown.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.infrastructure.composition import (
    close_model_providers,
    create_model_provider_registry,
)
from ava.models import ModelProviderResolver, UnknownModelProviderError
from ava.models.contracts import ModelProviderPort
from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider

#: All environment variables the settings layer reads. Tests clear them so
#: they assert on explicit values rather than ambient environment state.
_AVA_VARS = (
    "AVA_APPLICATION",
    "AVA_ENVIRONMENT",
    "AVA_AGENT_PROVIDER",
    "AVA_MODEL_PROVIDER",
    "AVA_MODEL_NAME",
    "AVA_MODEL_ID",
    "AVA_MODEL_HOSTING_MODE",
    "AVA_LOCAL_MODEL_BASE_URL",
    "AVA_HOST",
    "AVA_PORT",
    "AVA_DEBUG",
    "AVA_LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove AVA_* variables and reset the cached settings before every test."""
    for name in _AVA_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("ava.configuration.settings._settings", None)


def _local_provider_from(settings: Settings) -> OpenAICompatibleModelProvider:
    """Return the composed local provider from a registry built for ``settings``."""
    provider = create_model_provider_registry(settings).get("local")
    assert isinstance(provider, OpenAICompatibleModelProvider), "unexpected local provider type"
    return provider


# ============================================================
# BEGIN: Registry Composition Tests
# ============================================================


def test_composition_registers_local_provider_from_defaults() -> None:
    """Default settings compose a resolvable ``local`` provider into the registry."""
    settings = Settings()
    registry = create_model_provider_registry(settings)
    assert registry.contains("local")
    provider = registry.get("local")
    assert provider is not None
    assert isinstance(provider, ModelProviderPort)
    assert provider.name() == "local"
    assert provider.get_model_info().model_id == settings.model_name


def test_composition_passes_configured_local_base_url_to_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment-driven local endpoint flows into the composed provider.

    Observes the adapter's stored ``_base_url`` — a construction detail —
    because the provider port intentionally exposes no endpoint on its public
    surface; this is the cable that verifies configuration wiring without any
    network call.
    """
    monkeypatch.setenv("AVA_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:9000/v1")
    settings = Settings()
    provider = _local_provider_from(settings)
    assert provider._base_url == "http://127.0.0.1:9000/v1"
    assert provider.get_model_info().model_id == settings.model_name


def test_composition_resolves_configured_local_provider() -> None:
    """A resolver composed over the populated registry resolves ``local``."""
    settings = Settings()
    registry = create_model_provider_registry(settings)
    resolver = ModelProviderResolver(registry)
    provider = resolver.resolve(settings.model_provider)
    assert provider is registry.get("local")
    assert provider.name() == "local"
    assert provider.get_model_info().model_id == settings.model_name


def test_unknown_configured_identity_registers_nothing_and_fails_on_resolution() -> None:
    """An unknown model_provider identity never fails startup and adds no placeholder."""
    registry = create_model_provider_registry(Settings(model_provider="corporate"))
    assert registry.list() == []
    with pytest.raises(UnknownModelProviderError) as exc_info:
        ModelProviderResolver(registry).resolve("corporate")
    assert exc_info.value.provider_id == "corporate"


def test_unknown_provider_resolution_still_raises_unknown_model_provider_error() -> None:
    """Resolution behavior is unchanged: unknown ids fail explicitly."""
    registry = create_model_provider_registry(Settings())
    with pytest.raises(UnknownModelProviderError) as exc_info:
        ModelProviderResolver(registry).resolve("gateway")
    assert exc_info.value.provider_id == "gateway"


# ============================================================
# END: Registry Composition Tests
# ============================================================


# ============================================================
# BEGIN: Application Composition Tests
# ============================================================


def test_composition_and_startup_require_no_network() -> None:
    """Composing the application never contacts a provider runtime.

    A local Ollama service is neither required nor probed at startup: the
    registry is populated, resolution works, and the health endpoint responds.
    """
    app = create_app()
    registry = app.state.model_provider_registry
    assert registry.contains("local")
    assert registry.get("local") is not None
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_application_exposes_registry_and_resolver_on_state() -> None:
    """The application state carries the registry and resolver over the same instance."""
    app = create_app()
    assert app.state.model_provider_registry.contains("local")
    resolved = app.state.model_provider_resolver.resolve("local")
    assert resolved is app.state.model_provider_registry.get("local")
    assert resolved.name() == "local"


# ============================================================
# END: Application Composition Tests
# ============================================================


# ============================================================
# BEGIN: Lifecycle Tests
# ============================================================


def test_close_model_providers_closes_provider_owned_client() -> None:
    """Composition-level shutdown closes only the client the provider created."""
    registry = create_model_provider_registry(Settings())
    provider = registry.get("local")
    assert isinstance(provider, OpenAICompatibleModelProvider)
    assert not provider._http_client.is_closed

    asyncio.run(close_model_providers(registry))

    assert provider._http_client.is_closed


def test_application_shutdown_closes_provider_owned_client() -> None:
    """FastAPI lifespan shutdown releases the composed provider's HTTP client."""
    app = create_app()
    provider = app.state.model_provider_registry.get("local")
    assert isinstance(provider, OpenAICompatibleModelProvider)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert not provider._http_client.is_closed

    assert provider._http_client.is_closed


# ============================================================
# END: Lifecycle Tests
# ============================================================

@pytest.mark.parametrize("model_id", ["local", "unknown"])
def test_mock_never_resolves_model(monkeypatch: pytest.MonkeyPatch, model_id: str) -> None:
    from ava.agents.adapters.mock.mock_agent import MockAgentAdapter

    def unexpected_resolve(self: ModelProviderResolver, provider_id: str) -> ModelProviderPort:
        raise AssertionError("Mock must not resolve a model")

    monkeypatch.setenv("AVA_MODEL_PROVIDER", model_id)
    monkeypatch.setattr(ModelProviderResolver, "resolve", unexpected_resolve)
    app = create_app()
    assert isinstance(app.state.agent_port, MockAgentAdapter)
    with TestClient(app) as client:
        run = client.post("/runs", json={"prompt": "Offline"})
        assert run.status_code == 202
        assert client.get(f"/runs/{run.json()['run_id']}").json()["status"] == "completed"


def test_native_shares_registered_provider_without_startup_io(monkeypatch: pytest.MonkeyPatch) -> None:
    from ava.agents.adapters.native.native_agent import NativeAgentAdapter

    async def unexpected_io(*args: object, **kwargs: object) -> None:
        raise AssertionError("Startup must not contact the model")

    monkeypatch.setenv("AVA_AGENT_PROVIDER", "native")
    monkeypatch.setattr(OpenAICompatibleModelProvider, "health", unexpected_io)
    monkeypatch.setattr(OpenAICompatibleModelProvider, "generate", unexpected_io)
    app = create_app()
    agent = app.state.agent_port
    provider = app.state.model_provider_registry.get("local")
    assert isinstance(agent, NativeAgentAdapter)
    assert agent._selector._provider.resolve("local") is provider
    assert app.state.model_provider_resolver.resolve("local") is provider
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert not provider._http_client.is_closed
    assert provider._http_client.is_closed


def test_native_unknown_model_fails_at_execution_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown configured provider identity fails a run, not startup.

    Provider resolution is lazy (execution selection); startup never contacts a
    provider or fails eagerly for an unknown identity. The failure surfaces as
    a clean failed run through the API.
    """
    monkeypatch.setenv("AVA_AGENT_PROVIDER", "native")
    monkeypatch.setenv("AVA_MODEL_PROVIDER", "unknown")
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/runs", json={"prompt": "Hello"})
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "running"
        body = client.get(f"/runs/{body['run_id']}").json()
        assert body["status"] == "failed"
        events = client.get(f"/runs/{body['run_id']}/events").json()
        assert events[-1]["payload"]["error_code"] == "agent_failed"


def test_runtime_registry_composition_registers_native_and_openhands() -> None:
    from ava.infrastructure.composition import create_runtime_registry
    from ava.runtimes.adapters.native.native_runtime import NativeRuntime
    registry = create_runtime_registry()
    runtime = registry.get("native")
    assert isinstance(runtime, NativeRuntime)
    assert runtime.get_runtime_info().runtime_id == "native"
    assert set(registry.list()) == {"native", "openhands"}


def test_app_exposes_one_runtime_registry_and_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ava.configuration.settings._settings", None)
    app = create_app()
    registry = app.state.runtime_registry
    resolver = app.state.runtime_resolver
    assert resolver.resolve("native") is registry.get("native")
    assert set(registry.list()) == {"native", "openhands"}


def test_unknown_runtime_does_not_fail_unused_mock_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AVA_AGENT_RUNTIME", "does-not-exist")
    monkeypatch.setattr("ava.configuration.settings._settings", None)
    app = create_app()
    assert app.state.agent_port.name() == "mock"
    assert app.state.application.config.agent_runtime == "does-not-exist"


def test_unknown_runtime_does_not_fail_unused_native_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AVA_AGENT_RUNTIME", "does-not-exist")
    monkeypatch.setenv("AVA_AGENT_PROVIDER", "native")
    monkeypatch.setattr("ava.configuration.settings._settings", None)
    app = create_app()
    assert app.state.agent_port.name() == "native"
    assert app.state.application.config.agent_runtime == "does-not-exist"
