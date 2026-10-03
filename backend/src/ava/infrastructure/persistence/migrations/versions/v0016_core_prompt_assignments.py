"""Migration 0016 — explicit scoped CORE prompt assignments."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 16
NAME = "Scoped CORE prompt assignments"
EXPECTED_TABLES = ("core_prompt_assignments",)
EXPECTED_COLUMNS = ("id", "core_prompt_id", "scope_type", "scope_id", "mode", "created_at", "updated_at")


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE core_prompt_assignments (
            id TEXT PRIMARY KEY,
            core_prompt_id TEXT NOT NULL REFERENCES core_prompts(id) ON DELETE CASCADE,
            scope_type TEXT NOT NULL CHECK (scope_type IN (
                'global', 'application', 'project', 'folder', 'conversation',
                'runtime', 'capability', 'model_compatibility'
            )),
            scope_id TEXT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('enable', 'disable')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK ((scope_type = 'global' AND scope_id IS NULL) OR
                   (scope_type != 'global' AND scope_id IS NOT NULL AND length(trim(scope_id)) > 0))
        )"""
    )
    connection.execute(
        "CREATE UNIQUE INDEX ux_core_prompt_assignment_global "
        "ON core_prompt_assignments(core_prompt_id) WHERE scope_type = 'global'"
    )
    connection.execute(
        "CREATE UNIQUE INDEX ux_core_prompt_assignment_target "
        "ON core_prompt_assignments(core_prompt_id, scope_type, scope_id) WHERE scope_type != 'global'"
    )
    connection.execute(
        "CREATE INDEX ix_core_prompt_assignments_prompt_order "
        "ON core_prompt_assignments(core_prompt_id, scope_type, scope_id, created_at, id)"
    )
    connection.execute(
        "CREATE INDEX ix_core_prompt_assignments_scope_order "
        "ON core_prompt_assignments(scope_type, scope_id, created_at, id)"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if (
        not table_exists(connection, "core_prompt_assignments")
        or tuple(table_columns(connection, "core_prompt_assignments")) != EXPECTED_COLUMNS
    ):
        raise SchemaValidationError("core_prompt_assignments table does not match schema (version 16)")
    indexes = {row["name"] for row in connection.execute("PRAGMA index_list(core_prompt_assignments)")}
    expected_indexes = {
        "ux_core_prompt_assignment_global",
        "ux_core_prompt_assignment_target",
        "ix_core_prompt_assignments_prompt_order",
        "ix_core_prompt_assignments_scope_order",
    }
    if not expected_indexes.issubset(indexes):
        raise SchemaValidationError("core_prompt_assignments indexes are incomplete (version 16)")
