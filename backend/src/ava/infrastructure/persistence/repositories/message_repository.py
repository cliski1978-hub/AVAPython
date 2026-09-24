"""SQLite-backed message repository adapter (Step 4.6).

Implements the AVA ``MessageRepository`` port over the shared
``SqliteDatabase``. Behavioral parity with the in-memory ``MessageStore``:

* a message is immutable once appended and is stored verbatim (its AVA-owned
  ``created_at``/``updated_at`` are preserved, not re-minted);
* duplicates raise ``ValueError``;
* ``get`` is scoped to its conversation;
* messages enumerate in stable append order (by the technical surrogate
  ``id``, invisible to contracts and services).
"""

import sqlite3

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import row_to_message_record, to_utc_iso
from ava.repositories.message_repository import MessageRecord, MessageRepository

_MESSAGE_COLUMNS = "message_id, conversation_id, role, content, status, source_run_id, created_at, updated_at"

# ============================================================
# BEGIN: Relational Message Repository
# ============================================================


class RelationalMessageRepository(MessageRepository):
    """SQLite-backed implementation of the message repository port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def append(self, message: MessageRecord) -> MessageRecord:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO messages (message_id, conversation_id, role, content, status, "
                    "source_run_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        message.message_id,
                        message.conversation_id,
                        message.role.value,
                        message.content,
                        message.status.value,
                        message.source_run_id,
                        to_utc_iso(message.created_at),
                        to_utc_iso(message.updated_at),
                    ),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Message", key=message.message_id) from exc
        return message

    def get(self, conversation_id: str, message_id: str) -> MessageRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_MESSAGE_COLUMNS} FROM messages WHERE conversation_id = ? AND message_id = ?",
                (conversation_id, message_id),
            ).fetchone()
        return row_to_message_record(row) if row is not None else None

    def list_for_conversation(self, conversation_id: str) -> list[MessageRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_MESSAGE_COLUMNS} FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
        return [row_to_message_record(row) for row in rows]


# ============================================================
# END: Relational Message Repository
# ============================================================