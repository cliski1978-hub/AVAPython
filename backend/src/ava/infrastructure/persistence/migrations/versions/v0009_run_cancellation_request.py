"""Migration 0009 — durable run cancellation intent."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 9
NAME = "durable run cancellation request"
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
    "cancellation_requested_at",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    # A nullable column with no default: every existing run becomes "cancellation
    # was never requested", which is the truth for a run that predates the feature.
    # There is no backfill, because inventing a request time for historical runs
    # would be fabricating evidence.
    connection.execute("ALTER TABLE runs ADD COLUMN cancellation_requested_at TEXT")
    connection.execute(
        "CREATE INDEX idx_runs_cancellation_requested ON runs (cancellation_requested_at) "
        "WHERE cancellation_requested_at IS NOT NULL"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "runs") or tuple(table_columns(connection, "runs")) != EXPECTED_COLUMNS:
        raise SchemaValidationError("runs table does not match durable run cancellation schema (version 9)")
