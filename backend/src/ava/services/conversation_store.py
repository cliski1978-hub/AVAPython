"""In-memory AVA conversation store.

Holds the smallest generic conversation-state representation needed by the
current composition. This is Step 4.4 in-memory state only: no database,
cache, or queue. Archive/delete lifecycle management is deliberately out of
scope for now.
"""

from dataclasses import replace
from datetime import UTC, datetime

from ava.repositories.conversation_repository import (
    ConversationRecord,
    ConversationRepository,
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

    def create(self, conversation_id: str, *, title: str) -> ConversationRecord:
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
        )
        self._conversations[conversation_id] = record
        return record

    def get(self, conversation_id: str) -> ConversationRecord | None:
        """Return the conversation record for ``conversation_id``, or ``None``."""
        return self._conversations.get(conversation_id)

    def list(self) -> list[ConversationRecord]:
        """Return all conversation records in insertion order."""
        return list(self._conversations.values())

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        """Rename a conversation, refreshing its ``updated_at``.

        Returns:
            The updated record, or ``None`` if the conversation is unknown.
        """
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, title=title, updated_at=datetime.now(UTC))
        self._conversations[conversation_id] = updated
        return updated

    def clear(self) -> None:
        """Remove all conversation records (test/observability helper)."""
        self._conversations.clear()


# ============================================================
# END: Conversation Store
# ============================================================