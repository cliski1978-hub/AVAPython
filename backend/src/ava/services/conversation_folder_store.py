"""In-memory folder repository adapter."""

from dataclasses import replace
from datetime import datetime

from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.repositories.conversation_folder_repository import ConversationFolderRepository
from ava.repositories.conversation_repository import ConversationRepository
from ava.repositories.core_prompt_assignment import CorePromptScopeType
from ava.repositories.core_prompt_assignment_repository import CorePromptAssignmentRepository


class ConversationFolderStore(ConversationFolderRepository):
    """Memory implementation with folder-delete reference cleanup."""

    def __init__(
        self, conversations: ConversationRepository, assignments: CorePromptAssignmentRepository | None = None
    ) -> None:
        self._conversations = conversations
        self._assignments = assignments
        self._folders: dict[str, ConversationFolderRecord] = {}

    def create(self, folder: ConversationFolderRecord) -> ConversationFolderRecord:
        if folder.id in self._folders:
            raise ValueError(f"Conversation folder {folder.id!r} already exists")
        self._folders[folder.id] = folder
        return folder

    def get(self, folder_id: str) -> ConversationFolderRecord | None:
        return self._folders.get(folder_id)

    def list(self) -> list[ConversationFolderRecord]:
        return sorted(self._folders.values(), key=lambda item: (item.name.casefold(), item.created_at, item.id))

    def rename(self, folder_id: str, name: str, updated_at: datetime) -> ConversationFolderRecord | None:
        folder = self._folders.get(folder_id)
        if folder is None:
            return None
        updated = replace(folder, name=name, updated_at=updated_at)
        self._folders[folder_id] = updated
        return updated

    def delete(self, folder_id: str) -> bool:
        folder = self._folders.get(folder_id)
        if folder is None:
            return False
        snapshots = {item.conversation_id: item for item in self._conversations.list() if item.folder_id == folder_id}
        try:
            for conversation_id in snapshots:
                self._conversations.set_folder(conversation_id, None)
            if self._assignments is not None:
                self._assignments.delete_for_scope(CorePromptScopeType.FOLDER, folder_id)
            del self._folders[folder_id]
        except BaseException:
            for conversation_id in snapshots:
                self._conversations.set_folder(conversation_id, folder_id)
            raise
        return True
