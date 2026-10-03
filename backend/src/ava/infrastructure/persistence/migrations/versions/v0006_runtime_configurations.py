"""Migration 0006 — configured agent runtimes.

Stores only the AVA-owned ``RuntimeConfiguration`` record: the stable
configured-instance identity, its runtime adapter/framework type, display
metadata, and enabled state. No model, provider, provider-connection, workspace,
tool, credential, or execution-default field belongs in this migration. The
``runtime_type`` is an opaque AVA-owned adapter identifier, so it is stored
without a fixed vocabulary check; the domain record owns that validation.
"""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import (
    has_unique_index_on,
    present_tables,
    table_columns,
    table_exists,
)

VERSION = 6
NAME = "runtime configurations"
EXPECTED_TABLES: tuple[str, ...] = ("runtime_configurations",)
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "runtime_configurations": (
        "id",
        "runtime_configuration_id",
        "runtime_type",
        "display_name",
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
        "model_configurations",
        "ava_schema_migrations",
    }
)

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE runtime_configurations (
        id                         INTEGER PRIMARY KEY AUTOINCREMENT,
        runtime_configuration_id   TEXT NOT NULL UNIQUE,
        runtime_type               TEXT NOT NULL,
        display_name               TEXT NOT NULL,
        enabled                    INTEGER NOT NULL CHECK (enabled IN (0, 1))
    )
    """,
)


def migrate_up(connection: sqlite3.Connection) -> None:
    """Apply the runtime-configurations table."""
    for statement in STATEMENTS:
        connection.execute(statement)


def verify_structure(connection: sqlite3.Connection) -> None:
    """Fail closed unless the version 6 table has the expected minimal shape."""
    violations = _structure_violations(connection)
    if violations:
        raise SchemaValidationError(
            f"database does not match the runtime configurations schema (version {VERSION}): "
            f"{'; '.join(violations)}. Refusing to verify or stamp an unknown/incompatible schema."
        )


def _structure_violations(connection: sqlite3.Connection) -> list[str]:
    violations: list[str] = []
    if not table_exists(connection, "runtime_configurations"):
        violations.append("missing table 'runtime_configurations'")
    elif tuple(table_columns(connection, "runtime_configurations")) != EXPECTED_COLUMNS["runtime_configurations"]:
        violations.append("runtime_configurations columns do not match expected layout")
    unexpected = [
        table
        for table in sorted(present_tables(connection))
        if table not in EXPECTED_TABLES and table not in _ALLOWED_COEXISTING_TABLES and not table.startswith("sqlite_")
    ]
    if unexpected:
        violations.append(f"unexpected tables {unexpected}")
    if not has_unique_index_on(connection, "runtime_configurations", ("runtime_configuration_id",)):
        violations.append("runtime_configurations has no unique index on runtime_configuration_id")
    return violations
