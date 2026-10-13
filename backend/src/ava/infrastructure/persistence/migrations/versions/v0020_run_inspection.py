"""Migration 0020 — persist run execution inspection snapshots."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

VERSION = 20
NAME = "Run inspection snapshots"


def migrate_up(connection: sqlite3.Connection) -> None:
    columns = table_columns(connection, "runs")
    if "inspection_snapshot" not in columns:
        connection.execute("ALTER TABLE runs ADD COLUMN inspection_snapshot TEXT NULL")


def verify_structure(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "runs") or "inspection_snapshot" not in table_columns(connection, "runs"):
        raise SchemaValidationError("runs table does not contain inspection_snapshot (version 20)")
