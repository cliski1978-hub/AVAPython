"""Migration 0002 — document revision history (Step 4.13.C).

Adds the immutable document-revision history table that the document
write coordinator and relational revision repository (Step 4.13.C) persist
through. Every document save appends an immutable full snapshot here while
the ``documents`` table keeps holding the current state.

Layout:

* ``revision_id`` is the globally unique backend-owned revision identity
  (``UNIQUE``); ``document_id`` + ``revision_number`` is the per-document
  monotonic sequence (``UNIQUE(document_id, revision_number)``), enforced at
  the database level so concurrent appends can never interleave numbering.
* ``id`` is the stable surrogate rowid; ``title``/``content``/
  ``content_format`` are the snapshot values; ``created_at`` is the
  authoritative aware-UTC snapshot timestamp.

Version 0001 is never modified: its five-table layout and adoption validator
remain exactly the Step 4.6 baseline. This migration only appends the
revision table on top of an existing (adopted or migrated) version 1
database. No downgrade migration exists.
"""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import (
    has_unique_index_on,
    present_tables,
    table_columns,
    table_exists,
)

VERSION = 2
NAME = "document revision history"

#: Application tables created by this migration (adoption/validation vocabulary).
EXPECTED_TABLES: tuple[str, ...] = ("document_revisions",)

#: The structural baseline the table must match (declared column order).
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "document_revisions": (
        "id",
        "revision_id",
        "document_id",
        "revision_number",
        "title",
        "content",
        "content_format",
        "created_at",
    ),
}

#: Tables that legitimately coexist with the revision table (the version 1
#: framework plus the infrastructure metadata table).
_ALLOWED_COEXISTING_TABLES = frozenset(
    {"runs", "run_events", "conversations", "messages", "documents", "ava_schema_migrations"}
)

#: Ordered DDL executed exactly once, inside a transaction, by the runner.
STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE document_revisions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        revision_id     TEXT NOT NULL UNIQUE,
        document_id     TEXT NOT NULL,
        revision_number INTEGER NOT NULL,
        title           TEXT NOT NULL,
        content         TEXT NOT NULL,
        content_format  TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        UNIQUE (document_id, revision_number)
    )
    """,
)


def migrate_up(connection: sqlite3.Connection) -> None:
    """Apply the document-revision history table (single source of truth for v0002)."""
    for statement in STATEMENTS:
        connection.execute(statement)


def verify_structure(connection: sqlite3.Connection) -> None:
    """Raise ``SchemaValidationError`` unless the revision table matches this layout.

    Ran when the database is already at version 2, so it accepts the version 1
    framework tables and the metadata table alongside ``document_revisions``.
    Any mismatch fails closed with a diagnostic.
    """
    violations = _structure_violations(connection)
    if violations:
        detail = "; ".join(violations)
        raise SchemaValidationError(
            f"database does not match the document revision history schema (version {VERSION}): {detail}. "
            "Refusing to verify or stamp an unknown/incompatible schema."
        )


def _structure_violations(connection: sqlite3.Connection) -> list[str]:
    violations: list[str] = []

    if not table_exists(connection, "document_revisions"):
        violations.append("missing table 'document_revisions'")
    else:
        columns = table_columns(connection, "document_revisions")
        if tuple(columns) != EXPECTED_COLUMNS["document_revisions"]:
            violations.append(
                f"table 'document_revisions' columns {list(columns)} do not match expected "
                f"{list(EXPECTED_COLUMNS['document_revisions'])}"
            )

    unexpected = [
        table
        for table in sorted(present_tables(connection))
        if table not in EXPECTED_TABLES and table not in _ALLOWED_COEXISTING_TABLES and not table.startswith("sqlite_")
    ]
    if unexpected:
        violations.append(f"unexpected tables {unexpected}")

    if not has_unique_index_on(connection, "document_revisions", ("revision_id",)):
        violations.append("document_revisions has no unique index on revision_id")
    if not has_unique_index_on(connection, "document_revisions", ("document_id", "revision_number")):
        violations.append("document_revisions has no unique index on (document_id, revision_number)")

    return violations
