"""Transactional SQLite deletion of conversation-owned durable records."""

import sqlite3

from ava.contracts.attachments import AttachmentOwnerType
from ava.contracts.responses import ACTIVE_RUN_STATUSES
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.repositories.conversation_hard_delete import (
    ActiveConversationRunDeletionError,
    ConversationDeletion,
    ConversationHardDeleteCoordinator,
)


class RelationalConversationHardDeleteCoordinator(ConversationHardDeleteCoordinator):
    """Delete the relational conversation graph in one SQLite transaction."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def delete(self, conversation_id: str) -> ConversationDeletion | None:
        deletion = self.delete_many((conversation_id,))
        if conversation_id not in deletion.deleted_conversation_ids:
            return None
        return ConversationDeletion(deletion.attachment_storage_keys, (conversation_id,))

    def delete_many(self, conversation_ids: tuple[str, ...]) -> ConversationDeletion:
        storage_keys: list[str] = []
        deleted_ids: list[str] = []
        with self._database.transaction() as connection:
            for conversation_id in dict.fromkeys(conversation_ids):
                deleted_keys = self._delete_in_transaction(connection, conversation_id)
                if deleted_keys is not None:
                    storage_keys.extend(deleted_keys)
                    deleted_ids.append(conversation_id)
        return ConversationDeletion(tuple(storage_keys), tuple(deleted_ids))

    def _delete_in_transaction(self, connection: sqlite3.Connection, conversation_id: str) -> tuple[str, ...] | None:
        exists = connection.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        if exists is None:
            return None

        connection.execute(
            "DELETE FROM core_prompt_assignments WHERE scope_type = 'conversation' AND scope_id = ?",
            (conversation_id,),
        )
        connection.execute("DELETE FROM conversation_context_summaries WHERE conversation_id = ?", (conversation_id,))

        message_rows = connection.execute(
            "SELECT message_id, source_run_id FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
        message_ids = tuple(row["message_id"] for row in message_rows)
        source_run_ids = tuple(row["source_run_id"] for row in message_rows if row["source_run_id"])
        message_placeholders = ", ".join("?" for _ in message_ids)
        run_conditions = ["conversation_id = ?"]
        run_parameters: list[str] = [conversation_id]
        if message_ids:
            run_conditions.extend(
                (
                    f"(conversation_id IS NULL AND source_user_message_id IN ({message_placeholders}) "
                    "AND NOT EXISTS (SELECT 1 FROM messages other WHERE other.message_id = "
                    "runs.source_user_message_id AND other.conversation_id != ?) "
                    "AND NOT EXISTS (SELECT 1 FROM messages refs WHERE refs.source_run_id = runs.run_id "
                    "AND refs.conversation_id != ?))",
                    f"(conversation_id IS NULL AND assistant_message_id IN ({message_placeholders}) "
                    "AND NOT EXISTS (SELECT 1 FROM messages other WHERE other.message_id = "
                    "runs.assistant_message_id AND other.conversation_id != ?) "
                    "AND NOT EXISTS (SELECT 1 FROM messages refs WHERE refs.source_run_id = runs.run_id "
                    "AND refs.conversation_id != ?))",
                )
            )
            run_parameters.extend(message_ids)
            run_parameters.append(conversation_id)
            run_parameters.append(conversation_id)
            run_parameters.extend(message_ids)
            run_parameters.append(conversation_id)
            run_parameters.append(conversation_id)
        if source_run_ids:
            run_conditions.append(
                f"(conversation_id IS NULL AND run_id IN ({', '.join('?' for _ in source_run_ids)}) "
                "AND NOT EXISTS (SELECT 1 FROM messages refs WHERE refs.source_run_id = runs.run_id "
                "AND refs.conversation_id != ?))"
            )
            run_parameters.extend(source_run_ids)
            run_parameters.append(conversation_id)
        run_rows = connection.execute(
            f"SELECT run_id, status FROM runs WHERE {' OR '.join(run_conditions)}",
            run_parameters,
        ).fetchall()
        active_statuses = {status.value for status in ACTIVE_RUN_STATUSES}
        active_run_ids = tuple(row["run_id"] for row in run_rows if row["status"] in active_statuses)
        if active_run_ids:
            raise ActiveConversationRunDeletionError(conversation_id, active_run_ids)
        run_ids = tuple(row["run_id"] for row in run_rows)

        attachment_conditions = ["owner_type = ? AND owner_id = ?"]
        attachment_parameters: list[str] = [AttachmentOwnerType.CONVERSATION.value, conversation_id]
        if message_ids:
            attachment_conditions.append(
                f"(owner_type = ? AND owner_id IN ({message_placeholders}) "
                "AND NOT EXISTS (SELECT 1 FROM messages other "
                "WHERE other.message_id = attachments.owner_id AND other.conversation_id != ?))"
            )
            attachment_parameters.extend((AttachmentOwnerType.MESSAGE.value, *message_ids, conversation_id))
        attachment_rows = connection.execute(
            f"SELECT attachment_id, storage_key FROM attachments WHERE {' OR '.join(attachment_conditions)}",
            attachment_parameters,
        ).fetchall()
        storage_keys = tuple(row["storage_key"] for row in attachment_rows)
        attachment_ids = tuple(row["attachment_id"] for row in attachment_rows)

        # A message id is only unique within a conversation. Preserve an
        # ambiguous message attachment and detach it if another conversation
        # still has a message with the same identifier.
        if message_ids:
            connection.execute(
                f"UPDATE attachments SET owner_type = NULL, owner_id = NULL "
                f"WHERE owner_type = ? AND owner_id IN ({message_placeholders}) "
                "AND EXISTS (SELECT 1 FROM messages other "
                "WHERE other.message_id = attachments.owner_id AND other.conversation_id != ?)",
                (AttachmentOwnerType.MESSAGE.value, *message_ids, conversation_id),
            )
        if run_ids:
            run_placeholders = ", ".join("?" for _ in run_ids)
            connection.execute(f"DELETE FROM run_events WHERE run_id IN ({run_placeholders})", run_ids)
            # Keep any surviving message valid if it referenced a run owned
            # by the conversation being removed.
            connection.execute(
                f"UPDATE messages SET source_run_id = NULL WHERE conversation_id != ? "
                f"AND source_run_id IN ({run_placeholders})",
                (conversation_id, *run_ids),
            )
            connection.execute(f"DELETE FROM runs WHERE run_id IN ({run_placeholders})", run_ids)
        if attachment_ids:
            placeholders = ", ".join("?" for _ in attachment_ids)
            connection.execute(f"DELETE FROM attachments WHERE attachment_id IN ({placeholders})", attachment_ids)
        connection.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        connection.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
        return storage_keys
