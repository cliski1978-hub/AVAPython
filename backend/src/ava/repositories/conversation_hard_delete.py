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
    """Result of one committed conversation deletion and its unshared blobs."""

    attachment_storage_keys: tuple[str, ...]


class ConversationHardDeleteCoordinator(ABC):
    """Atomically remove a conversation and its exclusively owned records."""

    @abstractmethod
    def delete(self, conversation_id: str) -> ConversationDeletion | None:
        """Delete the aggregate, or return ``None`` when the conversation is unknown."""
        raise NotImplementedError
