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

    def create_folder(
        self, name: str, *, owner_principal_ref: str | None = None, owner_tenant_ref: str | None = None
    ) -> ConversationFolderRecord:
        normalized = self._normalize(name)
        now = datetime.now(UTC)
        return self._folders.create(
            ConversationFolderRecord(str(uuid4()), normalized, now, now, owner_principal_ref, owner_tenant_ref)
        )

    def get_folder(self, folder_id: str) -> ConversationFolderRecord:
        folder = self._folders.get(folder_id)
        if folder is None:
            raise ConversationFolderNotFoundError(folder_id)
        return folder

    def list_folders(self) -> list[ConversationFolderRecord]:
        return list(self._folders.list())

    def list_folders_for_owner(self, principal_ref: str, tenant_ref: str | None) -> list[ConversationFolderRecord]:
        return [
            item for item in self._folders.list()
            if item.owner_principal_ref == principal_ref and item.owner_tenant_ref == tenant_ref
        ]

    def get_folder_for_owner(
        self, folder_id: str, principal_ref: str, tenant_ref: str | None
    ) -> ConversationFolderRecord:
        folder = self._folders.get(folder_id)
        if folder is None or folder.owner_principal_ref != principal_ref or folder.owner_tenant_ref != tenant_ref:
            raise ConversationFolderNotFoundError(folder_id)
        return folder

    def rename_folder(
        self, folder_id: str, name: str, *, principal_ref: str | None = None, tenant_ref: str | None = None
    ) -> ConversationFolderRecord:
        if principal_ref is not None:
            self.get_folder_for_owner(folder_id, principal_ref, tenant_ref)
        normalized = self._normalize(name)
        folder = self._folders.rename(folder_id, normalized, datetime.now(UTC))
        if folder is None:
            raise ConversationFolderNotFoundError(folder_id)
        return folder

    def delete_folder(self, folder_id: str, *, principal_ref: str | None = None, tenant_ref: str | None = None) -> None:
        if principal_ref is not None:
            self.get_folder_for_owner(folder_id, principal_ref, tenant_ref)
        if not self._folders.delete(folder_id):
            raise ConversationFolderNotFoundError(folder_id)

    def set_conversation_folder(self, conversation_id: str, folder_id: str | None) -> ConversationRecord:
        if self._conversations.get(conversation_id) is None:
            raise ConversationNotFoundForFolderError(conversation_id)
        if folder_id is not None:
            folder = self._folders.get(folder_id)
            conversation = self._conversations.get(conversation_id)
            if folder is None or conversation is None or (
                folder.owner_principal_ref != conversation.owner_principal_ref
                or folder.owner_tenant_ref != conversation.owner_tenant_ref
            ):
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
