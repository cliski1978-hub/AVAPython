"""Migration 0001 — initial application persistence schema (Step 4.7).

This migration owns the DDL for AVA's initial persisted schema: the exact
five-table layout established by Step 4.6 (a Step 4.6 database is byte-for-byte
equivalent and is adopted rather than recreated). It is the single authoritative
production mechanism for creating the relational schema.

The layout preserves every Step 4.6 protection:

* ``runs.run_id`` is the primary key (TEXT, extensible).
* ``run_events`` carries an explicit monotonic per-run ``seq`` with
  ``UNIQUE(run_id, seq)`` for deterministic append order, a unique ``event_id``,
  and the partial unique index ``idx_run_events_one_terminal`` enforcing at most
  one terminal event per run (``run_completed``/``run_cancelled``/``run_failed``).
* ``conversations``/``documents`` expose unique API-facing ids over a stable
  surrogate ``id`` rowid.
* ``messages`` scope identity per conversation via ``UNIQUE(conversation_id,
  message_id)`` and order via ``idx_messages_conversation_order``.

Foreign keys: Step 4.6 deliberately shipped without declarative foreign keys
(AVA identity columns enforce integrity through the services); the initial
migration reproduces that exact baseline so existing Step 4.6 databases adopt
cleanly. Engine-level FKs are a candidate for a later real migration.
Default/column-level values match Step 4.6 exactly; nothing was relaxed.
"""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import (
    has_named_index,
    has_unique_index_on,
    is_unique_index,
    present_tables,
    table_columns,
    table_exists,
)

VERSION = 1
NAME = "initial application persistence schema"

#: Application tables created by this migration (adoption/validation vocabulary).
EXPECTED_TABLES: tuple[str, ...] = ("runs", "run_events", "conversations", "messages", "documents")

#: The structural baseline each table must match (declared column order).
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "runs": ("run_id", "status", "created_at", "updated_at", "execution_selection"),
    "run_events": ("id", "event_id", "run_id", "event_type", "seq", "timestamp", "payload", "contract_version"),
    "conversations": ("id", "conversation_id", "title", "created_at", "updated_at"),
    "messages": (
        "id",
        "message_id",
        "conversation_id",
        "role",
        "status",
        "content",
        "source_run_id",
        "created_at",
        "updated_at",
    ),
    "documents": ("id", "document_id", "title", "content", "content_format", "created_at", "updated_at"),
}

#: Infrastructure-only tables allowed alongside the application schema.
_ALLOWED_NON_APPLICATION_TABLES = frozenset({"ava_schema_migrations"})

#: Ordered DDL executed exactly once, inside a transaction, by the runner.
STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE runs (
        run_id              TEXT PRIMARY KEY,
        status              TEXT NOT NULL,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        execution_selection TEXT
    )
    """,
    """
    CREATE TABLE run_events (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id         TEXT NOT NULL UNIQUE,
        run_id           TEXT NOT NULL,
        event_type       TEXT NOT NULL,
        seq              INTEGER NOT NULL,
        "timestamp"      TEXT NOT NULL,
        payload          TEXT NOT NULL,
        contract_version TEXT NOT NULL,
        UNIQUE (run_id, seq)
    )
    """,
    # Defense-in-depth for the single-terminal-event invariant: a run may
    # store at most one terminal event (the three terminal event types from
    # TERMINAL_EVENT_TYPES in the run-event repository port).
    """
    CREATE UNIQUE INDEX idx_run_events_one_terminal
        ON run_events (run_id)
        WHERE event_type IN ('run_completed', 'run_cancelled', 'run_failed')
    """,
    """
    CREATE TABLE conversations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL UNIQUE,
        title           TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE messages (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id      TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        role            TEXT NOT NULL,
        status          TEXT NOT NULL,
        content         TEXT NOT NULL,
        source_run_id   TEXT,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        UNIQUE (conversation_id, message_id)
    )
    """,
    """
    CREATE INDEX idx_messages_conversation_order
        ON messages (conversation_id, id)
    """,
    """
    CREATE TABLE documents (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id    TEXT NOT NULL UNIQUE,
        title          TEXT NOT NULL,
        content        TEXT NOT NULL,
        content_format TEXT NOT NULL,
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL
    )
    """,
)


def migrate_up(connection: sqlite3.Connection) -> None:
    """Apply the initial five-table schema (single source of truth for v0001)."""
    for statement in STATEMENTS:
        connection.execute(statement)


def verify_structure(connection: sqlite3.Connection) -> None:
    """Raise ``SchemaValidationError`` unless the database matches this layout.

    Only databases matching the exact Step 4.6/initial schema may be adopted
    as version 1 or verified as current; any mismatch fails closed with a
    diagnostic rather than stamping or rewriting an unknown schema.
    """
    violations = _structure_violations(connection)
    if violations:
        detail = "; ".join(violations)
        raise SchemaValidationError(
            f"database does not match the initial application persistence schema (version {VERSION}): {detail}. "
            "Refusing to adopt or stamp an unknown/incompatible schema."
        )


def _structure_violations(connection: sqlite3.Connection) -> list[str]:
    violations: list[str] = []

    for table in EXPECTED_TABLES:
        if not table_exists(connection, table):
            violations.append(f"missing table {table!r}")
            continue
        columns = table_columns(connection, table)
        if tuple(columns) != EXPECTED_COLUMNS[table]:
            violations.append(
                f"table {table!r} columns {list(columns)} do not match expected "
                f"{list(EXPECTED_COLUMNS[table])}"
            )

    unexpected = [
        table
        for table in sorted(present_tables(connection))
        if table not in EXPECTED_TABLES
        and table not in _ALLOWED_NON_APPLICATION_TABLES
        and not table.startswith("sqlite_")
    ]
    if unexpected:
        violations.append(f"unexpected tables {unexpected}")

    if has_named_index(connection, "run_events", "idx_run_events_one_terminal"):
        if not is_unique_index(connection, "idx_run_events_one_terminal"):
            violations.append("run_events terminal-event index is not unique")
    else:
        violations.append("missing run_events terminal-event protection index 'idx_run_events_one_terminal'")
    if not has_named_index(connection, "messages", "idx_messages_conversation_order"):
        violations.append("missing messages ordering index 'idx_messages_conversation_order'")

    if not has_unique_index_on(connection, "runs", ("run_id",)):
        violations.append("runs has no unique index on run_id")
    if not has_unique_index_on(connection, "run_events", ("event_id",)):
        violations.append("run_events has no unique index on event_id")
    if not has_unique_index_on(connection, "run_events", ("run_id", "seq")):
        violations.append("run_events has no unique index on (run_id, seq)")
    if not has_unique_index_on(connection, "conversations", ("conversation_id",)):
        violations.append("conversations has no unique index on conversation_id")
    if not has_unique_index_on(connection, "messages", ("conversation_id", "message_id")):
        violations.append("messages has no unique index on (conversation_id, message_id)")
    if not has_unique_index_on(connection, "documents", ("document_id",)):
        violations.append("documents has no unique index on document_id")

    return violations