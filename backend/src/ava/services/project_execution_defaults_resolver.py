"""Read Project execution preferences through canonical Conversation membership."""

from ava.execution.selection import ProjectExecutionPreference
from ava.repositories.conversation_repository import ConversationRepository
from ava.repositories.project_repository import ProjectRepository


class ProjectExecutionDefaultsResolver:
    """Derive Project execution defaults only through a stored conversation link."""

    def __init__(self, *, conversations: ConversationRepository, projects: ProjectRepository) -> None:
        self._conversations = conversations
        self._projects = projects

    def resolve_for_conversation(self, conversation_id: str | None) -> ProjectExecutionPreference | None:
        """Return preferences for the conversation's current Project, if any.

        The caller supplies only a conversation ID. Project identity always
        comes from the authoritative Conversation record, so an arbitrary
        Project ID cannot influence run selection.
        """
        if conversation_id is None:
            return None
        conversation = self._conversations.get(conversation_id)
        if conversation is None or conversation.project_id is None:
            return None
        project = self._projects.get(conversation.project_id)
        if project is None:
            return None
        return ProjectExecutionPreference(
            project_id=project.id,
            runtime_key=project.execution_defaults.runtime_key,
            model_id=project.execution_defaults.model_id,
        )
