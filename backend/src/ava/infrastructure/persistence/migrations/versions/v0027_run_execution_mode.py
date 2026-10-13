"""Persist the authority ceiling selected when a run is created."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns

VERSION = 27
NAME = "run execution mode"


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        "ALTER TABLE runs ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'chat' "
        "CHECK(execution_mode IN ('chat', 'plan', 'agent'))"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if "execution_mode" not in table_columns(connection, "runs"):
        raise SchemaValidationError("Run execution mode column is missing")
    row = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()
    ddl = "".join(str(row["sql"]).lower().split()) if row else ""
    if "default'chat'" not in ddl or "check(execution_modein('chat','plan','agent'))" not in ddl:
        raise SchemaValidationError("Run execution mode constraints are missing")
