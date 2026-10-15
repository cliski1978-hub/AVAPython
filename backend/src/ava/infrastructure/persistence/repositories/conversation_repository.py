"""SQLite-backed conversation repository adapter (Step 4.6).

Implements the AVA ``ConversationRepository`` port over the shared
``SqliteDatabase``. Behavioral parity with the in-memory ``ConversationStore``:
duplicates raise ``ValueError``, unknown conversations return ``None``, and
``list()`` uses canonical pin/activity ordering; search filters the same
ordered population without changing its relative order.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection
from datetime import UTC, datetime

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import row_to_conversation_record, to_utc_iso
from ava.repositories.conversation_repository import (
    ConversationRecord,
    ConversationRepository,
    normalize_conversation_search,
)

_CONVERSATION_COLUMNS = (
    "conversation_id, title, created_at, updated_at, is_pinned, is_archived, folder_id, project_id, is_title_custom, "
    "owner_principal_ref, owner_tenant_ref"
)
_CONVERSATION_ORDER = "is_pinned DESC, updated_at DESC, created_at DESC, conversation_id ASC"

# ============================================================
# BEGIN: Relational Conversation Repository
# ============================================================


class RelationalConversationRepository(ConversationRepository):
    """SQLite-backed implementation of the conversation repository port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(
        self,
        conversation_id: str,
        *,
        title: str,
        project_id: str | None = None,
        folder_id: str | None = None,
        is_title_custom: bool = False,
        owner_principal_ref: str | None = None,
        owner_tenant_ref: str | None = None,
    ) -> ConversationRecord:
        now = datetime.now(UTC)
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO conversations (conversation_id, title, created_at, updated_at, "
                    "project_id, folder_id, is_title_custom, owner_principal_ref, owner_tenant_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        conversation_id,
                        title,
                        to_utc_iso(now),
                        to_utc_iso(now),
                        project_id,
                        folder_id,
                        int(is_title_custom),
                        owner_principal_ref,
                        owner_tenant_ref,
                    ),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Conversation", key=conversation_id) from exc
        return ConversationRecord(
            conversation_id=conversation_id,
            title=title,
            created_at=now,
            updated_at=now,
            project_id=project_id,
            folder_id=folder_id,
            is_title_custom=is_title_custom,
            owner_principal_ref=owner_principal_ref,
            owner_tenant_ref=owner_tenant_ref,
        )

    def get(self, conversation_id: str) -> ConversationRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None

    def get_for_owner(
        self, conversation_id: str, principal_ref: str, tenant_ref: str | None
    ) -> ConversationRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations "
                "WHERE conversation_id = ? AND owner_principal_ref = ? AND owner_tenant_ref IS ?",
                (conversation_id, principal_ref, tenant_ref),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None

    def list(self, search: str | None = None) -> list[ConversationRecord]:
        normalized = normalize_conversation_search(search)
        with self._database.connect() as connection:
            if normalized is None:
                rows = connection.execute(
                    f"SELECT {_CONVERSATION_COLUMNS} FROM conversations ORDER BY {_CONVERSATION_ORDER}"
                ).fetchall()
            else:
                escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                rows = connection.execute(
                    f"SELECT {_CONVERSATION_COLUMNS} FROM conversations "
                    "WHERE LOWER(title) LIKE LOWER(?) ESCAPE '\\' "
                    f"ORDER BY {_CONVERSATION_ORDER}",
                    (f"%{escaped}%",),
                ).fetchall()
        return [row_to_conversation_record(row) for row in rows]

    def list_for_owner(
        self, principal_ref: str, tenant_ref: str | None, search: str | None = None
    ) -> Collection[ConversationRecord]:
        normalized = normalize_conversation_search(search)
        with self._database.connect() as connection:
            if normalized is None:
                rows = connection.execute(
                    f"SELECT {_CONVERSATION_COLUMNS} FROM conversations "
                    "WHERE owner_principal_ref = ? AND owner_tenant_ref IS ? "
                    f"ORDER BY {_CONVERSATION_ORDER}",
                    (principal_ref, tenant_ref),
                ).fetchall()
            else:
                escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                rows = connection.execute(
                    f"SELECT {_CONVERSATION_COLUMNS} FROM conversations "
                    "WHERE owner_principal_ref = ? AND owner_tenant_ref IS ? "
                    "AND LOWER(title) LIKE LOWER(?) ESCAPE '\\' "
                    f"ORDER BY {_CONVERSATION_ORDER}",
                    (principal_ref, tenant_ref, f"%{escaped}%"),
                ).fetchall()
        return [row_to_conversation_record(row) for row in rows]

    def list_by_project(self, project_id: str) -> Collection[ConversationRecord]:
        """Query one Project's conversations using canonical conversation order."""
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE project_id = ? "
                f"ORDER BY {_CONVERSATION_ORDER}",
                (project_id,),
            ).fetchall()
        return [row_to_conversation_record(row) for row in rows]

    def list_by_project_for_owner(
        self, project_id: str, principal_ref: str, tenant_ref: str | None
    ) -> Collection[ConversationRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations "
                "WHERE project_id = ? AND owner_principal_ref = ? AND owner_tenant_ref IS ? "
                f"ORDER BY {_CONVERSATION_ORDER}",
                (project_id, principal_ref, tenant_ref),
            ).fetchall()
        return [row_to_conversation_record(row) for row in rows]

    def set_pinned(self, conversation_id: str, is_pinned: bool) -> ConversationRecord | None:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET is_pinned = ? WHERE conversation_id = ?",
                (int(is_pinned), conversation_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None

    def set_archived(self, conversation_id: str, is_archived: bool) -> ConversationRecord | None:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET is_archived = ? WHERE conversation_id = ?",
                (int(is_archived), conversation_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None

    def set_folder(self, conversation_id: str, folder_id: str | None) -> ConversationRecord | None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE conversations SET folder_id = ? WHERE conversation_id = ?",
                (folder_id, conversation_id),
            )
            row = connection.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None

    def set_project(self, conversation_id: str, project_id: str | None) -> ConversationRecord | None:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET project_id = ? WHERE conversation_id = ?",
                (project_id, conversation_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None

    def relocate(
        self, conversation_id: str, *, folder_id: str | None, project_id: str | None
    ) -> ConversationRecord | None:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET folder_id = ?, project_id = ? WHERE conversation_id = ?",
                (folder_id, project_id, conversation_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        now = datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ?, is_title_custom = 1 WHERE conversation_id = ?",
                (title, to_utc_iso(now), conversation_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None

    def update_auto_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE conversations SET title = ? WHERE conversation_id = ? AND is_title_custom = 0",
                (title, conversation_id),
            )
            row = connection.execute(
                f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row_to_conversation_record(row) if row is not None else None


# ============================================================
# END: Relational Conversation Repository
# ============================================================
