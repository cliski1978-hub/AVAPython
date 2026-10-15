"""Repository-backed owner checks for authenticated Conversation APIs."""

from ava.repositories.conversation_repository import ConversationRepository


class RepositoryConversationAccess:
    """Authorize only the principal and tenant durably assigned to a Conversation."""

    def __init__(self, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    def can_access(self, principal_ref: str, tenant_ref: str | None, conversation_id: str) -> bool:
        try:
            return self._conversations.get_for_owner(conversation_id, principal_ref, tenant_ref) is not None
        except Exception:
            return False
