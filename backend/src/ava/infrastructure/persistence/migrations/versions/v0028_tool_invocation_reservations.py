"""Durable normalized-tool invocation lifecycle records."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import (
    has_named_index,
    has_unique_index_on,
    table_columns,
)

VERSION = 28
NAME = "durable tool invocation reservations"


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE tool_invocation_reservations (
            invocation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
            tool_id TEXT NOT NULL,
            tool_version TEXT NOT NULL,
            operation_fingerprint TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            execution_context_ref TEXT NOT NULL,
            authority_revision_ref TEXT NOT NULL,
            configuration_revision_ref TEXT NOT NULL,
            execution_mode TEXT NOT NULL CHECK(execution_mode IN ('chat','plan','agent')),
            state TEXT NOT NULL CHECK(state IN (
                'reserved','executing','completed','failed','cancelled','indeterminate'
            )),
            revision INTEGER NOT NULL CHECK(revision >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            result_status TEXT,
            error_code TEXT,
            reconciliation_status TEXT NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX ix_tool_invocation_reservations_run_created "
        "ON tool_invocation_reservations(run_id, created_at, invocation_id)"
    )
    connection.execute(
        "CREATE INDEX ix_tool_invocation_reservations_state ON tool_invocation_reservations(state, updated_at)"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    required = {
        "invocation_id",
        "run_id",
        "tool_id",
        "tool_version",
        "operation_fingerprint",
        "workspace_id",
        "execution_context_ref",
        "authority_revision_ref",
        "configuration_revision_ref",
        "execution_mode",
        "state",
        "revision",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "result_status",
        "error_code",
        "reconciliation_status",
    }
    if not required.issubset(table_columns(connection, "tool_invocation_reservations")):
        raise SchemaValidationError("Tool invocation reservation schema is incomplete")
    if not has_unique_index_on(connection, "tool_invocation_reservations", ("invocation_id",)):
        raise SchemaValidationError("Tool invocation IDs are not unique")
    if not has_named_index(connection, "tool_invocation_reservations", "ix_tool_invocation_reservations_run_created"):
        raise SchemaValidationError("Tool invocation Run history index is missing")
    if not has_named_index(connection, "tool_invocation_reservations", "ix_tool_invocation_reservations_state"):
        raise SchemaValidationError("Tool invocation recovery index is missing")
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tool_invocation_reservations'"
    ).fetchone()
    ddl = "".join(str(row["sql"]).lower().split()) if row else ""
    if (
        "referencesruns(run_id)ondeleterestrict" not in ddl
        or "check(revision>=0)" not in ddl
        or "check(statein('reserved','executing','completed','failed','cancelled','indeterminate'))" not in ddl
        or "check(execution_modein('chat','plan','agent'))" not in ddl
    ):
        raise SchemaValidationError("Tool invocation Run relationship or revision constraint is missing")
