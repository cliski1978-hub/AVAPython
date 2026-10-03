"""Migration 0018 — durable Project-file metadata."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 18
NAME = "Project files"
EXPECTED_COLUMNS = (
    "id",
    "project_id",
    "file_name",
    "content_type",
    "size_bytes",
    "content_ref",
    "created_at",
    "updated_at",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE project_files ("
        "id TEXT PRIMARY KEY NOT NULL, "
        "project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "file_name TEXT NOT NULL CHECK (length(trim(file_name)) > 0), "
        "content_type TEXT NULL CHECK (content_type IS NULL OR length(trim(content_type)) > 0), "
        "size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0), "
        "content_ref TEXT NOT NULL UNIQUE CHECK (length(trim(content_ref)) > 0), "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute("CREATE INDEX idx_project_files_project_id ON project_files(project_id)")


def verify_structure(connection: sqlite3.Connection) -> None:
    if (
        not table_exists(connection, "project_files")
        or tuple(table_columns(connection, "project_files")) != EXPECTED_COLUMNS
    ):
        raise SchemaValidationError("project_files table does not match schema (version 18)")
