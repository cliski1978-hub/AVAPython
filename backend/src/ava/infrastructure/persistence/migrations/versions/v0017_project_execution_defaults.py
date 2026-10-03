"""Migration 0017 — independent Project runtime/model preferences."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 17
NAME = "Project execution defaults"
EXPECTED_COLUMNS = (
    "id",
    "name",
    "description",
    "instructions",
    "is_archived",
    "created_at",
    "updated_at",
    "default_runtime_key",
    "default_model_id",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        "ALTER TABLE projects ADD COLUMN default_runtime_key TEXT NULL "
        "CHECK (default_runtime_key IS NULL OR length(trim(default_runtime_key)) > 0)"
    )
    connection.execute(
        "ALTER TABLE projects ADD COLUMN default_model_id TEXT NULL "
        "REFERENCES model_configurations(model_id) ON DELETE SET NULL "
        "CHECK (default_model_id IS NULL OR length(trim(default_model_id)) > 0)"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "projects") or tuple(table_columns(connection, "projects")) != EXPECTED_COLUMNS:
        raise SchemaValidationError("projects table does not match schema (version 17)")
