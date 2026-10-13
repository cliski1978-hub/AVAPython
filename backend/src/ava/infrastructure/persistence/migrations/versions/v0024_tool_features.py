"""Persist singleton feature gates; missing configuration remains disabled."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_columns

VERSION = 24
NAME = "tool feature configuration"
EXPECTED_COLUMNS = ("id", "framework_enabled", "enabled_tool_ids", "configuration_version")


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE tool_feature_configuration (id INTEGER PRIMARY KEY CHECK(id = 1), "
        "framework_enabled INTEGER NOT NULL CHECK(framework_enabled IN (0, 1)), "
        "enabled_tool_ids TEXT NOT NULL, configuration_version INTEGER NOT NULL CHECK(configuration_version > 0))"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if tuple(table_columns(connection, "tool_feature_configuration")) != EXPECTED_COLUMNS:
        raise SchemaValidationError("Invalid tool feature configuration schema")
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tool_feature_configuration'"
    ).fetchone()
    ddl = "".join(str(row["sql"]).lower().split()) if row else ""
    for constraint in ("check(id=1)", "check(framework_enabledin(0,1))", "check(configuration_version>0)"):
        if constraint not in ddl:
            raise SchemaValidationError("Tool feature configuration constraints are missing")
