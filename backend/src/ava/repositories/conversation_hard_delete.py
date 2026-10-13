"""Conversation aggregate hard-delete boundary."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ActiveConversationRunDeletionError(Exception):
    """Raised when deleting a conversation that still has an active run."""

    def __init__(self, conversation_id: str, run_ids: tuple[str, ...]) -> None:
        self.conversation_id = conversation_id
        self.run_ids = run_ids
        super().__init__(f"Conversation {conversation_id} has active runs: {', '.join(run_ids)}")


@dataclass(frozen=True)
class ConversationDeletion:
    """Result of committed conversation deletions and their unshared blobs."""

    attachment_storage_keys: tuple[str, ...]
    deleted_conversation_ids: tuple[str, ...] = ()


class ConversationHardDeleteCoordinator(ABC):
    """Atomically remove a conversation and its exclusively owned records."""

    @abstractmethod
    def delete(self, conversation_id: str) -> ConversationDeletion | None:
        """Delete the aggregate, or return ``None`` when the conversation is unknown."""
        raise NotImplementedError

    def delete_many(self, conversation_ids: tuple[str, ...]) -> ConversationDeletion:
        """Delete several aggregates; adapters with transactions should override atomically."""
        storage_keys: list[str] = []
        deleted_ids: list[str] = []
        for conversation_id in dict.fromkeys(conversation_ids):
            deletion = self.delete(conversation_id)
            if deletion is not None:
                storage_keys.extend(deletion.attachment_storage_keys)
                deleted_ids.append(conversation_id)
        return ConversationDeletion(tuple(storage_keys), tuple(deleted_ids))
