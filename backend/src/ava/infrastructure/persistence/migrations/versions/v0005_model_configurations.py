"""Migration 0005 — configured models associated with provider connections."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import (
    has_unique_index_on,
    present_tables,
    table_columns,
    table_exists,
)

VERSION = 5
NAME = "model configurations"
EXPECTED_TABLES: tuple[str, ...] = ("model_configurations",)
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "model_configurations": (
        "id",
        "model_id",
        "provider_connection_id",
        "provider_model_name",
        "display_name",
        "hosting_mode",
        "capabilities",
        "enabled",
    ),
}
_ALLOWED_COEXISTING_TABLES = frozenset(
    {
        "runs",
        "run_events",
        "conversations",
        "messages",
        "documents",
        "document_revisions",
        "attachments",
        "provider_connections",
        "ava_schema_migrations",
    }
)
STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE model_configurations (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        model_id               TEXT NOT NULL UNIQUE,
        provider_connection_id TEXT NOT NULL,
        provider_model_name    TEXT NOT NULL,
        display_name           TEXT NOT NULL,
        hosting_mode           TEXT NOT NULL CHECK (hosting_mode IN ('local', 'company_hosted', 'external')),
        capabilities           TEXT NOT NULL,
        enabled                INTEGER NOT NULL CHECK (enabled IN (0, 1))
    )
    """,
)


def migrate_up(connection: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        connection.execute(statement)


def verify_structure(connection: sqlite3.Connection) -> None:
    violations: list[str] = []
    if not table_exists(connection, "model_configurations"):
        violations.append("missing table 'model_configurations'")
    elif tuple(table_columns(connection, "model_configurations")) != EXPECTED_COLUMNS["model_configurations"]:
        violations.append("model_configurations columns do not match expected layout")
    unexpected = [
        table
        for table in sorted(present_tables(connection))
        if table not in EXPECTED_TABLES and table not in _ALLOWED_COEXISTING_TABLES and not table.startswith("sqlite_")
    ]
    if unexpected:
        violations.append(f"unexpected tables {unexpected}")
    if not has_unique_index_on(connection, "model_configurations", ("model_id",)):
        violations.append("model_configurations has no unique index on model_id")
    if violations:
        raise SchemaValidationError(
            f"database does not match the model configurations schema (version {VERSION}): {'; '.join(violations)}"
        )
