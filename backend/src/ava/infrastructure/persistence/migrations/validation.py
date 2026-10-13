"""Bounded SQLite structural validation for migration verification (Step 4.7).

Not a generalized introspection framework: these helpers validate only the
specific Step 4.6/initial-schema layout the migration system knows how to
adopt and verify. They are used by the initial migration's ``verify`` to
protect against silent corruption/version mismatch — in particular to
recognize (and refuse) unknown or incompatible legacy databases before any
metadata stamping happens.
"""

import sqlite3
from typing import cast

# ============================================================
# BEGIN: Structural validation helpers
# ============================================================


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    """Return whether a table exists in the database."""
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def present_tables(connection: sqlite3.Connection) -> set[str]:
    """Return the names of every table in the database."""
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {cast(str, row["name"]) for row in rows}


def table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    """Return the column names of a table in declared order."""
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [cast(str, row["name"]) for row in rows]


def has_unique_index_on(connection: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> bool:
    """Return whether the table has a unique index over exactly ``columns``.

    This recognizes both explicit ``UNIQUE`` column/table constraints (which
    SQLite materializes as ``sqlite_autoindex_*``) and named unique indexes,
    by comparing the ordered index column list.
    """
    indexes = connection.execute(f'PRAGMA index_list("{table}")').fetchall()
    for index in indexes:
        if not index["unique"]:
            continue
        rows = connection.execute(f'PRAGMA index_info("{cast(str, index["name"])}")').fetchall()
        index_columns = tuple(cast(str, row["name"]) for row in rows)
        if tuple(index_columns) == columns:
            return True
    return False


def has_named_index(connection: sqlite3.Connection, table: str, index_name: str) -> bool:
    """Return whether a named index exists on a table."""
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ? AND tbl_name = ?",
        (index_name, table),
    ).fetchone()
    return row is not None


def is_unique_index(connection: sqlite3.Connection, index_name: str) -> bool:
    """Return whether a named index enforces uniqueness.

    Used to verify critical protection indexes (e.g. the single-terminal-event
    partial unique index on ``run_events``) are actually unique, not merely
    present in name.
    """
    row = connection.execute(
        "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    ).fetchone()
    if row is None:
        return False
    table = cast(str, row["tbl_name"])
    indexes = connection.execute(f'PRAGMA index_list("{table}")').fetchall()
    return any(index["name"] == index_name and index["unique"] for index in indexes)


# ============================================================
# END: Structural validation helpers
# ============================================================
