"""Phase 5.17 startup authority, atomic seeding, collisions and request paths."""

import importlib
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from ava.configuration.settings import Settings
from ava.contracts.models import ModelHostingMode, ModelResponse
from ava.infrastructure.composition import (
    bootstrap_execution_configuration,
    create_application_persistence,
    create_runtime_registry,
)
from ava.infrastructure.configuration_bootstrap import BootstrapStatus, ConfigurationBootstrapError
from ava.models.provider_connections import ProviderConnection
from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider

app_module = importlib.import_module("ava.api.app")


def settings_for(tmp_path: Path, **changes) -> Settings:
    return replace(
        Settings(
            agent_provider="native",
            agent_runtime="native",
            model_provider="local",
            model_name="vendor-a",
            model_id="ava-model-a",
            model_hosting_mode=ModelHostingMode.LOCAL,
            local_model_base_url="https://first.test/v1",
            persistence_provider="relational",
            persistence_database_url=str(tmp_path / "bootstrap.sqlite3"),
            attachment_storage="memory",
        ),
        **changes,
    )


def inventories(p):
    return (
        p.provider_connection_repository.list(),
        p.model_configuration_repository.list(),
        p.runtime_configuration_repository.list(),
        p.execution_defaults_repository.get(),
    )


def seed(settings, persistence):
    return bootstrap_execution_configuration(settings, persistence, create_runtime_registry())


def test_fresh_durable_configuration_and_restart_are_deterministic(tmp_path):
    settings = settings_for(tmp_path)
    p = create_application_persistence(settings)
    assert seed(settings, p) is BootstrapStatus.SEEDED
    first = inventories(p)
    provider, model, runtime, defaults = first
    assert len(provider) == len(model) == len(runtime) == 1
    assert provider[0].provider_connection_id == "bootstrap-provider-local"
    assert provider[0].credential_reference is None
    assert provider[0].endpoint == settings.local_model_base_url
    assert model[0].model_id == "ava-model-a"
    assert model[0].provider_model_name == "vendor-a"
    assert runtime[0].runtime_configuration_id == "bootstrap-runtime-native"
    assert runtime[0].runtime_type == "native"
    assert defaults.default_model_id == model[0].model_id
    p.dispose()
    p = create_application_persistence(settings)
    try:
        assert seed(settings, p) is BootstrapStatus.PERSISTED_DEFAULTS
        assert inventories(p) == first
    finally:
        p.dispose()


def test_legacy_derived_model_identity_is_preserved(tmp_path):
    settings = settings_for(tmp_path, model_id="")
    p = create_application_persistence(settings)
    try:
        assert seed(settings, p) is BootstrapStatus.SEEDED
        assert p.execution_defaults_repository.get().default_model_id == "local-vendor-a"
    finally:
        p.dispose()


@pytest.mark.parametrize("matching", [True, False])
def test_partial_or_colliding_configuration_is_never_completed_or_rewritten(tmp_path, matching):
    settings = settings_for(tmp_path)
    p = create_application_persistence(settings)
    connection = ProviderConnection(
        "bootstrap-provider-local",
        "local" if matching else "different-protocol",
        "User label",
        endpoint=settings.local_model_base_url if matching else "opaque:other",
    )
    p.provider_connection_repository.create(connection)
    before = inventories(p)
    assert seed(settings, p) is BootstrapStatus.EXISTING_RECORDS
    assert inventories(p) == before
    p.dispose()
    p = create_application_persistence(settings)
    try:
        assert seed(settings, p) is BootstrapStatus.EXISTING_RECORDS
        assert inventories(p) == before
    finally:
        p.dispose()


@pytest.mark.parametrize(
    "failed_repository,method",
    [
        ("provider_connection_repository", "create"),
        ("model_configuration_repository", "create"),
        ("runtime_configuration_repository", "create"),
        ("execution_defaults_repository", "set"),
    ],
)
def test_failure_rolls_back_all_rows_and_restart_can_seed(tmp_path, monkeypatch, failed_repository, method):
    settings = settings_for(tmp_path)
    p = create_application_persistence(settings)
    with monkeypatch.context() as patch:
        patch.setattr(getattr(p, failed_repository), method, Mock(side_effect=RuntimeError("injected write failure")))
        with pytest.raises(ConfigurationBootstrapError, match="rolled back"):
            seed(settings, p)
    assert inventories(p) == ([], [], [], None)
    p.dispose()
    p = create_application_persistence(settings)
    try:
        assert seed(settings, p) is BootstrapStatus.SEEDED
    finally:
        p.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {"model_name": " "},
        {"model_provider": "uninstalled"},
        {"agent_runtime": "uninstalled"},
        {"local_model_base_url": "opaque:unsupported"},
        {"local_model_base_url": "http://[broken"},
        {"model_id": "bootstrap-provider-local"},
        {"model_id": "vendor-a"},
    ],
)
def test_invalid_bootstrap_leaves_settings_unconfigured(tmp_path, changes):
    settings = settings_for(tmp_path, **changes)
    p = create_application_persistence(settings)
    try:
        assert seed(settings, p) is BootstrapStatus.INVALID_BOOTSTRAP
        assert inventories(p) == ([], [], [], None)
    finally:
        p.dispose()


@pytest.mark.parametrize("changes", [{"agent_provider": "mock"}, {"persistence_provider": "memory"}])
def test_development_composition_retains_compatibility_without_seeding(tmp_path, changes):
    settings = settings_for(tmp_path, **changes)
    p = create_application_persistence(settings)
    try:
        assert seed(settings, p) is BootstrapStatus.COMPATIBILITY_ONLY
        assert inventories(p) == ([], [], [], None)
    finally:
        p.dispose()


def test_env_changes_preserve_every_user_edit_including_disabled_records(tmp_path):
    settings = settings_for(tmp_path)
    p = create_application_persistence(settings)
    seed(settings, p)
    providers, models, runtimes, _ = inventories(p)
    p.provider_connection_repository.update(
        replace(
            providers[0],
            display_name="Edited gateway",
            endpoint="https://edited.test/v1",
            enabled=False,
            credential_reference="env:OPERATOR_KEY",
        )
    )
    p.model_configuration_repository.update(
        replace(
            models[0],
            display_name="Edited model",
            provider_model_name="edited-deployment",
            enabled=False,
            hosting_mode=ModelHostingMode.COMPANY_HOSTED,
        )
    )
    p.runtime_configuration_repository.update(replace(runtimes[0], display_name="Edited runtime", enabled=False))
    before = inventories(p)
    p.dispose()
    changed = replace(settings, model_name="vendor-b", model_id="ava-model-b", agent_runtime="openhands")
    p = create_application_persistence(changed)
    try:
        assert seed(changed, p) is BootstrapStatus.PERSISTED_DEFAULTS
        assert inventories(p) == before
    finally:
        p.dispose()


@pytest.fixture
def generation(monkeypatch):
    calls = []

    async def generate(self, request, *, model_name=None):
        calls.append((self.name(), model_name, self._base_url))
        return ModelResponse(content="configured answer", model_id=model_name or "default")

    monkeypatch.setattr(OpenAICompatibleModelProvider, "generate", generate)
    return calls


def test_api_edit_restart_and_default_vs_explicit_request_authority(tmp_path, generation):
    settings = settings_for(tmp_path)
    with TestClient(app_module.create_app(settings=settings)) as client:
        records = client.get("/settings/models").json()["models"]
        assert records[0]["model_id"] == "ava-model-a"
        result = client.put(
            "/settings/models/ava-model-a",
            json={
                "display_name": "User edited",
                "provider_model_name": "user-deployment",
                "hosting_mode": "company_hosted",
                "capabilities": {"chat": True},
                "enabled": True,
            },
        )
        assert result.status_code == 200, result.text
    changed = replace(
        settings, model_id="ava-model-b", model_name="vendor-b", local_model_base_url="https://second.test/v1"
    )
    with TestClient(app_module.create_app(settings=changed)) as client:
        default = client.post("/runs", json={"prompt": "default request"}).json()
        assert default["status"] == "running"
        default = client.get(f"/runs/{default['run_id']}").json()
        assert default["status"] == "completed"
        assert default["execution_selection"]["model_id"] == "ava-model-a"
        assert generation[-1] == ("local", "user-deployment", "https://first.test/v1")
        profiles = client.get("/execution-profiles").json()["profiles"]
        profile = next(p for p in profiles if p["id"] == "local-default")
        for override in [
            {"model_id": "ava-model-b"},
            {"runtime_id": profile["runtime_id"], "model_provider_id": profile["model_provider_id"]},
            {"mode": "auto"},
        ]:
            explicit = client.post("/runs", json={"prompt": "explicit request", "execution": override}).json()
            assert explicit["status"] == "running"
            explicit = client.get(f"/runs/{explicit['run_id']}").json()
            assert explicit["status"] == "completed"
            assert explicit["execution_selection"]["model_id"] == "ava-model-b"
            assert explicit["execution_selection"]["runtime_id"] == "native"
            assert explicit["execution_selection"]["model_provider_id"] == "local"
            assert generation[-1] == ("local", "vendor-b", "https://second.test/v1")


def test_unresolvable_explicit_execution_fails_as_configuration_before_runtime(tmp_path, generation):
    app = app_module.create_app(settings=settings_for(tmp_path))
    with TestClient(app) as client:
        profiles = client.get("/execution-profiles").json()["profiles"]
        local_coding = next(profile for profile in profiles if profile["id"] == "local-default")
        response = client.post(
            "/runs",
            json={
                "prompt": "must not execute",
                "execution": {
                    "runtime_id": "missing-runtime",
                    "model_provider_id": local_coding["model_provider_id"],
                },
            },
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        run = client.get(f"/runs/{run_id}").json()
        events = client.get(f"/runs/{run_id}/events").json()

    assert run["status"] == "failed"
    assert run["execution_selection"] is None
    failed = next(event for event in events if event["event_type"] == "run_failed")
    assert failed["payload"]["error_code"] == "configuration_invalid"
    assert failed["payload"]["message"] == (
        "The selected provider, model, and runtime combination cannot be used. Review the execution settings."
    )
    assert generation == []


@pytest.mark.parametrize("changes", [{"model_provider": "uninstalled"}, {"model_name": " "}])
def test_usable_persisted_defaults_do_not_depend_on_usable_legacy_config(tmp_path, generation, changes):
    settings = settings_for(tmp_path)
    with TestClient(app_module.create_app(settings=settings)):
        pass
    with TestClient(app_module.create_app(settings=replace(settings, **changes))) as client:
        result = client.post("/runs", json={"prompt": "persisted wins"}).json()
        assert result["status"] == "running"
        result = client.get(f"/runs/{result['run_id']}").json()
        assert result["status"] == "completed"
        assert result["execution_selection"]["model_id"] == "ava-model-a"
        assert generation[-1][1] == "vendor-a"


@pytest.mark.parametrize("defect", ["disabled", "missing"])
def test_invalid_saved_defaults_cannot_be_reseeded_or_fall_back(tmp_path, generation, defect):
    settings = settings_for(tmp_path)
    with TestClient(app_module.create_app(settings=settings)) as client:
        app = client.app
        p = app.state.persistence
        model = p.model_configuration_repository.get("ava-model-a")
        if defect == "disabled":
            p.model_configuration_repository.update(replace(model, enabled=False))
        else:
            with p.database.transaction() as db:
                db.execute("DELETE FROM model_configurations")
    with TestClient(app_module.create_app(settings=settings)) as client:
        assert client.app.state.configuration_bootstrap_status is BootstrapStatus.PERSISTED_DEFAULTS
        response = client.post("/runs", json={"prompt": "must fail"}).json()
        assert response["status"] == "running"
        response = client.get(f"/runs/{response['run_id']}").json()
        assert response["status"] == "failed"
        assert generation == []


def test_fresh_invalid_bootstrap_keeps_settings_reachable(tmp_path, generation, caplog):
    settings = settings_for(tmp_path, model_name=" ")
    with TestClient(app_module.create_app(settings=settings)) as client:
        assert client.get("/settings/defaults").json()["configured"] is False
        run = client.post("/runs", json={"prompt": "unconfigured"}).json()
        assert run["status"] == "running"
        assert client.get(f"/runs/{run['run_id']}").json()["status"] == "failed"
    assert "Settings" in caplog.text
    assert generation == []


def test_nested_repository_success_does_not_commit_outer_transaction(tmp_path):
    settings = settings_for(tmp_path)
    p = create_application_persistence(settings)
    try:
        with pytest.raises(RuntimeError), p.database.transaction():
            p.provider_connection_repository.create(ProviderConnection("connection", "local", "Test"))
            raise RuntimeError("outer failure")
        assert p.provider_connection_repository.list() == []
        with p.database.transaction():
            p.provider_connection_repository.create(ProviderConnection("keep", "local", "Keep"))
            with pytest.raises(RuntimeError), p.database.transaction():
                p.provider_connection_repository.create(ProviderConnection("discard", "local", "Discard"))
                raise RuntimeError("inner failure")
        assert [c.provider_connection_id for c in p.provider_connection_repository.list()] == ["keep"]
    finally:
        p.dispose()
