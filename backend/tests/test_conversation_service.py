"""ConversationService behavior tests (Step 4.4).

Prove the service owns the conversation/message domain invariants:

* identifier generation (service-owned UUIDs, never client-supplied);
* timezone-aware UTC timestamps produced by the service;
* the default title resolution for omitted/blank titles;
* repository duplicate collisions map onto explicit domain errors;
* messages only exist inside known conversations;
* message vocabulary (roles/status) matches the AVA-owned contract enums.
"""

from datetime import timedelta
from uuid import UUID

import pytest

from ava.contracts.conversations import (
    ConversationListResponse,
    ConversationMessagesResponse,
    MessageResponse,
    MessageRole,
    MessageStatus,
)
from ava.repositories import (
    ConversationRecord,
    ConversationRepository,
    MessageRecord,
    MessageRepository,
)
from ava.services.conversation_service import (
    DEFAULT_CONVERSATION_TITLE,
    ConversationNotFoundError,
    ConversationService,
    DuplicateConversationError,
    DuplicateMessageError,
)
from ava.services.conversation_store import ConversationStore
from ava.services.message_store import MessageStore

# ============================================================
# BEGIN: Fixtures
# ============================================================


def make_service() -> ConversationService:
    """Create a service backed by fresh in-memory stores."""
    return ConversationService(
        conversation_repository=ConversationStore(),
        message_repository=MessageStore(),
    )


class _FailingConversationRepository(ConversationRepository):
    """Conversation repository that always reports a duplicate id."""

    def create(self, conversation_id: str, *, title: str) -> ConversationRecord:
        raise ValueError(f"Conversation already exists: {conversation_id}")

    def get(self, conversation_id: str) -> ConversationRecord | None:
        return None

    def list(self) -> list[ConversationRecord]:
        return []

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        return None


class _FailingMessageRepository(MessageRepository):
    """Message repository that always reports a duplicate id."""

    def append(self, message: MessageRecord) -> MessageRecord:
        raise ValueError(f"Message already exists: {message.message_id}")

    def get(self, conversation_id: str, message_id: str) -> MessageRecord | None:
        return None

    def list_for_conversation(self, conversation_id: str) -> list[MessageRecord]:
        return []


# ============================================================
# END: Fixtures
# ============================================================


# ============================================================
# BEGIN: Create Conversation
# ============================================================


def test_create_conversation_assigns_default_title() -> None:
    """An omitted title resolves to the service's default."""
    service = make_service()
    conversation = service.create_conversation()

    assert conversation.title == DEFAULT_CONVERSATION_TITLE
    assert conversation.created_at == conversation.updated_at


def test_create_conversation_accepts_explicit_title_and_trims_blanks() -> None:
    service = make_service()

    titled = service.create_conversation(title="  My Project  ")
    assert titled.title == "My Project"

    blank = service.create_conversation(title="   ")
    assert blank.title == DEFAULT_CONVERSATION_TITLE

    empty = service.create_conversation(title="")
    assert empty.title == DEFAULT_CONVERSATION_TITLE


def test_create_conversation_mints_a_valid_ava_owned_uuid_identifier() -> None:
    service = make_service()
    conversation = service.create_conversation()

    assert UUID(conversation.conversation_id)
    assert str(UUID(conversation.conversation_id)) == conversation.conversation_id


def test_create_conversation_uses_aware_utc_timestamps() -> None:
    service = make_service()
    conversation = service.create_conversation()

    assert conversation.created_at.tzinfo is not None
    assert conversation.created_at.utcoffset() == timedelta(0)


def test_create_conversation_maps_duplicate_to_domain_error() -> None:
    service = ConversationService(
        conversation_repository=_FailingConversationRepository(),  # type: ignore[abstract]
        message_repository=MessageStore(),
    )
    with pytest.raises(DuplicateConversationError):
        service.create_conversation()


# ============================================================
# END: Create Conversation
# ============================================================


# ============================================================
# BEGIN: Read Conversation
# ============================================================


def test_get_conversation_returns_none_for_unknown() -> None:
    service = make_service()
    assert service.get_conversation("ghost") is None


def test_get_conversation_returns_created_conversation() -> None:
    service = make_service()
    created = service.create_conversation(title="Known")

    fetched = service.get_conversation(created.conversation_id)
    assert fetched is not None
    assert fetched.title == "Known"


def test_list_conversations_in_insertion_order() -> None:
    service = make_service()
    first = service.create_conversation(title="First")
    second = service.create_conversation(title="Second")

    conversations = service.list_conversations()
    assert isinstance(conversations, ConversationListResponse)
    assert [c.conversation_id for c in conversations.conversations] == [
        first.conversation_id,
        second.conversation_id,
    ]


def test_list_conversations_is_empty_before_any_create() -> None:
    service = make_service()
    assert service.list_conversations().conversations == []


# ============================================================
# END: Read Conversation
# ============================================================


# ============================================================
# BEGIN: Rename Conversation
# ============================================================


def test_rename_conversation_updates_title_and_updated_at() -> None:
    service = make_service()
    created = service.create_conversation(title="Old")
    before = created.updated_at

    renamed = service.update_title(created.conversation_id, "  New  ")
    assert renamed is not None
    assert renamed.title == "New"
    assert renamed.updated_at >= before
    assert service.get_conversation(created.conversation_id).title == "New"


def test_rename_unknown_conversation_returns_none() -> None:
    service = make_service()
    assert service.update_title("ghost", "New") is None


def test_rename_rejects_blank_title() -> None:
    service = make_service()
    created = service.create_conversation()
    with pytest.raises(ValueError):
        service.update_title(created.conversation_id, "   ")


# ============================================================
# END: Rename Conversation
# ============================================================


# ============================================================
# BEGIN: Append Message
# ============================================================


def test_append_message_to_known_conversation() -> None:
    service = make_service()
    conversation = service.create_conversation()

    message = service.append_message(
        conversation.conversation_id,
        content="Hello AVA",
        source_run_id="run-123",
    )

    assert isinstance(message, MessageResponse)
    assert message.conversation_id == conversation.conversation_id
    assert message.content == "Hello AVA"
    assert message.role == MessageRole.USER
    assert message.status == MessageStatus.COMPLETE
    assert message.source_run_id == "run-123"
    assert UUID(message.message_id)
    assert message.updated_at == message.created_at


def test_append_message_defaults_role_to_user_and_status_to_complete() -> None:
    service = make_service()
    conversation = service.create_conversation()

    message = service.append_message(conversation.conversation_id, content="Hi")

    assert message.role == MessageRole.USER
    assert message.status == MessageStatus.COMPLETE
    assert message.source_run_id is None


def test_append_message_allows_assistant_and_system_roles() -> None:
    service = make_service()
    conversation = service.create_conversation()

    assistant = service.append_message(
        conversation.conversation_id, content="Answer", role=MessageRole.ASSISTANT
    )
    system = service.append_message(
        conversation.conversation_id, content="Notice", role=MessageRole.SYSTEM
    )

    assert assistant.role == MessageRole.ASSISTANT
    assert system.role == MessageRole.SYSTEM


def test_append_message_to_unknown_conversation_raises() -> None:
    service = make_service()
    with pytest.raises(ConversationNotFoundError):
        service.append_message("ghost", content="Hello")


def test_append_message_maps_duplicate_to_domain_error() -> None:
    conversation_store = ConversationStore()
    conversation_store.create("conv-seeded", title="Seeded")
    failing = ConversationService(
        conversation_repository=conversation_store,
        message_repository=_FailingMessageRepository(),  # type: ignore[abstract]
    )
    with pytest.raises(DuplicateMessageError):
        failing.append_message("conv-seeded", content="Hi")


# ============================================================
# END: Append Message
# ============================================================


# ============================================================
# BEGIN: Read Messages
# ============================================================


def test_list_messages_preserves_append_order() -> None:
    service = make_service()
    conversation = service.create_conversation()

    service.append_message(conversation.conversation_id, content="One")
    service.append_message(conversation.conversation_id, content="Two")

    result = service.list_messages(conversation.conversation_id)
    assert isinstance(result, ConversationMessagesResponse)
    assert result.conversation_id == conversation.conversation_id
    assert [m.content for m in result.messages] == ["One", "Two"]


def test_list_messages_is_none_for_unknown_conversation() -> None:
    service = make_service()
    assert service.list_messages("ghost") is None


def test_list_messages_is_empty_for_new_conversation() -> None:
    service = make_service()
    conversation = service.create_conversation()
    assert service.list_messages(conversation.conversation_id).messages == []


def test_get_message_scoped_to_conversation() -> None:
    service = make_service()
    first = service.create_conversation()
    second = service.create_conversation()

    message = service.append_message(first.conversation_id, content="Hello")

    assert service.get_message(first.conversation_id, message.message_id) is not None
    assert service.get_message(second.conversation_id, message.message_id) is None
    assert service.get_message(first.conversation_id, "ghost") is None


# ============================================================
# END: Read Messages
# ============================================================