"""Migration 0012 — durable Project metadata."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 12
NAME = "projects"
EXPECTED_TABLES = ("projects",)
EXPECTED_COLUMNS = (
    "id",
    "name",
    "description",
    "instructions",
    "is_archived",
    "created_at",
    "updated_at",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            instructions TEXT,
            is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "projects") or tuple(table_columns(connection, "projects")) != EXPECTED_COLUMNS:
        raise SchemaValidationError("projects table does not match schema (version 12)")
