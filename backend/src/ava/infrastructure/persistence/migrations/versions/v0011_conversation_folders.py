"""Migration 0011 — durable conversation folder metadata."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 11
NAME = "conversation folders"
EXPECTED_TABLES = ("conversation_folders",)
EXPECTED_COLUMNS = ("id", "name", "created_at", "updated_at")


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE conversation_folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX idx_conversation_folders_name ON conversation_folders(name COLLATE NOCASE, created_at, id)"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if (
        not table_exists(connection, "conversation_folders")
        or tuple(table_columns(connection, "conversation_folders")) != EXPECTED_COLUMNS
    ):
        raise SchemaValidationError("conversation_folders table does not match schema (version 11)")
