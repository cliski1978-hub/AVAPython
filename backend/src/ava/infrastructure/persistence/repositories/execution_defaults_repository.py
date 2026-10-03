"""SQLite-backed application-execution-defaults repository adapter."""

import sqlite3

from ava.configuration.execution_defaults import (
    ApplicationExecutionDefaults,
    validate_execution_defaults,
)
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.repositories.execution_defaults_repository import ExecutionDefaultsRepository
from ava.repositories.model_configuration_repository import ModelConfigurationRepository
from ava.repositories.provider_connection_repository import ProviderConnectionRepository
from ava.repositories.runtime_configuration_repository import RuntimeConfigurationRepository

_COLUMNS = "default_provider_connection_id, default_model_id, default_runtime_configuration_id"
_SINGLETON_ID = 1


class RelationalExecutionDefaultsRepository(ExecutionDefaultsRepository):
    """SQLite implementation storing the one application-wide defaults row.

    The table is a fixed single-row record: ``id`` is constrained to 1, so the
    database itself guarantees at most one defaults record. Only the three
    configured identities are stored; provider adapters, provider-native model
    names, runtime types, and display names stay owned by their source records.
    """

    def __init__(
        self,
        *,
        database: SqliteDatabase,
        provider_connections: ProviderConnectionRepository,
        model_configurations: ModelConfigurationRepository,
        runtime_configurations: RuntimeConfigurationRepository,
    ) -> None:
        self._database = database
        self._provider_connections = provider_connections
        self._model_configurations = model_configurations
        self._runtime_configurations = runtime_configurations

    def get(self) -> ApplicationExecutionDefaults | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM application_execution_defaults WHERE id = ?",
                (_SINGLETON_ID,),
            ).fetchone()
        return _row_to_execution_defaults(row) if row is not None else None

    def set(self, defaults: ApplicationExecutionDefaults) -> ApplicationExecutionDefaults:
        with self._database.transaction() as connection:
            validate_execution_defaults(
                defaults=defaults,
                provider_connection=self._provider_connections.get(defaults.default_provider_connection_id),
                model_configuration=self._model_configurations.get(defaults.default_model_id),
                runtime_configuration=self._runtime_configurations.get(defaults.default_runtime_configuration_id),
            )
            values = (
                defaults.default_provider_connection_id,
                defaults.default_model_id,
                defaults.default_runtime_configuration_id,
            )
            try:
                updated = connection.execute(
                    "UPDATE application_execution_defaults "
                    "SET default_provider_connection_id = ?, default_model_id = ?, "
                    "default_runtime_configuration_id = ? WHERE id = ?",
                    (*values, _SINGLETON_ID),
                ).rowcount
                if not updated:
                    connection.execute(
                        "INSERT INTO application_execution_defaults "
                        "(id, default_provider_connection_id, default_model_id, "
                        "default_runtime_configuration_id) VALUES (?, ?, ?, ?)",
                        (_SINGLETON_ID, *values),
                    )
            except sqlite3.Error as exc:
                raise translate_database_error(
                    exc, entity="Application execution defaults", key=str(_SINGLETON_ID)
                ) from exc
        return defaults


def _row_to_execution_defaults(row: sqlite3.Row) -> ApplicationExecutionDefaults:
    return ApplicationExecutionDefaults(
        default_provider_connection_id=row["default_provider_connection_id"],
        default_model_id=row["default_model_id"],
        default_runtime_configuration_id=row["default_runtime_configuration_id"],
    )
