"""Settings -> real run machinery -> HTTP adapter, without external network."""

import asyncio
import importlib
import json
import logging
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from ava.configuration.settings import Settings
from ava.contracts.models import ModelHostingMode
from ava.execution.model_resources import (
    DefaultResourceDescriptor,
    ModelCapacityExceededError,
    ModelLeaseConflictError,
    ModelResourceAdapterRegistry,
    ModelResourceManager,
    ModelResourceState,
    ModelResourceUnavailableError,
    ResourceCapacity,
)
from ava.infrastructure.model_provider_factory import (
    ConfiguredModelProviderFactory,
    installed_provider_adapter_ids,
)
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.registry import ModelProviderRegistry

app_module = importlib.import_module("ava.api.app")
SECRET = "phase516-integration-secret"


def configure(client):
    providers = client.post(
        "/settings/providers",
        json={
            "provider_connection_id": "gateway",
            "provider_id": "local",
            "display_name": "Gateway",
            "endpoint": "https://configured.test/v1",
            "credential_reference": "env:AVA_PHASE516_KEY",
            "enabled": True,
        },
    )
    assert providers.status_code == 201, providers.text
    models = client.post(
        "/settings/models",
        json={
            "model_id": "configured-model",
            "provider_connection_id": "gateway",
            "provider_model_name": "vendor/model",
            "display_name": "Model",
            "hosting_mode": "company_hosted",
            "capabilities": {"chat": True},
            "enabled": True,
        },
    )
    assert models.status_code == 201, models.text
    runtimes = client.post(
        "/settings/runtimes",
        json={
            "runtime_configuration_id": "configured-runtime",
            "runtime_type": "native",
            "display_name": "Runtime",
            "enabled": True,
        },
    )
    assert runtimes.status_code == 201, runtimes.text
    defaults = client.put(
        "/settings/defaults",
        json={
            "default_provider_connection_id": "gateway",
            "default_model_id": "configured-model",
            "default_runtime_configuration_id": "configured-runtime",
        },
    )
    assert defaults.status_code == 200, defaults.text


@pytest.fixture
def transport(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200, json={"model": "vendor/model", "choices": [{"message": {"content": "persisted answer"}}]}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    factories = []

    def make_factory(settings, registry):
        factory = ConfiguredModelProviderFactory(
            installed_provider_ids=installed_provider_adapter_ids(registry),
            default_endpoint=settings.local_model_base_url,
            http_client=http,
        )
        factories.append(factory)
        return factory

    monkeypatch.setattr(app_module, "create_configured_model_provider_factory", make_factory)
    monkeypatch.setenv("AVA_PHASE516_KEY", SECRET)
    yield requests, factories
    asyncio.run(http.aclose())


def settings_for(tmp_path, persistence="memory"):
    return Settings(
        agent_provider="native",
        agent_runtime="native",
        model_provider="local",
        model_name="bootstrap-native",
        model_id="bootstrap-model",
        model_hosting_mode=ModelHostingMode.LOCAL,
        local_model_base_url="https://bootstrap.test/v1",
        persistence_provider=persistence,
        persistence_database_url=str(tmp_path / "integration.sqlite3"),
        attachment_storage="memory",
    )


@pytest.mark.parametrize("persistence", ["memory", "relational"])
def test_saved_defaults_reach_runtime_orchestrator_lease_and_provider(
    tmp_path,
    monkeypatch,
    transport,
    caplog,
    persistence,
):
    requests, _ = transport
    app = app_module.create_app(settings=settings_for(tmp_path, persistence))
    observed = []
    select = app.state.model_orchestrator.select

    def select_observed(request, **kwargs):
        result = select(request, **kwargs)
        observed.append(result.model_id)
        return result

    monkeypatch.setattr(app.state.model_orchestrator, "select", select_observed)
    manager = app.state.model_resource_manager
    acquire = manager.acquire
    leases = []

    async def acquire_observed(model_id, **kwargs):
        lease = await acquire(model_id, **kwargs)
        leases.append(lease)
        return lease

    monkeypatch.setattr(manager, "acquire", acquire_observed)
    runtime_resolve = app.state.runtime_resolver.resolve
    runtime_ids = []

    def resolve_observed(runtime_id):
        runtime_ids.append(runtime_id)
        return runtime_resolve(runtime_id)

    monkeypatch.setattr(app.state.runtime_resolver, "resolve", resolve_observed)
    # An accidental bootstrap selection would fail, never contact a live server.
    bootstrap = app.state.model_provider_registry.get("local")

    async def no_bootstrap(*args, **kwargs):
        pytest.fail("persisted execution selected bootstrap provider")

    monkeypatch.setattr(bootstrap, "generate", no_bootstrap)
    caplog.set_level(logging.DEBUG)
    with TestClient(app) as client:
        profiles_before = client.get("/execution-profiles").json()
        configure(client)
        assert requests == []  # startup and settings never resolve/invoke provider
        assert client.get("/execution-profiles").json() == profiles_before
        for key in [SECRET, "rotated-" + SECRET]:
            monkeypatch.setenv("AVA_PHASE516_KEY", key)
            response = client.post("/runs", json={"prompt": "hello"})
            assert response.status_code == 202
            body = response.json()
            assert body["status"] == "running"
            body = client.get(f"/runs/{body['run_id']}").json()
            assert body["status"] == "completed", body
            assert body["execution_selection"]["model_id"] == "configured-model"
            assert body["execution_selection"]["runtime_id"] == "native"
            assert body["execution_selection"]["model_provider_id"] == "local"
            assert body["execution_selection"]["hosting_mode"] == "company_hosted"
            events = client.get(f"/runs/{body['run_id']}/events")
            assert "persisted answer" in events.text
            assert SECRET not in response.text + events.text
            assert requests[-1].headers["authorization"] == f"Bearer {key}"
            assert str(requests[-1].url) == "https://configured.test/v1/chat/completions"
            assert json.loads(requests[-1].content)["model"] == "vendor/model"
            assert app.state.agent_port._executions == {}  # no completed provider/key retention
        assert observed == ["configured-model", "configured-model"]
        assert runtime_ids == ["native", "native"]
        assert len(leases) == 2
        # Unload would raise on any leaked lease.
        asyncio.run(manager.unload("configured-model"))
        assert SECRET not in caplog.text
        if persistence == "relational":
            with app.state.persistence.database.connect() as db:
                assert SECRET not in "\n".join(db.iterdump())


@pytest.mark.parametrize("failure", ["disabled", "credential", "runtime", "provider", "relationship"])
def test_invalid_saved_defaults_fail_run_without_bootstrap_or_http(tmp_path, monkeypatch, transport, failure):
    requests, _ = transport
    app = app_module.create_app(settings=settings_for(tmp_path))
    bootstrap = app.state.model_provider_registry.get("local")
    attempted = []

    async def bootstrap_generate(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("must not fall back")

    monkeypatch.setattr(bootstrap, "generate", bootstrap_generate)
    with TestClient(app) as client:
        configure(client)
        p = app.state.persistence
        if failure == "disabled":
            model = p.model_configuration_repository.get("configured-model")
            p.model_configuration_repository.update(replace(model, enabled=False))
        elif failure == "credential":
            monkeypatch.delenv("AVA_PHASE516_KEY")
        elif failure == "runtime":
            runtime = p.runtime_configuration_repository.get("configured-runtime")
            monkeypatch.setattr(
                p.runtime_configuration_repository, "get", lambda _: replace(runtime, runtime_type="absent")
            )
        elif failure == "provider":
            connection = p.provider_connection_repository.get("gateway")
            monkeypatch.setattr(
                p.provider_connection_repository, "get", lambda _: replace(connection, provider_id="absent")
            )
        else:
            model = p.model_configuration_repository.get("configured-model")
            monkeypatch.setattr(
                p.model_configuration_repository, "get", lambda _: replace(model, provider_connection_id="other")
            )
        response = client.post("/runs", json={"prompt": "hello"})
        assert response.status_code == 202
        body = client.get(f"/runs/{response.json()['run_id']}").json()
        assert body["status"] == "failed"
        events = client.get(f"/runs/{body['run_id']}/events")
        assert "run_failed" in events.text
        assert "message_content" not in events.text
        assert requests == attempted == []


def test_absent_defaults_retain_bootstrap_execution(tmp_path, monkeypatch, transport):
    from ava.contracts.models import ModelResponse

    requests, _ = transport
    app = app_module.create_app(settings=settings_for(tmp_path))
    invoked = []

    async def generate(request, *, model_name=None):
        invoked.append(model_name)
        return ModelResponse(content="bootstrap answer", model_id="bootstrap-native")

    monkeypatch.setattr(app.state.model_provider_registry.get("local"), "generate", generate)
    with TestClient(app) as client:
        response = client.post("/runs", json={"prompt": "hello"})
        assert response.status_code == 202
        body = client.get(f"/runs/{response.json()['run_id']}").json()
        assert body["status"] == "completed"
        assert body["execution_selection"]["model_id"] == "bootstrap-model"
        assert invoked == ["bootstrap-native"]
        assert requests == []


def test_persisted_defaults_drive_execution_after_restart(tmp_path, transport):
    requests, _ = transport
    settings = settings_for(tmp_path, "relational")
    with TestClient(app_module.create_app(settings=settings)) as client:
        configure(client)
        first = client.post("/runs", json={"prompt": "before restart"}).json()
        assert first["status"] == "running"
    with TestClient(app_module.create_app(settings=settings)) as client:
        assert client.get(f"/runs/{first['run_id']}").json()["status"] == "completed"
        second = client.post("/runs", json={"prompt": "after restart"}).json()
        assert second["status"] == "running"
        second = client.get(f"/runs/{second['run_id']}").json()
        assert second["status"] == "completed"
        assert second["execution_selection"]["model_id"] == "configured-model"
    assert len(requests) == 2


def test_factory_closes_owned_pool_and_does_not_close_injected_pool():
    async def scenario():
        owned = ConfiguredModelProviderFactory(installed_provider_ids=frozenset({"local"}), default_endpoint="opaque")
        await owned.aclose()
        await owned.aclose()
        assert owned._http_client.is_closed
        async with httpx.AsyncClient() as client:
            factory = ConfiguredModelProviderFactory(
                installed_provider_ids=frozenset({"local"}),
                default_endpoint="opaque",
                http_client=client,
            )
            await factory.aclose()
            assert not client.is_closed

    asyncio.run(scenario())


def test_registry_membership_does_not_reinterpret_an_unrelated_adapter():
    from ava.models.contracts import ModelProviderPort

    registry = ModelProviderRegistry()
    registry.register("custom-protocol", Mock(spec=ModelProviderPort))
    assert installed_provider_adapter_ids(registry) == frozenset()


def test_dynamic_resource_leases_preserve_capacity_and_unknown_id_rejection():
    class ColdAdapter:
        async def get_state(self, model_id):
            return ModelResourceState.COLD

        async def load(self, model_id):
            pass

        async def unload(self, model_id):
            pass

    manager = ModelResourceManager(
        registry=ModelRegistry(()),
        descriptors=(),
        adapters=ModelResourceAdapterRegistry({"test": ColdAdapter()}),
        default_descriptor=DefaultResourceDescriptor("test", estimated_vram_mb=8),
        capacity=ResourceCapacity(vram_mb=10),
    )
    profile = ModelProfile("selected", "Selected", "local", "vendor/model", ModelHostingMode.LOCAL)

    async def scenario():
        with pytest.raises(ModelResourceUnavailableError):
            await manager.acquire("arbitrary-id")
        lease = await manager.acquire(profile.model_id, profile=profile)
        with pytest.raises(ModelCapacityExceededError):
            await manager.acquire("second", profile=replace(profile, model_id="second"))
        with pytest.raises(ModelLeaseConflictError):
            await manager.acquire(profile.model_id, profile=replace(profile, hosting_mode=ModelHostingMode.EXTERNAL))
        await lease.release()
        await manager.unload(profile.model_id)
        second = await manager.acquire("second", profile=replace(profile, model_id="second"))
        await second.release()

    asyncio.run(scenario())
