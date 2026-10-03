"""AVA-owned repository port for flat conversation folders."""

from abc import ABC, abstractmethod
from collections.abc import Collection
from datetime import datetime

from ava.repositories.conversation_folder import ConversationFolderRecord


class ConversationFolderRepository(ABC):
    """Persistence operations for folder metadata and atomic folder removal."""

    @abstractmethod
    def create(self, folder: ConversationFolderRecord) -> ConversationFolderRecord:
        raise NotImplementedError

    @abstractmethod
    def get(self, folder_id: str) -> ConversationFolderRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list(self) -> Collection[ConversationFolderRecord]:
        raise NotImplementedError

    @abstractmethod
    def rename(self, folder_id: str, name: str, updated_at: datetime) -> ConversationFolderRecord | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, folder_id: str) -> bool:
        """Delete folder and clear its conversation references atomically."""
        raise NotImplementedError
