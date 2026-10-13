"""Migration 0021 — add a per-model AVA context window setting."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 21
NAME = "Configured model context windows"


def migrate_up(connection: sqlite3.Connection) -> None:
    if "context_window_tokens" not in table_columns(connection, "model_configurations"):
        connection.execute(
            "ALTER TABLE model_configurations ADD COLUMN context_window_tokens INTEGER NULL "
            "CHECK (context_window_tokens IS NULL OR context_window_tokens > 0)"
        )


def verify_structure(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "model_configurations") or "context_window_tokens" not in table_columns(
        connection, "model_configurations"
    ):
        raise SchemaValidationError("model_configurations is missing context_window_tokens (schema version 21)")
