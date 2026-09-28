"""SQLite-backed model-configuration repository adapter."""

import json
import sqlite3

from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.models.model_configurations import ModelConfiguration
from ava.repositories.model_configuration_repository import ModelConfigurationRepository

_COLUMNS = "model_id, provider_connection_id, provider_model_name, display_name, hosting_mode, capabilities, enabled"


class RelationalModelConfigurationRepository(ModelConfigurationRepository):
    """SQLite implementation with explicit provider-connection validation."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, configuration: ModelConfiguration) -> ModelConfiguration:
        try:
            with self._database.transaction() as connection:
                _require_provider_connection(connection, configuration.provider_connection_id)
                connection.execute(
                    "INSERT INTO model_configurations "
                    "(model_id, provider_connection_id, provider_model_name, display_name, "
                    "hosting_mode, capabilities, enabled) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        configuration.model_id,
                        configuration.provider_connection_id,
                        configuration.provider_model_name,
                        configuration.display_name,
                        configuration.hosting_mode.value,
                        _dump_capabilities(configuration.capabilities),
                        configuration.enabled,
                    ),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Model configuration", key=configuration.model_id) from exc
        return configuration

    def get(self, model_id: str) -> ModelConfiguration | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM model_configurations WHERE model_id = ?", (model_id,)
            ).fetchone()
        return _row_to_model_configuration(row) if row is not None else None

    def list(self) -> list[ModelConfiguration]:
        with self._database.connect() as connection:
            rows = connection.execute(f"SELECT {_COLUMNS} FROM model_configurations ORDER BY id ASC").fetchall()
        return [_row_to_model_configuration(row) for row in rows]

    def update(self, configuration: ModelConfiguration) -> ModelConfiguration | None:
        with self._database.transaction() as connection:
            existing = connection.execute(
                "SELECT provider_connection_id FROM model_configurations WHERE model_id = ?", (configuration.model_id,)
            ).fetchone()
            if existing is None:
                return None
            if existing["provider_connection_id"] != configuration.provider_connection_id:
                raise ValueError("Model configuration provider_connection_id cannot change")
            connection.execute(
                "UPDATE model_configurations SET provider_model_name = ?, display_name = ?, hosting_mode = ?, "
                "capabilities = ?, enabled = ? WHERE model_id = ?",
                (configuration.provider_model_name, configuration.display_name, configuration.hosting_mode.value,
                 _dump_capabilities(configuration.capabilities), configuration.enabled, configuration.model_id),
            )
        return configuration


def _require_provider_connection(connection: sqlite3.Connection, provider_connection_id: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM provider_connections WHERE provider_connection_id = ?", (provider_connection_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown provider connection: {provider_connection_id}")


def _dump_capabilities(capabilities: ModelCapabilities) -> str:
    return json.dumps(capabilities.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _row_to_model_configuration(row: sqlite3.Row) -> ModelConfiguration:
    return ModelConfiguration(
        model_id=row["model_id"],
        provider_connection_id=row["provider_connection_id"],
        provider_model_name=row["provider_model_name"],
        display_name=row["display_name"],
        hosting_mode=ModelHostingMode(row["hosting_mode"]),
        capabilities=ModelCapabilities.model_validate(json.loads(row["capabilities"])),
        enabled=bool(row["enabled"]),
    )
