"""Phase 5.7 runtime-configuration repository parity and durability tests."""

import ast
import dataclasses
import inspect
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
    v0004_provider_connections,
    v0005_model_configurations,
)
from ava.repositories import RuntimeConfigurationRepository
from ava.runtimes.configurations import RuntimeConfiguration
from ava.services.run_service import RunService
from ava.services.runtime_configuration_store import RuntimeConfigurationStore


def _configuration(configuration_id: str = "openhands-local", **changes: object) -> RuntimeConfiguration:
    values: dict[str, object] = {
        "runtime_configuration_id": configuration_id,
        "runtime_type": "openhands",
        "display_name": "OpenHands Local",
        "enabled": True,
    }
    values.update(changes)
    return RuntimeConfiguration(**values)  # type: ignore[arg-type]


def _imported_names(target: object) -> set[str]:
    """Return the names a module actually imports, ignoring its docstring prose."""
    module = inspect.getmodule(target)
    assert module is not None
    names: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
    return names


def _declared_field_names(source: str) -> set[str]:
    """Return annotated attribute and function-parameter names declared in ``source``.

    Docstrings are skipped, so a module may describe what it deliberately omits
    without the check reading that prose as a declared field.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument in [*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs]:
                names.add(argument.arg)
    return names


@dataclass(frozen=True)
class Setup:
    runtimes: RuntimeConfigurationRepository
    dispose: Callable[[], None]


@pytest.fixture(params=["memory", "relational"])
def repositories(request: pytest.FixtureRequest) -> Setup:
    if request.param == "memory":
        setup = Setup(RuntimeConfigurationStore(), lambda: None)
    else:
        bundle = create_relational_repositories(":memory:")
        setup = Setup(bundle.runtime_configuration_repository, bundle.dispose)
    yield setup
    setup.dispose()


# ============================================================
# BEGIN Port and in-memory implementation
# ============================================================


def test_port_is_abstract_and_memory_store_implements_it() -> None:
    with pytest.raises(TypeError):
        RuntimeConfigurationRepository()  # type: ignore[abstract]
    store = RuntimeConfigurationStore()
    assert isinstance(store, RuntimeConfigurationRepository)


def test_port_exposes_only_configuration_storage_operations() -> None:
    """The port stores records; it resolves no runtime and looks up no model."""
    public = {name for name in dir(RuntimeConfigurationRepository) if not name.startswith("_")}
    assert public == {"create", "get", "list", "update"}
    assert _imported_names(RuntimeConfigurationRepository) == {
        "ABC",
        "abstractmethod",
        "Collection",
        "RuntimeConfiguration",
    }


def test_create_get_list_duplicate_and_missing_behavior_match(repositories: Setup) -> None:
    first = _configuration()
    second = _configuration("native-local", runtime_type="native", display_name="Native AVA", enabled=False)
    assert repositories.runtimes.list() == []
    assert repositories.runtimes.create(first) == first
    assert repositories.runtimes.create(second) == second
    assert repositories.runtimes.get(first.runtime_configuration_id) == first
    assert repositories.runtimes.get("missing") is None
    assert [item.runtime_configuration_id for item in repositories.runtimes.list()] == [
        "openhands-local",
        "native-local",
    ]
    with pytest.raises(ValueError, match="Runtime configuration already exists: openhands-local"):
        repositories.runtimes.create(first)


def test_listing_order_is_insertion_order_not_alphabetical(repositories: Setup) -> None:
    """Deterministic order is creation order, independent of identity spelling."""
    for configuration_id in ("zulu", "alpha", "mike"):
        repositories.runtimes.create(_configuration(configuration_id))
    assert [item.runtime_configuration_id for item in repositories.runtimes.list()] == [
        "zulu",
        "alpha",
        "mike",
    ]


def test_runtime_type_is_stored_as_an_opaque_ava_owned_identifier(repositories: Setup) -> None:
    """Persistence stores the domain value; it does not fix a runtime vocabulary."""
    for runtime_type in ("native", "openhands", "langgraph", "agentcore", "future-adapter"):
        repositories.runtimes.create(_configuration(f"config-{runtime_type}", runtime_type=runtime_type))
    stored = {item.runtime_type for item in repositories.runtimes.list()}
    assert stored == {"native", "openhands", "langgraph", "agentcore", "future-adapter"}
    assert repositories.runtimes.get("config-future-adapter").runtime_type == "future-adapter"  # type: ignore[union-attr]


def test_update_changes_display_name_and_enabled_but_not_identity_or_type(repositories: Setup) -> None:
    original = _configuration()
    repositories.runtimes.create(original)
    updated = _configuration(display_name="OpenHands (EU)", enabled=False)
    assert repositories.runtimes.update(updated) == updated
    assert repositories.runtimes.get("openhands-local") == updated
    assert updated.runtime_configuration_id == original.runtime_configuration_id
    assert updated.runtime_type == original.runtime_type
    assert repositories.runtimes.update(_configuration("missing")) is None


def test_runtime_type_cannot_be_reassigned_after_creation(repositories: Setup) -> None:
    """Changing type would redefine what the configured instance represents."""
    repositories.runtimes.create(_configuration())
    with pytest.raises(ValueError, match="runtime_type cannot change"):
        repositories.runtimes.update(_configuration(runtime_type="native"))
    assert repositories.runtimes.get("openhands-local").runtime_type == "openhands"  # type: ignore[union-attr]


def test_enabled_state_round_trips_in_both_directions(repositories: Setup) -> None:
    repositories.runtimes.create(_configuration())
    assert repositories.runtimes.get("openhands-local").enabled is True  # type: ignore[union-attr]
    disabled = repositories.runtimes.update(_configuration(enabled=False))
    assert disabled is not None and disabled.enabled is False
    assert repositories.runtimes.get("openhands-local").enabled is False  # type: ignore[union-attr]
    reenabled = repositories.runtimes.update(_configuration(enabled=True))
    assert reenabled is not None and reenabled.enabled is True
    assert repositories.runtimes.get("openhands-local").enabled is True  # type: ignore[union-attr]


def test_configured_instance_identity_is_independent_of_the_runtime_registry_key() -> None:
    """``runtime_configuration_id`` is not the ``RuntimeRegistry`` lookup key."""
    configuration = _configuration("production-openhands")
    assert configuration.runtime_configuration_id == "production-openhands"
    assert configuration.runtime_type == "openhands"
    assert configuration.runtime_configuration_id != configuration.runtime_type


# ============================================================
# END Port and in-memory implementation
# ============================================================


# ============================================================
# BEGIN Restart durability
# ============================================================


def test_relational_runtime_configuration_survives_reopen(tmp_path) -> None:
    database_url = str(tmp_path / "ava.sqlite3")
    configurations = [
        _configuration("native-local", runtime_type="native", display_name="Native AVA", enabled=False),
        _configuration("openhands-local", display_name="OpenHands Local"),
    ]
    first = create_relational_repositories(database_url)
    for configuration in configurations:
        first.runtime_configuration_repository.create(configuration)
    first.dispose()

    second = create_relational_repositories(database_url)
    try:
        for configuration in configurations:
            reloaded = second.runtime_configuration_repository.get(configuration.runtime_configuration_id)
            assert reloaded == configuration
            assert reloaded is not None
            assert reloaded.runtime_configuration_id == configuration.runtime_configuration_id
            assert reloaded.runtime_type == configuration.runtime_type
            assert reloaded.display_name == configuration.display_name
            assert reloaded.enabled == configuration.enabled
        assert list(second.runtime_configuration_repository.list()) == configurations
    finally:
        second.dispose()


def test_update_persists_across_reopen(tmp_path) -> None:
    database_url = str(tmp_path / "ava.sqlite3")
    first = create_relational_repositories(database_url)
    first.runtime_configuration_repository.create(_configuration())
    first.runtime_configuration_repository.update(_configuration(display_name="Renamed", enabled=False))
    first.dispose()

    second = create_relational_repositories(database_url)
    try:
        reloaded = second.runtime_configuration_repository.get("openhands-local")
        assert reloaded == _configuration(display_name="Renamed", enabled=False)
    finally:
        second.dispose()


# ============================================================
# END Restart durability
# ============================================================


# ============================================================
# BEGIN Migration compatibility
# ============================================================


def _registry_through_v5() -> MigrationRegistry:
    registry = MigrationRegistry()
    for version in (
        v0001_initial_schema,
        v0002_document_revisions,
        v0003_attachments,
        v0004_provider_connections,
        v0005_model_configurations,
    ):
        registry.register(
            Migration(
                version=version.VERSION,
                name=version.NAME,
                up=version.migrate_up,
                verify=version.verify_structure,
                expected_tables=version.EXPECTED_TABLES,
            )
        )
    return registry


def test_v6_upgrades_a_v5_database_and_preserves_existing_configuration(tmp_path) -> None:
    database = SqliteDatabase(str(tmp_path / "phase5-v5.sqlite3"), auto_migrate=False)
    try:
        assert MigrationRunner(database, _registry_through_v5()).migrate() == [1, 2, 3, 4, 5]
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO provider_connections "
                "(provider_connection_id, provider_id, display_name, endpoint, enabled, credential_reference) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("connection-a", "openai-compatible", "Connection A", None, True, None),
            )
            connection.execute(
                "INSERT INTO model_configurations "
                "(model_id, provider_connection_id, provider_model_name, display_name, hosting_mode, "
                "capabilities, enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "ava.model.a",
                    "connection-a",
                    "provider-model-a",
                    "Model A",
                    "company_hosted",
                    '{"chat":true,"vision":false}',
                    True,
                ),
            )
        assert MigrationRunner(database, default_registry()).migrate() == list(range(6, 19))
        with database.connect() as connection:
            assert connection.execute("SELECT provider_id FROM provider_connections").fetchone()[0] == (
                "openai-compatible"
            )
            assert connection.execute("SELECT provider_model_name FROM model_configurations").fetchone()[0] == (
                "provider-model-a"
            )
            assert connection.execute("SELECT COUNT(*) FROM runtime_configurations").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM application_execution_defaults").fetchone()[0] == 0
    finally:
        database.dispose()


def test_v6_upgrades_a_v5_database_with_phase_4_data_untouched(tmp_path) -> None:
    """Conversation, message, run, event, document, revision, and attachment rows survive."""
    database = SqliteDatabase(str(tmp_path / "phase4-to-v6.sqlite3"), auto_migrate=False)
    try:
        assert MigrationRunner(database, _registry_through_v5()).migrate() == [1, 2, 3, 4, 5]
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO conversations (conversation_id, title, created_at, updated_at) "
                "VALUES ('conv-1', 'C', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO messages (message_id, conversation_id, role, status, content, created_at, updated_at) "
                "VALUES ('msg-1', 'conv-1', 'user', 'complete', 'hello', "
                "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO runs (run_id, status, created_at, updated_at) "
                "VALUES ('run-1', 'completed', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO documents (document_id, title, content, content_format, created_at, updated_at) "
                "VALUES ('doc-1', 'T', '<p>x</p>', 'html', "
                "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO document_revisions (revision_id, document_id, revision_number, title, content, "
                "content_format, created_at) "
                "VALUES ('rev-1', 'doc-1', 1, 'T', '<p>x</p>', 'html', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, storage_key, "
                "owner_type, owner_id, status, created_at) "
                "VALUES ('att-1', 'report.pdf', 'application/pdf', 10, 'k1', 'document', 'doc-1', "
                "'available', '2026-01-01T00:00:00+00:00')"
            )
        assert MigrationRunner(database, default_registry()).migrate() == list(range(6, 19))
        with database.connect() as connection:
            seeded = {
                "conversations": 1,
                "messages": 1,
                "runs": 1,
                "run_events": 0,
                "documents": 1,
                "document_revisions": 1,
                "attachments": 1,
                "provider_connections": 0,
                "model_configurations": 0,
            }
            for table, expected in seeded.items():
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected, table
    finally:
        database.dispose()


def test_v6_creates_only_the_minimal_runtime_configurations_table() -> None:
    database = SqliteDatabase(":memory:")
    try:
        with database.connect() as connection:
            columns = [row["name"] for row in connection.execute('PRAGMA table_info("runtime_configurations")')]
        assert columns == [
            "id",
            "runtime_configuration_id",
            "runtime_type",
            "display_name",
            "enabled",
        ]
    finally:
        database.dispose()


def test_v6_enforces_identity_uniqueness_and_boolean_enabled(tmp_path) -> None:
    import sqlite3

    database = SqliteDatabase(":memory:")
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO runtime_configurations "
            "(runtime_configuration_id, runtime_type, display_name, enabled) VALUES (?, ?, ?, ?)",
            ("config-a", "native", "Native AVA", 1),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO runtime_configurations "
                "(runtime_configuration_id, runtime_type, display_name, enabled) VALUES (?, ?, ?, ?)",
                ("config-a", "openhands", "Duplicate", 1),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO runtime_configurations "
                "(runtime_configuration_id, runtime_type, display_name, enabled) VALUES (?, ?, ?, ?)",
                ("config-b", "native", "Bad Flag", 2),
            )
    database.dispose()


# ============================================================
# END Migration compatibility
# ============================================================


# ============================================================
# BEGIN Architecture boundaries
# ============================================================


def test_runtime_configuration_persistence_stays_out_of_execution() -> None:
    """Persisted runtime configuration is not wired into the execution boundary."""
    assert "RuntimeConfiguration" not in inspect.getsource(RunService)
    for module_source in (
        inspect.getsource(__import__("ava.runtimes.registry", fromlist=["RuntimeRegistry"])),
        inspect.getsource(__import__("ava.runtimes.resolver", fromlist=["RuntimeResolver"])),
        inspect.getsource(__import__("ava.execution.selector", fromlist=["ExecutionSelector"])),
    ):
        assert "RuntimeConfigurationRepository" not in module_source
        assert "RuntimeConfiguration" not in module_source


def test_relational_adapter_stays_inside_the_persistence_package() -> None:
    """The SQLite adapter is infrastructure-only, like every other relational adapter."""
    from ava.infrastructure.persistence.repositories import RelationalRuntimeConfigurationRepository

    assert issubclass(RelationalRuntimeConfigurationRepository, RuntimeConfigurationRepository)


def test_persisted_record_carries_no_model_provider_or_authority_fields() -> None:
    """Structural (not prose) check: the record and port name only the 5.6 fields."""
    assert [field.name for field in dataclasses.fields(RuntimeConfiguration)] == [
        "runtime_configuration_id",
        "runtime_type",
        "display_name",
        "enabled",
    ]
    declared = _declared_field_names(inspect.getsource(RuntimeConfiguration))
    port_parameters = _declared_field_names(inspect.getsource(RuntimeConfigurationRepository))
    for forbidden in (
        "model_id",
        "provider_id",
        "provider_connection_id",
        "ModelConfiguration",
        "ProviderConnection",
        "workspace",
        "tool",
        "credential",
    ):
        assert forbidden not in declared, forbidden
        assert forbidden not in port_parameters, forbidden


# ============================================================
# END Architecture boundaries
# ============================================================
