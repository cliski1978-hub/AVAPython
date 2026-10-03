"""SQLite-backed runtime-configuration repository adapter."""

import sqlite3

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.repositories.runtime_configuration_repository import RuntimeConfigurationRepository
from ava.runtimes.configurations import RuntimeConfiguration

_COLUMNS = "runtime_configuration_id, runtime_type, display_name, enabled"


class RelationalRuntimeConfigurationRepository(RuntimeConfigurationRepository):
    """SQLite implementation of AVA's runtime-configuration persistence port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, configuration: RuntimeConfiguration) -> RuntimeConfiguration:
        try:
            with self._database.transaction() as database_connection:
                database_connection.execute(
                    "INSERT INTO runtime_configurations "
                    "(runtime_configuration_id, runtime_type, display_name, enabled) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        configuration.runtime_configuration_id,
                        configuration.runtime_type,
                        configuration.display_name,
                        configuration.enabled,
                    ),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(
                exc, entity="Runtime configuration", key=configuration.runtime_configuration_id
            ) from exc
        return configuration

    def get(self, runtime_configuration_id: str) -> RuntimeConfiguration | None:
        with self._database.connect() as database_connection:
            row = database_connection.execute(
                f"SELECT {_COLUMNS} FROM runtime_configurations WHERE runtime_configuration_id = ?",
                (runtime_configuration_id,),
            ).fetchone()
        return _row_to_runtime_configuration(row) if row is not None else None

    def list(self) -> list[RuntimeConfiguration]:
        with self._database.connect() as database_connection:
            rows = database_connection.execute(
                f"SELECT {_COLUMNS} FROM runtime_configurations ORDER BY id ASC"
            ).fetchall()
        return [_row_to_runtime_configuration(row) for row in rows]

    def update(self, configuration: RuntimeConfiguration) -> RuntimeConfiguration | None:
        with self._database.transaction() as database_connection:
            existing = database_connection.execute(
                "SELECT runtime_type FROM runtime_configurations WHERE runtime_configuration_id = ?",
                (configuration.runtime_configuration_id,),
            ).fetchone()
            if existing is None:
                return None
            if existing["runtime_type"] != configuration.runtime_type:
                raise ValueError("Runtime configuration runtime_type cannot change")
            database_connection.execute(
                "UPDATE runtime_configurations SET display_name = ?, enabled = ? WHERE runtime_configuration_id = ?",
                (configuration.display_name, configuration.enabled, configuration.runtime_configuration_id),
            )
        return configuration


def _row_to_runtime_configuration(row: sqlite3.Row) -> RuntimeConfiguration:
    return RuntimeConfiguration(
        runtime_configuration_id=row["runtime_configuration_id"],
        runtime_type=row["runtime_type"],
        display_name=row["display_name"],
        enabled=bool(row["enabled"]),
    )
