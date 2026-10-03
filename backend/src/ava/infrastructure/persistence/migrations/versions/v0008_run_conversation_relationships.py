"""Migration 0008 — durable conversation/run relationship identifiers."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 8
NAME = "durable conversation run relationships"
EXPECTED_TABLES = ("runs",)
EXPECTED_COLUMNS = (
    "run_id",
    "status",
    "created_at",
    "updated_at",
    "execution_selection",
    "conversation_id",
    "source_user_message_id",
    "assistant_message_id",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE runs ADD COLUMN conversation_id TEXT")
    connection.execute("ALTER TABLE runs ADD COLUMN source_user_message_id TEXT")
    connection.execute("ALTER TABLE runs ADD COLUMN assistant_message_id TEXT")
    connection.execute("CREATE INDEX idx_runs_conversation ON runs (conversation_id)")
    connection.execute("CREATE INDEX idx_runs_source_user_message ON runs (source_user_message_id)")
    connection.execute(
        "CREATE UNIQUE INDEX idx_runs_assistant_message ON runs (assistant_message_id) "
        "WHERE assistant_message_id IS NOT NULL"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "runs") or tuple(table_columns(connection, "runs")) != EXPECTED_COLUMNS:
        raise SchemaValidationError(
            "runs table does not match durable conversation/run relationship schema (version 8)"
        )
