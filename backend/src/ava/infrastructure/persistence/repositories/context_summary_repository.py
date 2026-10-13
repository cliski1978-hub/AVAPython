"""SQLite adapter for versioned conversation context summaries."""

from datetime import datetime
from sqlite3 import Row

from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.serialization import to_utc_iso
from ava.repositories.context_summary_repository import (
    ContextSummaryRepository,
    ConversationContextSummary,
)


def _record(row: Row) -> ConversationContextSummary:
    return ConversationContextSummary(
        summary_id=row["summary_id"],
        conversation_id=row["conversation_id"],
        content=row["content"],
        covers_through_message_id=row["covers_through_message_id"],
        covers_through_sequence=row["covers_through_sequence"],
        source_token_count=row["source_token_count"],
        summary_token_count=row["summary_token_count"],
        model_id=row["model_id"],
        provider_id=row["provider_id"],
        version=row["version"],
        created_at=datetime.fromisoformat(row["created_at"]),
        stale=bool(row["stale"]),
    )


class RelationalContextSummaryRepository(ContextSummaryRepository):
    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def get_active(self, conversation_id: str) -> ConversationContextSummary | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_context_summaries WHERE conversation_id = ? AND stale = 0 "
                "ORDER BY version DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
        return _record(row) if row else None

    def list_versions(self, conversation_id: str) -> list[ConversationContextSummary]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_context_summaries WHERE conversation_id = ? ORDER BY version",
                (conversation_id,),
            ).fetchall()
        return [_record(row) for row in rows]

    def save_version(self, summary: ConversationContextSummary) -> ConversationContextSummary:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO conversation_context_summaries "
                "(summary_id, conversation_id, content, covers_through_message_id, covers_through_sequence, "
                "source_token_count, summary_token_count, model_id, provider_id, version, created_at, stale) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    summary.summary_id,
                    summary.conversation_id,
                    summary.content,
                    summary.covers_through_message_id,
                    summary.covers_through_sequence,
                    summary.source_token_count,
                    summary.summary_token_count,
                    summary.model_id,
                    summary.provider_id,
                    summary.version,
                    to_utc_iso(summary.created_at),
                    int(summary.stale),
                ),
            )
        return summary

    def mark_stale(self, summary_id: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE conversation_context_summaries SET stale = 1 WHERE summary_id = ?", (summary_id,)
            )

    def delete_for_conversation(self, conversation_id: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "DELETE FROM conversation_context_summaries WHERE conversation_id = ?", (conversation_id,)
            )
