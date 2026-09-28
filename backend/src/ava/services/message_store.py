"""In-memory AVA message store.

Holds messages keyed per conversation in stable append order. Assistant
content can be replaced with the latest durable snapshot through the repository
port; identity, role, ownership, creation time, and append order stay fixed.
"""

from dataclasses import replace
from datetime import UTC, datetime

from ava.repositories.message_repository import (
    MessageRecord,
    MessageRepository,
)

# ============================================================
# BEGIN: Message Store
# ============================================================


class MessageStore(MessageRepository):
    """In-memory, AVA-owned store of message records keyed by conversation.

    Messages are isolated per conversation and enumerated in stable append
    order. This is the in-memory ``MessageRepository`` implementation used by
    the current composition. Step 4.4 state only: no database, cache, or
    queue.
    """

    def __init__(self) -> None:
        self._messages: dict[str, dict[str, MessageRecord]] = {}

    def append(self, message: MessageRecord) -> MessageRecord:
        """Append a new message record.

        Args:
            message: The AVA-owned message snapshot to persist.

        Returns:
            The message as stored, unchanged.

        Raises:
            ValueError: If a message with this identifier already exists.
        """
        messages = self._messages.setdefault(message.conversation_id, {})
        if message.message_id in messages:
            raise ValueError(f"Message already exists: {message.message_id}")
        messages[message.message_id] = message
        return message

    def get(self, conversation_id: str, message_id: str) -> MessageRecord | None:
        """Return ``message_id`` within ``conversation_id``, or ``None``.

        Lookup is scoped to its conversation: a message that exists under a
        different conversation is treated as unknown.
        """
        return self._messages.get(conversation_id, {}).get(message_id)

    def list_for_conversation(self, conversation_id: str) -> list[MessageRecord]:
        """Return the conversation's messages in stable append order.

        An unknown conversation yields an empty list (the port is
        conversation-agnostic; the service filters existence).
        """
        return list(self._messages.get(conversation_id, {}).values())

    def update_content(self, conversation_id: str, message_id: str, content: str) -> MessageRecord | None:
        message = self._messages.get(conversation_id, {}).get(message_id)
        if message is None:
            return None
        updated = replace(message, content=content, updated_at=datetime.now(UTC))
        self._messages[conversation_id][message_id] = updated
        return updated

    def clear(self) -> None:
        """Remove all message records (test/observability helper)."""
        self._messages.clear()


# ============================================================
# END: Message Store
# ============================================================
