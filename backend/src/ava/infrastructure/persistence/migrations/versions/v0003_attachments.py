"""Migration 0003 — attachment metadata table (Step 4.14.C).

Adds the durable relational home for Step 4.14.A attachment metadata that the
``RelationalAttachmentRepository`` (Step 4.14.C) persists through. This is a
metadata-only schema: it stores identity, display name, media type, byte size,
the opaque logical ``storage_key``, optional ownership, lifecycle status, and
the creation timestamp — no physical file bytes, no paths, no provider columns.

The layout:

* ``attachment_id`` is the backend/service-owned identity, ``UNIQUE``.
* ``storage_key`` is the opaque logical content reference, ``UNIQUE`` (a key is
  unique and immutable per attachment; physical content is a separate port).
* The owner model is intentionally generic and orphan-safe: ``owner_type`` /
  ``owner_id`` are both-``NULL``-or-both-set, and the type is restricted to
  the approved vocabulary. No declarative foreign keys, no cascade, no delete
  semantics (the generic owner may point at a document, message, or
  conversation; the ownership vocabulary stays synchronized with the approved
  contract options).
* ``status`` is restricted to the approved lifecycle vocabulary; ``size_bytes``
  is non-negative with zero valid.
* ``id`` is the stable surrogate rowid used only for deterministic insertion
  ordering (``idx_attachments_owner`` supports owner listing); it is never
  exposed through the repository port.

Checksum (``sha256``/etag), deletion, and provider-specific columns (S3,
Azure, volume paths) are explicitly deferred and do not appear here. Versions
0001 and 0002 are never modified; this migration only appends the attachments
table on top of an existing version 1/2 database.
"""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import (
    has_named_index,
    has_unique_index_on,
    present_tables,
    table_columns,
    table_exists,
)

VERSION = 3
NAME = "attachment metadata"

#: Application tables created by this migration (adoption/validation vocabulary).
EXPECTED_TABLES: tuple[str, ...] = ("attachments",)

#: The structural baseline the table must match (declared column order).
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "attachments": (
        "id",
        "attachment_id",
        "file_name",
        "media_type",
        "size_bytes",
        "storage_key",
        "owner_type",
        "owner_id",
        "status",
        "created_at",
    ),
}

#: Tables that legitimately coexist with the attachment table (the version 1
#: framework, the revision history table, and the infrastructure metadata table).
_ALLOWED_COEXISTING_TABLES = frozenset(
    {
        "runs",
        "run_events",
        "conversations",
        "messages",
        "documents",
        "document_revisions",
        "ava_schema_migrations",
    }
)

#: Ordered DDL executed exactly once, inside a transaction, by the runner.
STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE attachments (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        attachment_id TEXT NOT NULL UNIQUE,
        file_name     TEXT NOT NULL,
        media_type    TEXT NOT NULL,
        size_bytes    INTEGER NOT NULL CHECK (size_bytes >= 0),
        storage_key   TEXT NOT NULL UNIQUE,
        owner_type    TEXT NULL,
        owner_id      TEXT NULL,
        status        TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        CHECK (
            (owner_type IS NULL AND owner_id IS NULL)
            OR
            (owner_type IS NOT NULL AND owner_id IS NOT NULL)
        ),
        CHECK (
            owner_type IS NULL
            OR owner_type IN ('document', 'conversation', 'message')
        ),
        CHECK (
            status IN ('pending', 'available', 'failed')
        )
    )
    """,
    """
    CREATE INDEX idx_attachments_owner
        ON attachments (owner_type, owner_id)
    """,
)


def migrate_up(connection: sqlite3.Connection) -> None:
    """Apply the attachment metadata table (single source of truth for v0003)."""
    for statement in STATEMENTS:
        connection.execute(statement)


def verify_structure(connection: sqlite3.Connection) -> None:
    """Raise ``SchemaValidationError`` unless the attachment table matches this layout.

    Ran when the database is already at version 3, so it accepts the version 1
    and version 2 framework tables and the metadata table alongside
    ``attachments``. Any mismatch fails closed with a diagnostic.
    """
    violations = _structure_violations(connection)
    if violations:
        detail = "; ".join(violations)
        raise SchemaValidationError(
            f"database does not match the attachment metadata schema (version {VERSION}): {detail}. "
            "Refusing to verify or stamp an unknown/incompatible schema."
        )


def _structure_violations(connection: sqlite3.Connection) -> list[str]:
    violations: list[str] = []

    if not table_exists(connection, "attachments"):
        violations.append("missing table 'attachments'")
    else:
        columns = table_columns(connection, "attachments")
        if tuple(columns) != EXPECTED_COLUMNS["attachments"]:
            violations.append(
                f"table 'attachments' columns {list(columns)} do not match expected "
                f"{list(EXPECTED_COLUMNS['attachments'])}"
            )

    unexpected = [
        table
        for table in sorted(present_tables(connection))
        if table not in EXPECTED_TABLES
        and table not in _ALLOWED_COEXISTING_TABLES
        and not table.startswith("sqlite_")
    ]
    if unexpected:
        violations.append(f"unexpected tables {unexpected}")

    if not has_unique_index_on(connection, "attachments", ("attachment_id",)):
        violations.append("attachments has no unique index on attachment_id")
    if not has_unique_index_on(connection, "attachments", ("storage_key",)):
        violations.append("attachments has no unique index on storage_key")
    if not has_named_index(connection, "attachments", "idx_attachments_owner"):
        violations.append("missing attachments owner lookup index 'idx_attachments_owner'")

    return violations