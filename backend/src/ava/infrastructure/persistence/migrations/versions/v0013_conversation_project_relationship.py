"""Migration 0013 — nullable Project membership for conversations."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 13
NAME = "conversation Project relationship"
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
    "project_id",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    # Match the app-enforced Folder relationship; nullable ALTER TABLE
    # preserves legacy conversations and does not rebuild the table.
    connection.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT")


def verify_structure(connection: sqlite3.Connection) -> None:
    if (
        not table_exists(connection, "conversations")
        or tuple(table_columns(connection, "conversations")) != EXPECTED_COLUMNS
    ):
        raise SchemaValidationError("conversations table does not match Project relationship schema (version 13)")
