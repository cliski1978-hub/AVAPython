"""In-memory AVA conversation store.

Holds the smallest generic conversation-state representation needed by the
current composition. This is Step 4.4 in-memory state only: no database,
cache, or queue. Archive/delete lifecycle management is deliberately out of
scope for now.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime

from ava.repositories.conversation_repository import (
    ConversationRecord,
    ConversationRepository,
    normalize_conversation_search,
)

# ============================================================
# BEGIN: Conversation Store
# ============================================================


class ConversationStore(ConversationRepository):
    """In-memory, AVA-owned store of conversation records keyed by id.

    This is the in-memory ``ConversationRepository`` implementation used by
    the current composition. Step 4.4 state only: no database, cache, or
    queue.
    """

    def __init__(self) -> None:
        self._conversations: dict[str, ConversationRecord] = {}

    def create(
        self,
        conversation_id: str,
        *,
        title: str,
        project_id: str | None = None,
        folder_id: str | None = None,
        is_title_custom: bool = False,
    ) -> ConversationRecord:
        """Create a new conversation record.

        Args:
            conversation_id: The AVA-generated conversation identifier.
            title: The conversation's initial title.

        Returns:
            The newly created record.

        Raises:
            ValueError: If a conversation with this identifier exists.
        """
        if conversation_id in self._conversations:
            raise ValueError(f"Conversation already exists: {conversation_id}")
        now = datetime.now(UTC)
        record = ConversationRecord(
            conversation_id=conversation_id,
            title=title,
            created_at=now,
            updated_at=now,
            project_id=project_id,
            folder_id=folder_id,
            is_title_custom=is_title_custom,
        )
        self._conversations[conversation_id] = record
        return record

    def get(self, conversation_id: str) -> ConversationRecord | None:
        """Return the conversation record for ``conversation_id``, or ``None``."""
        return self._conversations.get(conversation_id)

    def list(self, search: str | None = None) -> list[ConversationRecord]:
        """Return records in canonical order, optionally matching title text."""
        records = list(self._conversations.values())
        # Stable multi-pass sorting keeps the final identity key ascending
        # while the preceding ordering keys are descending.
        records.sort(key=lambda record: record.conversation_id)
        records.sort(
            key=lambda record: (record.is_pinned, record.updated_at, record.created_at),
            reverse=True,
        )
        normalized = normalize_conversation_search(search)
        if normalized is None:
            return records
        needle = normalized.lower()
        return [record for record in records if needle in record.title.lower()]

    def list_by_project(self, project_id: str) -> Collection[ConversationRecord]:
        """Return a canonically ordered snapshot for exactly one Project."""
        return [record for record in self.list() if record.project_id == project_id]

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        """Rename a conversation, refreshing its ``updated_at``.

        Returns:
            The updated record, or ``None`` if the conversation is unknown.
        """
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, title=title, updated_at=datetime.now(UTC), is_title_custom=True)
        self._conversations[conversation_id] = updated
        return updated

    def update_auto_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        record = self._conversations.get(conversation_id)
        if record is None or record.is_title_custom:
            return record
        updated = replace(record, title=title)
        self._conversations[conversation_id] = updated
        return updated

    def set_pinned(self, conversation_id: str, is_pinned: bool) -> ConversationRecord | None:
        """Set the requested pin state without changing other conversation fields."""
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, is_pinned=is_pinned)
        self._conversations[conversation_id] = updated
        return updated

    def set_archived(self, conversation_id: str, is_archived: bool) -> ConversationRecord | None:
        """Set the requested archive state without changing other conversation fields."""
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, is_archived=is_archived)
        self._conversations[conversation_id] = updated
        return updated

    def set_folder(self, conversation_id: str, folder_id: str | None) -> ConversationRecord | None:
        current = self._conversations.get(conversation_id)
        if current is None:
            return None
        updated = replace(current, folder_id=folder_id)
        self._conversations[conversation_id] = updated
        return updated

    def set_project(self, conversation_id: str, project_id: str | None) -> ConversationRecord | None:
        current = self._conversations.get(conversation_id)
        if current is None:
            return None
        updated = replace(current, project_id=project_id)
        self._conversations[conversation_id] = updated
        return updated

    def relocate(
        self, conversation_id: str, *, folder_id: str | None, project_id: str | None
    ) -> ConversationRecord | None:
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, folder_id=folder_id, project_id=project_id)
        self._conversations[conversation_id] = updated
        return updated

    def clear(self) -> None:
        """Remove all conversation records (test/observability helper)."""
        self._conversations.clear()


# ============================================================
# END: Conversation Store
# ============================================================
