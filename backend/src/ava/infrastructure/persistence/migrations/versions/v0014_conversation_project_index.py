"""Migration 0014 — index Project-scoped conversation lookup."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_exists

VERSION = 14
NAME = "conversation Project lookup index"
EXPECTED_TABLES = ("conversations",)


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE INDEX idx_conversations_project ON conversations (project_id)")


def verify_structure(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "conversations"):
        raise SchemaValidationError("conversations table does not exist (version 14)")
    indexes = {row["name"] for row in connection.execute("PRAGMA index_list(conversations)")}
    if "idx_conversations_project" not in indexes:
        raise SchemaValidationError("conversations Project lookup index is missing (version 14)")
