import json

from ava.contracts.tool_features import ToolFeatureConfiguration
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.repositories.tool_feature_repository import ToolFeatureConflictError, ToolFeatureRepository


class RelationalToolFeatureRepository(ToolFeatureRepository):
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def get(self) -> ToolFeatureConfiguration | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM tool_feature_configuration WHERE id = 1").fetchone()
        if row is None:
            return None
        if row["framework_enabled"] not in (0, 1):
            raise ValueError("invalid framework gate")
        return ToolFeatureConfiguration.model_validate(
            {
                "framework_enabled": row["framework_enabled"] == 1,
                "enabled_tool_ids": json.loads(row["enabled_tool_ids"]),
                "configuration_version": row["configuration_version"],
            }
        )

    def compare_and_set(self, expected_version: int, configuration: ToolFeatureConfiguration) -> None:
        if configuration.configuration_version != expected_version + 1:
            raise ValueError("configuration version must advance by one")
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT configuration_version FROM tool_feature_configuration WHERE id = 1"
            ).fetchone()
            version = row["configuration_version"] if row else 0
            if version != expected_version:
                raise ToolFeatureConflictError("Feature configuration changed; reload before saving.")
            connection.execute(
                "INSERT INTO tool_feature_configuration "
                "(id, framework_enabled, enabled_tool_ids, configuration_version) "
                "VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET framework_enabled=excluded.framework_enabled, "
                "enabled_tool_ids=excluded.enabled_tool_ids, configuration_version=excluded.configuration_version",
                (
                    int(configuration.framework_enabled),
                    json.dumps(configuration.enabled_tool_ids),
                    configuration.configuration_version,
                ),
            )
