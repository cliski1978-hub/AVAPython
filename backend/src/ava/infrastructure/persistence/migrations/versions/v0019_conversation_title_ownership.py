"""Migration 0019 — persist whether a conversation title was user-set."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 19
NAME = "Conversation title ownership"


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        "ALTER TABLE conversations ADD COLUMN is_title_custom INTEGER NOT NULL DEFAULT 0 "
        "CHECK (is_title_custom IN (0, 1))"
    )
    # Before this marker existed, a manual rename was the only operation that
    # advanced a conversation's updated_at timestamp. Preserve that known
    # signal for already-renamed conversations without guessing from title text.
    connection.execute("UPDATE conversations SET is_title_custom = 1 WHERE updated_at > created_at")


def verify_structure(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "conversations") or "is_title_custom" not in table_columns(
        connection, "conversations"
    ):
        raise SchemaValidationError("conversations is missing is_title_custom (schema version 19)")
