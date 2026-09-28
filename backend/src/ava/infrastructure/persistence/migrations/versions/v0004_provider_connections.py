"""Migration 0004 — configured provider connections.

Stores only the AVA-owned ``ProviderConnection`` record: stable connection
identity, provider adapter identity, display metadata, opaque endpoint and
credential reference, and enabled state. No credential values, model records,
runtime records, or execution defaults belong in this migration.
"""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import (
    has_unique_index_on,
    present_tables,
    table_columns,
    table_exists,
)

VERSION = 4
NAME = "provider connections"
EXPECTED_TABLES: tuple[str, ...] = ("provider_connections",)
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "provider_connections": (
        "id",
        "provider_connection_id",
        "provider_id",
        "display_name",
        "endpoint",
        "enabled",
        "credential_reference",
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
        "ava_schema_migrations",
    }
)

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE provider_connections (
        id                       INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_connection_id   TEXT NOT NULL UNIQUE,
        provider_id              TEXT NOT NULL,
        display_name             TEXT NOT NULL,
        endpoint                 TEXT NULL,
        enabled                  INTEGER NOT NULL CHECK (enabled IN (0, 1)),
        credential_reference     TEXT NULL
    )
    """,
)


def migrate_up(connection: sqlite3.Connection) -> None:
    """Apply the provider-connections table."""
    for statement in STATEMENTS:
        connection.execute(statement)


def verify_structure(connection: sqlite3.Connection) -> None:
    """Fail closed unless the version 4 table has the expected minimal shape."""
    violations = _structure_violations(connection)
    if violations:
        raise SchemaValidationError(
            f"database does not match the provider connections schema (version {VERSION}): "
            f"{'; '.join(violations)}. Refusing to verify or stamp an unknown/incompatible schema."
        )


def _structure_violations(connection: sqlite3.Connection) -> list[str]:
    violations: list[str] = []
    if not table_exists(connection, "provider_connections"):
        violations.append("missing table 'provider_connections'")
    elif tuple(table_columns(connection, "provider_connections")) != EXPECTED_COLUMNS["provider_connections"]:
        violations.append("provider_connections columns do not match expected layout")
    unexpected = [
        table
        for table in sorted(present_tables(connection))
        if table not in EXPECTED_TABLES
        and table not in _ALLOWED_COEXISTING_TABLES
        and not table.startswith("sqlite_")
    ]
    if unexpected:
        violations.append(f"unexpected tables {unexpected}")
    if not has_unique_index_on(connection, "provider_connections", ("provider_connection_id",)):
        violations.append("provider_connections has no unique index on provider_connection_id")
    return violations
