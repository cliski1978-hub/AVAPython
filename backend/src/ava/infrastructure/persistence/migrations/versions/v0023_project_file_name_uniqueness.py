"""Migration 0023 — enforce Project-scoped normalized file-name uniqueness."""

import sqlite3
from collections import defaultdict

from ava.infrastructure.persistence.migrations.migration import MigrationError, SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import has_unique_index_on, table_columns, table_exists
from ava.repositories.project_file import normalize_project_file_name

VERSION = 23
NAME = "Project file name uniqueness"
EXPECTED_COLUMNS = (
    "id",
    "project_id",
    "file_name",
    "content_type",
    "size_bytes",
    "content_ref",
    "created_at",
    "updated_at",
    "normalized_file_name",
)
UNIQUE_INDEX = "ux_project_files_project_normalized_name"


def _duplicates(connection: sqlite3.Connection) -> list[tuple[str, str, list[str]]]:
    by_key: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in connection.execute("SELECT id, project_id, file_name FROM project_files"):
        by_key[(row["project_id"], normalize_project_file_name(row["file_name"]))].append((row["id"], row["file_name"]))
    return [
        (project_id, entries[0][1], [entry[0] for entry in entries])
        for (project_id, _), entries in sorted(by_key.items())
        if len(entries) > 1
    ]


def migrate_up(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "project_files"):
        raise SchemaValidationError("project_files table is missing (schema version 23)")

    duplicates = _duplicates(connection)
    if duplicates:
        details = "; ".join(
            f"project_id={project_id!r}, filename={file_name!r}, file_ids={file_ids!r}"
            for project_id, file_name, file_ids in duplicates[:10]
        )
        more = f" (and {len(duplicates) - 10} more)" if len(duplicates) > 10 else ""
        raise MigrationError(
            "Project-file uniqueness migration found existing filenames that collide after trimming and "
            "case-folding. No files or records were changed. Resolve the listed duplicates manually, then "
            f"restart AVA: {details}{more}"
        )

    columns = table_columns(connection, "project_files")
    if "normalized_file_name" in columns:
        raise SchemaValidationError("project_files already has normalized_file_name before schema version 23")

    connection.execute(
        "CREATE TABLE project_files_new ("
        "id TEXT PRIMARY KEY NOT NULL, "
        "project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "file_name TEXT NOT NULL CHECK (length(trim(file_name)) > 0), "
        "content_type TEXT NULL CHECK (content_type IS NULL OR length(trim(content_type)) > 0), "
        "size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0), "
        "content_ref TEXT NOT NULL UNIQUE CHECK (length(trim(content_ref)) > 0), "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "normalized_file_name TEXT NOT NULL CHECK (length(normalized_file_name) > 0))"
    )
    rows = connection.execute(
        "SELECT id, project_id, file_name, content_type, size_bytes, content_ref, created_at, updated_at "
        "FROM project_files"
    ).fetchall()
    connection.executemany(
        "INSERT INTO project_files_new "
        "(id, project_id, file_name, content_type, size_bytes, content_ref, created_at, updated_at, "
        "normalized_file_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(*tuple(row), normalize_project_file_name(row["file_name"])) for row in rows],
    )
    connection.execute("DROP TABLE project_files")
    connection.execute("ALTER TABLE project_files_new RENAME TO project_files")
    connection.execute("CREATE INDEX idx_project_files_project_id ON project_files(project_id)")
    connection.execute(
        "CREATE UNIQUE INDEX ux_project_files_project_normalized_name "
        "ON project_files(project_id, normalized_file_name)"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    columns = tuple(table_columns(connection, "project_files")) if table_exists(connection, "project_files") else ()
    if columns != EXPECTED_COLUMNS:
        raise SchemaValidationError("project_files table does not match schema (version 23)")
    if not has_unique_index_on(connection, "project_files", ("project_id", "normalized_file_name")):
        raise SchemaValidationError("Project-file normalized-name uniqueness index is missing (schema version 23)")
