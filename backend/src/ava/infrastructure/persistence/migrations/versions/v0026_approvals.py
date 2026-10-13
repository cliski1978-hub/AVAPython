"""Durable, invocation-bound approval records."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns

VERSION = 26
NAME = "durable tool approvals"
EXPECTED_COLUMNS = (
    "approval_id",
    "invocation_id",
    "run_id",
    "workspace_id",
    "status",
    "requested_at",
    "record_json",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE approval_records ("
        "approval_id TEXT PRIMARY KEY, invocation_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL, "
        "workspace_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN "
        "('pending','approved','denied','expired','cancelled','invalidated')), "
        "requested_at TEXT NOT NULL, record_json TEXT NOT NULL)"
    )
    connection.execute("CREATE INDEX approval_records_pending_run ON approval_records(status, run_id)")
    connection.execute("CREATE INDEX approval_records_pending_workspace ON approval_records(status, workspace_id)")


def verify_structure(connection: sqlite3.Connection) -> None:
    if tuple(table_columns(connection, "approval_records")) != EXPECTED_COLUMNS:
        raise SchemaValidationError("Invalid approval record schema")
    row = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='approval_records'").fetchone()
    ddl = "".join(str(row["sql"]).lower().split()) if row else ""
    for constraint in (
        "primarykey",
        "unique",
        "check(statusin('pending','approved','denied','expired','cancelled','invalidated'))",
    ):
        if constraint not in ddl:
            raise SchemaValidationError("Approval record constraints are missing")
    indexes = {entry["name"] for entry in connection.execute("PRAGMA index_list(approval_records)").fetchall()}
    if not {"approval_records_pending_run", "approval_records_pending_workspace"}.issubset(indexes):
        raise SchemaValidationError("Approval lookup indexes are missing")
