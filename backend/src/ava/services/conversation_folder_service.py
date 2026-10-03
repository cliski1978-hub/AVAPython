"""Application behavior for conversation folder CRUD and assignment."""

from datetime import UTC, datetime
from uuid import uuid4

from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.repositories.conversation_folder_repository import ConversationFolderRepository
from ava.repositories.conversation_repository import ConversationRecord, ConversationRepository


class ConversationFolderNotFoundError(Exception):
    """Raised when an unknown folder is requested or assigned."""


class ConversationNotFoundForFolderError(Exception):
    """Raised when folder assignment targets an unknown conversation."""


class InvalidConversationFolderNameError(ValueError):
    """Raised when a folder name is blank after trimming."""


class ConversationFolderService:
    def __init__(
        self,
        *,
        folder_repository: ConversationFolderRepository,
        conversation_repository: ConversationRepository,
    ) -> None:
        self._folders = folder_repository
        self._conversations = conversation_repository

    def create_folder(self, name: str) -> ConversationFolderRecord:
        normalized = self._normalize(name)
        now = datetime.now(UTC)
        return self._folders.create(ConversationFolderRecord(str(uuid4()), normalized, now, now))

    def get_folder(self, folder_id: str) -> ConversationFolderRecord:
        folder = self._folders.get(folder_id)
        if folder is None:
            raise ConversationFolderNotFoundError(folder_id)
        return folder

    def list_folders(self) -> list[ConversationFolderRecord]:
        return list(self._folders.list())

    def rename_folder(self, folder_id: str, name: str) -> ConversationFolderRecord:
        normalized = self._normalize(name)
        folder = self._folders.rename(folder_id, normalized, datetime.now(UTC))
        if folder is None:
            raise ConversationFolderNotFoundError(folder_id)
        return folder

    def delete_folder(self, folder_id: str) -> None:
        if not self._folders.delete(folder_id):
            raise ConversationFolderNotFoundError(folder_id)

    def set_conversation_folder(self, conversation_id: str, folder_id: str | None) -> ConversationRecord:
        if self._conversations.get(conversation_id) is None:
            raise ConversationNotFoundForFolderError(conversation_id)
        if folder_id is not None and self._folders.get(folder_id) is None:
            raise ConversationFolderNotFoundError(folder_id)
        updated = self._conversations.set_folder(conversation_id, folder_id)
        if updated is None:
            raise ConversationNotFoundForFolderError(conversation_id)
        return updated

    @staticmethod
    def _normalize(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise InvalidConversationFolderNameError("Folder name must not be blank.")
        return normalized
