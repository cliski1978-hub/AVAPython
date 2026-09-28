"""Migration 0007 — application execution defaults.

Stores the single application-wide defaults record: the three configured
identities a default run uses. Only ``default_provider_connection_id``,
``default_model_id``, and ``default_runtime_configuration_id`` are persisted;
provider adapter ids, provider-native model names, runtime types, and display
names remain owned by their source configuration records and are never
duplicated here.

The row is a singleton: ``id`` is constrained to 1, so the database itself
allows at most one defaults record. No ``AUTOINCREMENT`` key is used because a
single record has no insertion order to preserve. As elsewhere in AVA's schema,
there are no declarative foreign keys; cross-record existence, enabled-state,
and model/provider-connection compatibility are validated explicitly by the
repository implementations.
"""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import (
    present_tables,
    table_columns,
    table_exists,
)

VERSION = 7
NAME = "application execution defaults"
EXPECTED_TABLES: tuple[str, ...] = ("application_execution_defaults",)
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "application_execution_defaults": (
        "id",
        "default_provider_connection_id",
        "default_model_id",
        "default_runtime_configuration_id",
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
        "runtime_configurations",
        "ava_schema_migrations",
    }
)

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE application_execution_defaults (
        id                               INTEGER PRIMARY KEY CHECK (id = 1),
        default_provider_connection_id   TEXT NOT NULL,
        default_model_id                 TEXT NOT NULL,
        default_runtime_configuration_id TEXT NOT NULL
    )
    """,
)


def migrate_up(connection: sqlite3.Connection) -> None:
    """Apply the application-execution-defaults singleton table."""
    for statement in STATEMENTS:
        connection.execute(statement)


def verify_structure(connection: sqlite3.Connection) -> None:
    """Fail closed unless the version 7 table has the expected minimal shape."""
    violations = _structure_violations(connection)
    if violations:
        raise SchemaValidationError(
            f"database does not match the application execution defaults schema (version {VERSION}): "
            f"{'; '.join(violations)}. Refusing to verify or stamp an unknown/incompatible schema."
        )


def _structure_violations(connection: sqlite3.Connection) -> list[str]:
    violations: list[str] = []
    if not table_exists(connection, "application_execution_defaults"):
        violations.append("missing table 'application_execution_defaults'")
        return violations
    if (
        tuple(table_columns(connection, "application_execution_defaults"))
        != EXPECTED_COLUMNS["application_execution_defaults"]
    ):
        violations.append("application_execution_defaults columns do not match expected layout")
    unexpected = [
        table
        for table in sorted(present_tables(connection))
        if table not in EXPECTED_TABLES
        and table not in _ALLOWED_COEXISTING_TABLES
        and not table.startswith("sqlite_")
    ]
    if unexpected:
        violations.append(f"unexpected tables {unexpected}")
    if not _enforces_single_record(connection):
        violations.append("application_execution_defaults does not constrain the row id to 1")
    return violations


def _enforces_single_record(connection: sqlite3.Connection) -> bool:
    """Return whether the table's DDL pins the primary key to the single row id."""
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("application_execution_defaults",),
    ).fetchone()
    if row is None:
        return False
    ddl = " ".join(str(row["sql"]).split()).lower()
    return "check (id = 1)" in ddl
