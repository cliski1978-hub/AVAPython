"""SQLite-backed conversation repository adapter (Step 4.6).

Implements the AVA ``ConversationRepository`` port over the shared
``SqliteDatabase``. Behavioral parity with the in-memory ``ConversationStore``:
duplicates raise ``ValueError``, unknown conversations return ``None``, and
``list()`` enumerates in stable insertion order (the technical surrogate
``id`` rowid is invisible to contracts and services).
"""

import sqlite3
from datetime import UTC, datetime

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import row_to_conversation_record, to_utc_iso
from ava.repositories.conversation_repository import ConversationRecord, ConversationRepository

_CONVERSATION_COLUMNS = "conversation_id, title, created_at, updated_at"

# ============================================================
# BEGIN: Relational Conversation Repository
# ============================================================


class RelationalConversationRepository(ConversationRepository):
    """SQLite-backed implementation of the conversation repository port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, conversation_id: str, *, title: str) -> ConversationRecord:
        now = datetime.now(UTC)
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO conversations (conversation_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (conversation_id, title, to_utc_iso(now), to_utc_iso(now)),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Conversation", key=conversation_id) from exc
        return ConversationRecord(conversation_id=conversation_id, title=title, created_at=now, updated_at=now)

    def get(self, conversation_id: str) -> ConversationRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None

    def list(self) -> list[ConversationRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations ORDER BY id ASC"
            ).fetchall()
        return [row_to_conversation_record(row) for row in rows]

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        now = datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE conversation_id = ?",
                (title, to_utc_iso(now), conversation_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None


# ============================================================
# END: Relational Conversation Repository
# ============================================================