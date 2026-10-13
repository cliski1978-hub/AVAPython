"""Durable administrator-configured execution Workspace roots."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns

VERSION = 25
NAME = "workspace access configuration"
EXPECTED_COLUMNS = (
    "workspace_id",
    "name",
    "kind",
    "root_path",
    "allowed_capabilities",
    "status",
    "revision",
    "created_at",
    "updated_at",
    "contract_version",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE workspace_access_configurations ("
        "workspace_id TEXT PRIMARY KEY, name TEXT, kind TEXT NOT NULL CHECK(kind IN ('local','ephemeral')), "
        "root_path TEXT NOT NULL, allowed_capabilities TEXT NOT NULL, "
        "status TEXT NOT NULL CHECK(status IN ('active','revoked')), "
        "revision INTEGER NOT NULL CHECK(revision > 0), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "contract_version TEXT NOT NULL CHECK(contract_version = 'v1'))"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if tuple(table_columns(connection, "workspace_access_configurations")) != EXPECTED_COLUMNS:
        raise SchemaValidationError("Invalid Workspace access configuration schema")
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='workspace_access_configurations'"
    ).fetchone()
    ddl = "".join(str(row["sql"]).lower().split()) if row else ""
    for constraint in ("primarykey", "check(revision>0)", "check(statusin('active','revoked'))"):
        if constraint not in ddl:
            raise SchemaValidationError("Workspace access configuration constraints are missing")
