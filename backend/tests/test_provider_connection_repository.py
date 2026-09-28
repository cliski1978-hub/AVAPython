"""Phase 5.3 provider-connection repository behavior and durability tests."""

from collections.abc import Callable
from dataclasses import dataclass

import pytest

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
)
from ava.models.provider_connections import ProviderConnection
from ava.repositories import ProviderConnectionRepository
from ava.services.provider_connection_store import ProviderConnectionStore


def _connection(connection_id: str, **changes: object) -> ProviderConnection:
    values: dict[str, object] = {
        "provider_connection_id": connection_id,
        "provider_id": "openai-compatible",
        "display_name": connection_id.title(),
        "endpoint": None,
        "enabled": True,
        "credential_reference": None,
    }
    values.update(changes)
    return ProviderConnection(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class RepositorySetup:
    repository: ProviderConnectionRepository
    dispose: Callable[[], None]


@pytest.fixture(params=["memory", "relational"])
def repository(request: pytest.FixtureRequest) -> RepositorySetup:
    if request.param == "memory":
        setup = RepositorySetup(ProviderConnectionStore(), lambda: None)
    else:
        repositories = create_relational_repositories(":memory:")
        setup = RepositorySetup(repositories.provider_connection_repository, repositories.dispose)
    yield setup
    setup.dispose()


def test_port_is_abstract_and_memory_store_implements_it() -> None:
    with pytest.raises(TypeError):
        ProviderConnectionRepository()  # type: ignore[abstract]
    assert isinstance(ProviderConnectionStore(), ProviderConnectionRepository)


def test_create_get_list_and_duplicate_are_consistent(repository: RepositorySetup) -> None:
    first = _connection(
        "local-ollama",
        display_name="Local Ollama",
        endpoint="http://localhost:11434/v1",
        credential_reference="env:OLLAMA_TOKEN",
    )
    second = _connection("company-gateway", enabled=False)
    assert repository.repository.list() == []
    assert repository.repository.create(first) == first
    assert repository.repository.create(second) == second
    assert repository.repository.get(first.provider_connection_id) == first
    assert repository.repository.get("missing") is None
    assert [item.provider_connection_id for item in repository.repository.list()] == [
        "local-ollama",
        "company-gateway",
    ]
    with pytest.raises(ValueError, match="Provider connection already exists: local-ollama"):
        repository.repository.create(first)


def test_update_replaces_mutable_fields_without_changing_provider_association(
    repository: RepositorySetup,
) -> None:
    original = _connection("gateway", endpoint=None, enabled=True, credential_reference=None)
    repository.repository.create(original)
    updated = _connection(
        "gateway",
        display_name="Approved gateway",
        endpoint="https://models.example.test/v1",
        enabled=False,
        credential_reference="vault:approved-gateway",
    )
    assert repository.repository.update(updated) == updated
    assert repository.repository.get("gateway") == updated
    assert repository.repository.update(_connection("missing")) is None
    with pytest.raises(ValueError, match="provider_id cannot change"):
        repository.repository.update(_connection("gateway", provider_id="other-provider"))


def test_relational_connection_survives_database_recreation(tmp_path) -> None:
    database_url = str(tmp_path / "ava.sqlite3")
    connection = _connection(
        "durable",
        endpoint="https://durable.example.test/v1",
        enabled=False,
        credential_reference="vault:durable",
    )
    first = create_relational_repositories(database_url)
    first.provider_connection_repository.create(connection)
    first.dispose()
    second = create_relational_repositories(database_url)
    try:
        assert second.provider_connection_repository.get("durable") == connection
    finally:
        second.dispose()


def test_v4_migrates_a_phase_4_database_without_changing_existing_rows(tmp_path) -> None:
    database_url = str(tmp_path / "phase4.sqlite3")
    database = SqliteDatabase(database_url, auto_migrate=False)
    try:
        phase4_registry = MigrationRegistry()
        for version_module in (
            v0001_initial_schema,
            v0002_document_revisions,
            v0003_attachments,
        ):
            phase4_registry.register(
                Migration(
                    version=version_module.VERSION,
                    name=version_module.NAME,
                    up=version_module.migrate_up,
                    verify=version_module.verify_structure,
                    expected_tables=version_module.EXPECTED_TABLES,
                )
            )
        assert MigrationRunner(database, phase4_registry).migrate() == [1, 2, 3]
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO conversations (conversation_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("conversation-1", "Phase 4", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
        assert MigrationRunner(database, default_registry()).migrate() == [4, 5, 6, 7, 8, 9]
        with database.connect() as connection:
            row = connection.execute(
                "SELECT title FROM conversations WHERE conversation_id = 'conversation-1'"
            ).fetchone()
            assert row[0] == "Phase 4"
            assert connection.execute("SELECT COUNT(*) FROM provider_connections").fetchone()[0] == 0
    finally:
        database.dispose()
