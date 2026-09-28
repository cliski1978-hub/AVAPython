"""Phase 5.5 model-configuration repository parity and durability tests."""

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.infrastructure.persistence import (
    Migration,
    MigrationRegistry,
    MigrationRunner,
    SqliteDatabase,
    create_relational_repositories,
    default_registry,
)
from ava.infrastructure.persistence.migrations.versions import (
    v0001_initial_schema,
    v0002_document_revisions,
    v0003_attachments,
    v0004_provider_connections,
)
from ava.models.model_configurations import ModelConfiguration
from ava.models.provider_connections import ProviderConnection
from ava.repositories import ModelConfigurationRepository, ProviderConnectionRepository
from ava.services.model_configuration_store import ModelConfigurationStore
from ava.services.provider_connection_store import ProviderConnectionStore


def _provider(connection_id: str = "connection-a") -> ProviderConnection:
    return ProviderConnection(connection_id, "openai-compatible", "Connection A")


def _model(model_id: str = "ava.model.a", **changes: object) -> ModelConfiguration:
    values: dict[str, object] = {
        "model_id": model_id,
        "provider_connection_id": "connection-a",
        "provider_model_name": "provider-model-a",
        "display_name": "Model A",
        "hosting_mode": ModelHostingMode.COMPANY_HOSTED,
        "capabilities": ModelCapabilities(chat=True, streaming=True, tool_calling=True),
        "enabled": True,
    }
    values.update(changes)
    return ModelConfiguration(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Setup:
    providers: ProviderConnectionRepository
    models: ModelConfigurationRepository
    dispose: Callable[[], None]


@pytest.fixture(params=["memory", "relational"])
def repositories(request: pytest.FixtureRequest) -> Setup:
    if request.param == "memory":
        providers = ProviderConnectionStore()
        setup = Setup(providers, ModelConfigurationStore(provider_connections=providers), lambda: None)
    else:
        bundle = create_relational_repositories(":memory:")
        setup = Setup(bundle.provider_connection_repository, bundle.model_configuration_repository, bundle.dispose)
    setup.providers.create(_provider())
    yield setup
    setup.dispose()


def test_port_is_abstract_and_memory_store_implements_it() -> None:
    with pytest.raises(TypeError):
        ModelConfigurationRepository()  # type: ignore[abstract]
    providers = ProviderConnectionStore()
    assert isinstance(ModelConfigurationStore(provider_connections=providers), ModelConfigurationRepository)


def test_create_get_list_duplicate_and_missing_behavior_match(repositories: Setup) -> None:
    first = _model()
    second = _model("ava.model.b", provider_model_name="provider-model-b", enabled=False)
    assert repositories.models.list() == []
    assert repositories.models.create(first) == first
    assert repositories.models.create(second) == second
    assert repositories.models.get(first.model_id) == first
    assert repositories.models.get("missing") is None
    assert [model.model_id for model in repositories.models.list()] == ["ava.model.a", "ava.model.b"]
    with pytest.raises(ValueError, match="Model configuration already exists: ava.model.a"):
        repositories.models.create(first)


def test_create_rejects_unknown_provider_connection(repositories: Setup) -> None:
    with pytest.raises(ValueError, match="Unknown provider connection: missing-connection"):
        repositories.models.create(_model(provider_connection_id="missing-connection"))


def test_update_round_trips_all_mutable_fields_and_keeps_connection_immutable(repositories: Setup) -> None:
    repositories.models.create(_model())
    updated = _model(
        provider_model_name="provider-model-new",
        display_name="Model A Revised",
        hosting_mode=ModelHostingMode.EXTERNAL,
        capabilities=ModelCapabilities(chat=True, vision=True, reasoning=True),
        enabled=False,
    )
    assert repositories.models.update(updated) == updated
    assert repositories.models.get(updated.model_id) == updated
    assert repositories.models.update(_model("missing")) is None
    with pytest.raises(ValueError, match="provider_connection_id cannot change"):
        repositories.models.update(_model(provider_connection_id="connection-b"))


def test_relational_models_and_provider_connection_survive_reopen(tmp_path) -> None:
    database_url = str(tmp_path / "ava.sqlite3")
    provider = _provider()
    model = _model(enabled=False)
    first = create_relational_repositories(database_url)
    first.provider_connection_repository.create(provider)
    first.model_configuration_repository.create(model)
    first.dispose()
    second = create_relational_repositories(database_url)
    try:
        assert second.provider_connection_repository.get(provider.provider_connection_id) == provider
        assert second.model_configuration_repository.get(model.model_id) == model
    finally:
        second.dispose()


def test_v5_upgrades_a_v4_database_and_preserves_provider_connections(tmp_path) -> None:
    database = SqliteDatabase(str(tmp_path / "phase5-v4.sqlite3"), auto_migrate=False)
    try:
        registry = MigrationRegistry()
        for version in (v0001_initial_schema, v0002_document_revisions, v0003_attachments, v0004_provider_connections):
            registry.register(Migration(version=version.VERSION, name=version.NAME, up=version.migrate_up,
                                        verify=version.verify_structure, expected_tables=version.EXPECTED_TABLES))
        assert MigrationRunner(database, registry).migrate() == [1, 2, 3, 4]
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO provider_connections "
                "(provider_connection_id, provider_id, display_name, endpoint, enabled, credential_reference) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("connection-a", "openai-compatible", "Connection A", None, True, None),
            )
        assert MigrationRunner(database, default_registry()).migrate() == [5, 6, 7, 8, 9]
        with database.connect() as connection:
            row = connection.execute(
                "SELECT provider_id FROM provider_connections WHERE provider_connection_id = 'connection-a'"
            ).fetchone()
            assert row[0] == "openai-compatible"
            assert connection.execute("SELECT COUNT(*) FROM model_configurations").fetchone()[0] == 0
    finally:
        database.dispose()
