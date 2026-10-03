"""SQLite adapter for conversation folder metadata."""

import sqlite3
from datetime import datetime

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.errors import PersistenceError
from ava.infrastructure.persistence.serialization import row_to_conversation_folder_record, to_utc_iso
from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.repositories.conversation_folder_repository import ConversationFolderRepository


class RelationalConversationFolderRepository(ConversationFolderRepository):
    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, folder: ConversationFolderRecord) -> ConversationFolderRecord:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO conversation_folders (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (folder.id, folder.name, to_utc_iso(folder.created_at), to_utc_iso(folder.updated_at)),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Conversation folder", key=folder.id) from exc
        return folder

    def get(self, folder_id: str) -> ConversationFolderRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, name, created_at, updated_at FROM conversation_folders WHERE id = ?", (folder_id,)
            ).fetchone()
        return row_to_conversation_folder_record(row) if row is not None else None

    def list(self) -> list[ConversationFolderRecord]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT id, name, created_at, updated_at FROM conversation_folders").fetchall()
        # Python casefold ordering keeps Unicode behavior identical to memory storage.
        return sorted(
            (row_to_conversation_folder_record(row) for row in rows),
            key=lambda item: (item.name.casefold(), item.created_at, item.id),
        )

    def rename(self, folder_id: str, name: str, updated_at: datetime) -> ConversationFolderRecord | None:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE conversation_folders SET name = ?, updated_at = ? WHERE id = ?",
                (name, to_utc_iso(updated_at), folder_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT id, name, created_at, updated_at FROM conversation_folders WHERE id = ?", (folder_id,)
            ).fetchone()
        return row_to_conversation_folder_record(row) if row is not None else None

    def delete(self, folder_id: str) -> bool:
        try:
            with self._database.transaction() as connection:
                row = connection.execute("SELECT id FROM conversation_folders WHERE id = ?", (folder_id,)).fetchone()
                if row is None:
                    return False
                connection.execute(
                    "DELETE FROM core_prompt_assignments WHERE scope_type = 'folder' AND scope_id = ?", (folder_id,)
                )
                connection.execute("UPDATE conversations SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
                connection.execute("DELETE FROM conversation_folders WHERE id = ?", (folder_id,))
            return True
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not delete conversation folder {folder_id!r}.") from exc
