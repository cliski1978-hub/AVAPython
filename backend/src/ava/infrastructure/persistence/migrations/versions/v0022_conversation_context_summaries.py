"""Migration 0022 — persist versioned AVA conversation context summaries."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import table_exists

VERSION = 22
NAME = "Conversation context summaries"


def migrate_up(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS conversation_context_summaries (
            summary_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            content TEXT NOT NULL,
            covers_through_message_id TEXT NOT NULL,
            covers_through_sequence INTEGER NOT NULL,
            source_token_count INTEGER NOT NULL,
            summary_token_count INTEGER NOT NULL,
            model_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            stale INTEGER NOT NULL DEFAULT 0 CHECK (stale IN (0, 1)),
            UNIQUE(conversation_id, version)
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_summaries_active "
        "ON conversation_context_summaries(conversation_id, stale, version DESC)"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, "conversation_context_summaries"):
        raise SchemaValidationError("conversation_context_summaries table is missing (schema version 22)")
