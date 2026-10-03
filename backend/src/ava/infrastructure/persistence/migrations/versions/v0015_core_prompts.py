"""Migration 0015 — durable reusable CORE prompt definitions."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 15
NAME = "CORE prompt definitions"
EXPECTED_TABLES = ("core_prompts",)
EXPECTED_COLUMNS = (
    "id",
    "name",
    "description",
    "prompt_text",
    "category",
    "is_enabled",
    "created_at",
    "updated_at",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE core_prompts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NULL,
            prompt_text TEXT NOT NULL,
            category TEXT NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if (
        not table_exists(connection, "core_prompts")
        or tuple(table_columns(connection, "core_prompts")) != EXPECTED_COLUMNS
    ):
        raise SchemaValidationError("core_prompts table does not match schema (version 15)")
