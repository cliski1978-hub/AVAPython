"""Migration 0010 — durable conversation organization metadata."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 10
NAME = "conversation organization metadata"
EXPECTED_TABLES = ("conversations",)
EXPECTED_COLUMNS = (
    "id",
    "conversation_id",
    "title",
    "created_at",
    "updated_at",
    "is_pinned",
    "is_archived",
    "folder_id",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    # SQLite applies these defaults to existing rows as well as future inserts.
    connection.execute(
        "ALTER TABLE conversations ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1))"
    )
    connection.execute(
        "ALTER TABLE conversations ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1))"
    )
    connection.execute("ALTER TABLE conversations ADD COLUMN folder_id TEXT")


def verify_structure(connection: sqlite3.Connection) -> None:
    if (
        not table_exists(connection, "conversations")
        or tuple(table_columns(connection, "conversations")) != EXPECTED_COLUMNS
    ):
        raise SchemaValidationError("conversations table does not match organization metadata schema (version 10)")
