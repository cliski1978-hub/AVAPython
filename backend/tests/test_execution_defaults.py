"""Phase 5.8 application-execution-defaults domain and repository tests."""

import ast
import inspect
from collections.abc import Callable
from dataclasses import dataclass, fields

import pytest

from ava.configuration.execution_defaults import ApplicationExecutionDefaults
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
    v0005_model_configurations,
    v0006_runtime_configurations,
)
from ava.models.model_configurations import ModelConfiguration
from ava.models.provider_connections import ProviderConnection
from ava.repositories import ExecutionDefaultsRepository
from ava.runtimes.configurations import RuntimeConfiguration
from ava.services.execution_defaults_store import ExecutionDefaultsStore
from ava.services.model_configuration_store import ModelConfigurationStore
from ava.services.provider_connection_store import ProviderConnectionStore
from ava.services.runtime_configuration_store import RuntimeConfigurationStore

CONNECTION_A = "connection-a"
CONNECTION_B = "connection-b"
MODEL_ON_A = "ava.model.on-a"
MODEL_ON_B = "ava.model.on-b"
RUNTIME_NATIVE = "native-local"
RUNTIME_OPENHANDS = "openhands-local"


def _connection(connection_id: str = CONNECTION_A, **changes: object) -> ProviderConnection:
    values: dict[str, object] = {
        "provider_connection_id": connection_id,
        "provider_id": "openai-compatible",
        "display_name": f"Connection {connection_id[-1].upper()}",
        "enabled": True,
    }
    values.update(changes)
    return ProviderConnection(**values)  # type: ignore[arg-type]


def _model(model_id: str = MODEL_ON_A, **changes: object) -> ModelConfiguration:
    values: dict[str, object] = {
        "model_id": model_id,
        "provider_connection_id": CONNECTION_A,
        "provider_model_name": "provider-model",
        "display_name": "Model",
        "hosting_mode": ModelHostingMode.COMPANY_HOSTED,
        "capabilities": ModelCapabilities(chat=True),
        "enabled": True,
    }
    values.update(changes)
    return ModelConfiguration(**values)  # type: ignore[arg-type]


def _runtime(runtime_configuration_id: str = RUNTIME_NATIVE, **changes: object) -> RuntimeConfiguration:
    values: dict[str, object] = {
        "runtime_configuration_id": runtime_configuration_id,
        "runtime_type": "native",
        "display_name": "Native AVA",
        "enabled": True,
    }
    values.update(changes)
    return RuntimeConfiguration(**values)  # type: ignore[arg-type]


def _defaults(**changes: object) -> ApplicationExecutionDefaults:
    values: dict[str, object] = {
        "default_provider_connection_id": CONNECTION_A,
        "default_model_id": MODEL_ON_A,
        "default_runtime_configuration_id": RUNTIME_NATIVE,
    }
    values.update(changes)
    return ApplicationExecutionDefaults(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Setup:
    defaults: ExecutionDefaultsRepository
    providers: object
    models: object
    runtimes: object
    dispose: Callable[[], None]


@pytest.fixture(params=["memory", "relational"])
def repositories(request: pytest.FixtureRequest) -> Setup:
    if request.param == "memory":
        providers = ProviderConnectionStore()
        models = ModelConfigurationStore(provider_connections=providers)
        runtimes = RuntimeConfigurationStore()
        setup = Setup(
            ExecutionDefaultsStore(
                provider_connections=providers,
                model_configurations=models,
                runtime_configurations=runtimes,
            ),
            providers,
            models,
            runtimes,
            lambda: None,
        )
    else:
        bundle = create_relational_repositories(":memory:")
        setup = Setup(
            bundle.execution_defaults_repository,
            bundle.provider_connection_repository,
            bundle.model_configuration_repository,
            bundle.runtime_configuration_repository,
            bundle.dispose,
        )
    setup.providers.create(_connection(CONNECTION_A))  # type: ignore[attr-defined]
    setup.providers.create(_connection(CONNECTION_B))  # type: ignore[attr-defined]
    setup.models.create(_model(MODEL_ON_A))  # type: ignore[attr-defined]
    setup.models.create(_model(MODEL_ON_B, provider_connection_id=CONNECTION_B))  # type: ignore[attr-defined]
    setup.runtimes.create(_runtime(RUNTIME_NATIVE))  # type: ignore[attr-defined]
    setup.runtimes.create(_runtime(RUNTIME_OPENHANDS, runtime_type="openhands", display_name="OpenHands"))  # type: ignore[attr-defined]
    yield setup
    setup.dispose()


# ============================================================
# BEGIN Domain
# ============================================================


def test_defaults_reference_only_the_three_configured_identities() -> None:
    assert [field.name for field in fields(ApplicationExecutionDefaults)] == [
        "default_provider_connection_id",
        "default_model_id",
        "default_runtime_configuration_id",
    ]


@pytest.mark.parametrize(
    "field",
    [
        "default_provider_connection_id",
        "default_model_id",
        "default_runtime_configuration_id",
    ],
)
def test_blank_references_are_rejected(field: str) -> None:
    with pytest.raises(ValueError, match=f"{field} must be a non-blank string"):
        _defaults(**{field: "   "})


# ============================================================
# END Domain
# ============================================================


# ============================================================
# BEGIN Repository contract
# ============================================================


def test_port_is_singular_not_a_collection() -> None:
    """The port is get/set; there is no create/list/delete for a singleton."""
    with pytest.raises(TypeError):
        ExecutionDefaultsRepository()  # type: ignore[abstract]
    public = {name for name in dir(ExecutionDefaultsRepository) if not name.startswith("_")}
    assert public == {"get", "set"}


def test_port_is_abstract_and_both_adapters_implement_it() -> None:
    from ava.infrastructure.persistence.repositories import RelationalExecutionDefaultsRepository

    providers = ProviderConnectionStore()
    store = ExecutionDefaultsStore(
        provider_connections=providers,
        model_configurations=ModelConfigurationStore(provider_connections=providers),
        runtime_configurations=RuntimeConfigurationStore(),
    )
    assert isinstance(store, ExecutionDefaultsRepository)
    assert issubclass(RelationalExecutionDefaultsRepository, ExecutionDefaultsRepository)


def test_get_returns_none_before_set(repositories: Setup) -> None:
    assert repositories.defaults.get() is None


def test_set_then_get_round_trips(repositories: Setup) -> None:
    assert repositories.defaults.set(_defaults()) == _defaults()
    assert repositories.defaults.get() == _defaults()


def test_set_replaces_the_previous_defaults(repositories: Setup) -> None:
    repositories.defaults.set(_defaults())
    replaced = _defaults(
        default_provider_connection_id=CONNECTION_B,
        default_model_id=MODEL_ON_B,
        default_runtime_configuration_id=RUNTIME_OPENHANDS,
    )
    assert repositories.defaults.set(replaced) == replaced
    assert repositories.defaults.get() == replaced


def test_repeated_set_keeps_a_single_record(repositories: Setup) -> None:
    for runtime_id in (RUNTIME_NATIVE, RUNTIME_OPENHANDS, RUNTIME_NATIVE):
        repositories.defaults.set(_defaults(default_runtime_configuration_id=runtime_id))
    stored = repositories.defaults.get()
    assert stored == _defaults(default_runtime_configuration_id=RUNTIME_NATIVE)
    if isinstance(repositories.defaults, object) and hasattr(repositories.defaults, "_database"):
        with repositories.defaults._database.connect() as connection:  # type: ignore[attr-defined]
            count = connection.execute("SELECT COUNT(*) FROM application_execution_defaults").fetchone()[0]
        assert count == 1


def test_a_failed_set_leaves_the_previous_defaults_intact(repositories: Setup) -> None:
    repositories.defaults.set(_defaults())
    with pytest.raises(ValueError):
        repositories.defaults.set(_defaults(default_model_id="unknown-model"))
    assert repositories.defaults.get() == _defaults()


# ============================================================
# END Repository contract
# ============================================================


# ============================================================
# BEGIN Reference validation
# ============================================================


def test_missing_provider_connection_is_rejected(repositories: Setup) -> None:
    with pytest.raises(ValueError, match="Unknown provider connection: missing-connection"):
        repositories.defaults.set(_defaults(default_provider_connection_id="missing-connection"))


def test_missing_model_is_rejected(repositories: Setup) -> None:
    with pytest.raises(ValueError, match="Unknown model configuration: missing-model"):
        repositories.defaults.set(_defaults(default_model_id="missing-model"))


def test_missing_runtime_configuration_is_rejected(repositories: Setup) -> None:
    with pytest.raises(
        ValueError, match="Unknown runtime configuration: missing-runtime"
    ):
        repositories.defaults.set(_defaults(default_runtime_configuration_id="missing-runtime"))


def test_disabled_provider_connection_is_rejected(repositories: Setup) -> None:
    repositories.providers.update(_connection(CONNECTION_A, enabled=False))  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="Provider connection is disabled: connection-a"):
        repositories.defaults.set(_defaults())


def test_disabled_model_is_rejected(repositories: Setup) -> None:
    repositories.models.update(_model(MODEL_ON_A, enabled=False))  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="Model configuration is disabled: ava.model.on-a"):
        repositories.defaults.set(_defaults())


def test_disabled_runtime_configuration_is_rejected(repositories: Setup) -> None:
    repositories.runtimes.update(_runtime(RUNTIME_NATIVE, enabled=False))  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="Runtime configuration is disabled: native-local"):
        repositories.defaults.set(_defaults())


def test_model_belonging_to_a_different_connection_is_rejected(repositories: Setup) -> None:
    """A model hosted by connection B cannot be the default for connection A."""
    with pytest.raises(
        ValueError,
        match=r"Model configuration ava\.model\.on-b does not belong to provider connection connection-a",
    ):
        repositories.defaults.set(_defaults(default_model_id=MODEL_ON_B))


def test_compatible_defaults_are_accepted(repositories: Setup) -> None:
    b_defaults = _defaults(
        default_provider_connection_id=CONNECTION_B,
        default_model_id=MODEL_ON_B,
        default_runtime_configuration_id=RUNTIME_OPENHANDS,
    )
    assert repositories.defaults.set(b_defaults) == b_defaults
    assert repositories.defaults.get() == b_defaults


def test_validation_never_silently_falls_back(repositories: Setup) -> None:
    """A rejected set stores nothing and substitutes nothing."""
    with pytest.raises(ValueError):
        repositories.defaults.set(_defaults(default_model_id=MODEL_ON_B))
    assert repositories.defaults.get() is None


# ============================================================
# END Reference validation
# ============================================================


# ============================================================
# BEGIN Durability
# ============================================================


def _seed(database_url: str) -> None:
    bundle = create_relational_repositories(database_url)
    bundle.provider_connection_repository.create(_connection(CONNECTION_A))
    bundle.model_configuration_repository.create(_model(MODEL_ON_A))
    bundle.runtime_configuration_repository.create(_runtime(RUNTIME_NATIVE))
    bundle.execution_defaults_repository.set(_defaults())
    bundle.dispose()


def test_defaults_survive_reopen(tmp_path) -> None:
    database_url = str(tmp_path / "ava.sqlite3")
    _seed(database_url)
    second = create_relational_repositories(database_url)
    try:
        assert second.execution_defaults_repository.get() == _defaults()
    finally:
        second.dispose()


def test_replaced_defaults_survive_reopen(tmp_path) -> None:
    database_url = str(tmp_path / "ava.sqlite3")
    bundle = create_relational_repositories(database_url)
    bundle.provider_connection_repository.create(_connection(CONNECTION_B))
    bundle.model_configuration_repository.create(_model(MODEL_ON_B, provider_connection_id=CONNECTION_B))
    bundle.runtime_configuration_repository.create(
        _runtime(RUNTIME_OPENHANDS, runtime_type="openhands", display_name="OpenHands")
    )
    bundle.execution_defaults_repository.set(
        _defaults(
            default_provider_connection_id=CONNECTION_B,
            default_model_id=MODEL_ON_B,
            default_runtime_configuration_id=RUNTIME_OPENHANDS,
        )
    )
    bundle.dispose()
    second = create_relational_repositories(database_url)
    try:
        assert second.execution_defaults_repository.get() == _defaults(
            default_provider_connection_id=CONNECTION_B,
            default_model_id=MODEL_ON_B,
            default_runtime_configuration_id=RUNTIME_OPENHANDS,
        )
    finally:
        second.dispose()


def test_defaults_read_back_absent_across_reopen_when_never_set(tmp_path) -> None:
    """Absence is itself durable state, not just an uninitialized in-memory value."""
    database_url = str(tmp_path / "ava.sqlite3")
    first = create_relational_repositories(database_url)
    assert first.execution_defaults_repository.get() is None
    first.dispose()
    second = create_relational_repositories(database_url)
    try:
        assert second.execution_defaults_repository.get() is None
    finally:
        second.dispose()


# ============================================================
# END Durability
# ============================================================


# ============================================================
# BEGIN Migration compatibility
# ============================================================


def _registry_through_v6() -> MigrationRegistry:
    registry = MigrationRegistry()
    for version in (
        v0001_initial_schema,
        v0002_document_revisions,
        v0003_attachments,
        v0004_provider_connections,
        v0005_model_configurations,
        v0006_runtime_configurations,
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


def test_v7_upgrades_a_v6_database_and_preserves_every_configured_record(tmp_path) -> None:
    database = SqliteDatabase(str(tmp_path / "phase5-v6.sqlite3"), auto_migrate=False)
    try:
        assert MigrationRunner(database, _registry_through_v6()).migrate() == [1, 2, 3, 4, 5, 6]
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO provider_connections "
                "(provider_connection_id, provider_id, display_name, endpoint, enabled, credential_reference) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (CONNECTION_A, "openai-compatible", "Connection A", "http://host/v1", True, "ENV:AVA_TEST"),
            )
            connection.execute(
                "INSERT INTO model_configurations "
                "(model_id, provider_connection_id, provider_model_name, display_name, hosting_mode, "
                "capabilities, enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (MODEL_ON_A, CONNECTION_A, "provider-model", "Model", "company_hosted", '{"chat":true}', True),
            )
            connection.execute(
                "INSERT INTO runtime_configurations "
                "(runtime_configuration_id, runtime_type, display_name, enabled) VALUES (?, ?, ?, ?)",
                (RUNTIME_NATIVE, "native", "Native AVA", True),
            )
        assert MigrationRunner(database, default_registry()).migrate() == [7, 8, 9]
        with database.connect() as connection:
            assert connection.execute(
                "SELECT provider_id, endpoint, credential_reference FROM provider_connections"
            ).fetchone()[:] == ("openai-compatible", "http://host/v1", "ENV:AVA_TEST")
            assert connection.execute(
                "SELECT provider_connection_id, provider_model_name FROM model_configurations"
            ).fetchone()[:] == (CONNECTION_A, "provider-model")
            assert connection.execute(
                "SELECT runtime_type, display_name FROM runtime_configurations"
            ).fetchone()[:] == ("native", "Native AVA")
            assert connection.execute("SELECT COUNT(*) FROM application_execution_defaults").fetchone()[0] == 0
    finally:
        database.dispose()


def test_v7_upgrades_a_v6_database_with_phase_4_data_untouched(tmp_path) -> None:
    database = SqliteDatabase(str(tmp_path / "phase4-to-v7.sqlite3"), auto_migrate=False)
    try:
        assert MigrationRunner(database, _registry_through_v6()).migrate() == [1, 2, 3, 4, 5, 6]
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO conversations (conversation_id, title, created_at, updated_at) "
                "VALUES ('conv-1', 'C', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
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
        assert MigrationRunner(database, default_registry()).migrate() == [7, 8, 9]
        with database.connect() as connection:
            for table in ("conversations", "messages", "runs", "run_events", "documents"):
                expected = 0 if table in {"messages", "run_events"} else 1
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected, table
    finally:
        database.dispose()


def test_v7_table_stores_only_the_three_configured_identities() -> None:
    database = SqliteDatabase(":memory:")
    try:
        with database.connect() as connection:
            columns = [
                row["name"] for row in connection.execute('PRAGMA table_info("application_execution_defaults")')
            ]
        assert columns == [
            "id",
            "default_provider_connection_id",
            "default_model_id",
            "default_runtime_configuration_id",
        ]
    finally:
        database.dispose()


def test_v7_table_rejects_a_second_row_at_the_database_level() -> None:
    """The single-record rule is a database constraint, not only application logic."""
    import sqlite3

    database = SqliteDatabase(":memory:")
    try:
        insert = (
            "INSERT INTO application_execution_defaults "
            "(id, default_provider_connection_id, default_model_id, default_runtime_configuration_id) "
            "VALUES (?, ?, ?, ?)"
        )
        with database.connect() as connection:
            connection.execute(insert, (1, CONNECTION_A, MODEL_ON_A, RUNTIME_NATIVE))
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(insert, (2, CONNECTION_B, MODEL_ON_B, RUNTIME_OPENHANDS))
    finally:
        database.dispose()


def test_defaults_table_does_not_duplicate_adapter_or_type_metadata() -> None:
    database = SqliteDatabase(":memory:")
    try:
        with database.connect() as connection:
            ddl = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("application_execution_defaults",),
            ).fetchone()[0]
        for forbidden in ("provider_id", "provider_model_name", "runtime_type", "display_name", "enabled"):
            assert forbidden not in ddl, forbidden
    finally:
        database.dispose()


# ============================================================
# END Migration compatibility
# ============================================================


# ============================================================
# BEGIN Architecture boundaries
# ============================================================


def _declared_names(source: str) -> set[str]:
    """Return annotated attributes and parameter names, ignoring docstring prose."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument in [*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs]:
                names.add(argument.arg)
    return names


def test_defaults_never_name_adapter_or_type_identities() -> None:
    declared = _declared_names(inspect.getsource(ApplicationExecutionDefaults))
    for forbidden in ("provider_id", "provider_model_name", "runtime_type", "runtime_id"):
        assert forbidden not in declared, forbidden


def test_defaults_domain_owns_no_user_workspace_or_routing_state() -> None:
    declared = _declared_names(inspect.getsource(ApplicationExecutionDefaults))
    for forbidden in (
        "user_id",
        "conversation_id",
        "workspace_id",
        "tool_permissions",
        "fallback",
        "routing",
        "weight",
    ):
        assert forbidden not in declared, forbidden


def test_run_service_and_execution_selection_remain_unaware_of_persisted_defaults() -> None:
    from ava.execution.selector import ExecutionSelector
    from ava.services.run_service import RunService

    for target in (RunService, ExecutionSelector):
        source = inspect.getsource(target)
        assert "ApplicationExecutionDefaults" not in source
        assert "ExecutionDefaultsRepository" not in source


def test_execution_profile_contract_is_unchanged() -> None:
    """ExecutionProfile stays a bootstrap/discovery preset over adapter keys."""
    from ava.contracts.responses import ExecutionProfile

    assert [field for field in ExecutionProfile.model_fields] == [
        "id",
        "name",
        "description",
        "runtime_id",
        "model_provider_id",
    ]


def test_persisted_defaults_are_not_exposed_through_execution_discovery() -> None:
    """No execution-profile or discovery response gained a persisted default."""
    from ava.contracts.responses import ExecutionProfile, ExecutionProfileDiscoveryResponse

    assert "default_provider_connection_id" not in ExecutionProfile.model_fields
    assert "default_runtime_configuration_id" not in ExecutionProfile.model_fields
    assert set(ExecutionProfileDiscoveryResponse.model_fields) == {
        "contract_version",
        "default_profile_id",
        "profiles",
    }


# ============================================================
# END Architecture boundaries
# ============================================================
