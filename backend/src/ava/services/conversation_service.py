"""AVA conversation and message application service.

Coordinates the conversation/run domain against the AVA-owned repository
ports. The service owns what a repository must not: conversation and message
identity generation, timezone-aware UTC timestamps, the default conversation
title, and the invariant that messages only exist inside known conversations.

The service programs against the ``ConversationRepository`` / ``MessageRepository``
ports, never the concrete in-memory stores. Composition (``create_app``)
injects implementations.
"""

from datetime import UTC, datetime
from uuid import uuid4

from ava.contracts.conversations import (
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationResponse,
    MessageResponse,
    MessageRole,
    MessageStatus,
    assistant_status_for_run,
)
from ava.repositories.conversation_repository import (
    ConversationRecord,
    ConversationRepository,
)
from ava.repositories.message_repository import MessageRecord, MessageRepository
from ava.repositories.run_event_repository import RunEventRepository
from ava.repositories.run_repository import RunRepository

DEFAULT_CONVERSATION_TITLE = "New Conversation"


# ============================================================
# BEGIN: Conversation Domain Errors
# ============================================================


class ConversationNotFoundError(Exception):
    """Raised when an operation targets an unknown conversation."""


class DuplicateConversationError(Exception):
    """Raised when a conversation identifier collides with an existing one."""


class DuplicateMessageError(Exception):
    """Raised when a message identifier collides with an existing one."""


# ============================================================
# END: Conversation Domain Errors
# ============================================================


# ============================================================
# BEGIN: Conversation Service
# ============================================================


class ConversationService:
    """Delegates conversation and message reads/writes to the repository ports.

    Args:
        conversation_repository: The injected conversation repository port.
        message_repository: The injected message repository port.

    The service generates identifiers and timestamps, resolves the default
    title, enforces conversation existence for message operations, and maps
    repository duplicate collisions onto explicit domain errors.
    """

    def __init__(
        self,
        *,
        conversation_repository: ConversationRepository,
        message_repository: MessageRepository,
        run_repository: RunRepository | None = None,
        run_event_repository: RunEventRepository | None = None,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._message_repository = message_repository
        self._run_repository = run_repository
        self._run_event_repository = run_event_repository

    def create_conversation(self, title: str | None = None) -> ConversationResponse:
        """Create a new conversation, returning its response contract.

        Args:
            title: Optional initial title; blank/omitted values resolve to
                ``DEFAULT_CONVERSATION_TITLE``.

        Returns:
            The created conversation's response contract.

        Raises:
            DuplicateConversationError: If a conversation identifier collides.
        """
        resolved_title = (title or "").strip() or DEFAULT_CONVERSATION_TITLE
        try:
            record = self._conversation_repository.create(
                str(uuid4()),
                title=resolved_title,
            )
        except ValueError as exc:
            raise DuplicateConversationError(
                f"Conversation already exists: {exc}"
            ) from exc
        return _conversation_to_response(record)

    def get_conversation(self, conversation_id: str) -> ConversationResponse | None:
        """Return the conversation, or ``None`` if it is unknown."""
        record = self._conversation_repository.get(conversation_id)
        if record is None:
            return None
        return _conversation_to_response(record)

    def list_conversations(self) -> ConversationListResponse:
        """Return all conversations in stable insertion order."""
        records = self._conversation_repository.list()
        return ConversationListResponse(
            conversations=[_conversation_to_response(record) for record in records]
        )

    def update_title(self, conversation_id: str, title: str) -> ConversationResponse | None:
        """Rename a conversation, returning the updated conversation.

        Args:
            conversation_id: The conversation identifier.
            title: The new, non-blank title.

        Returns:
            The updated conversation, or ``None`` if it is unknown.

        Raises:
            ValueError: If ``title`` is blank after trimming (defense in
                depth; the update contract already rejects blank titles).
        """
        trimmed_title = title.strip()
        if not trimmed_title:
            raise ValueError("title must not be blank")
        record = self._conversation_repository.update_title(conversation_id, trimmed_title)
        if record is None:
            return None
        return _conversation_to_response(record)

    def append_message(
        self,
        conversation_id: str,
        *,
        content: str,
        role: MessageRole = MessageRole.USER,
        source_run_id: str | None = None,
    ) -> MessageResponse:
        """Append a message to a known conversation.

        The message is stored with ``MessageStatus.COMPLETE``: no
        message-authoring pipeline exists yet (Step 4.4), so there is nothing
        to await or re-visit.

        Args:
            conversation_id: The conversation to append to.
            content: The message content.
            role: The AVA message role (defaults to ``user``).
            source_run_id: Optional AVA run that produced the message.

        Returns:
            The appended message's response contract.

        Raises:
            ConversationNotFoundError: If the conversation is unknown.
            DuplicateMessageError: If a message identifier collides.
        """
        if self._conversation_repository.get(conversation_id) is None:
            raise ConversationNotFoundError(f"Conversation not found: {conversation_id}")
        now = datetime.now(UTC)
        message = MessageRecord(
            message_id=str(uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            status=MessageStatus.COMPLETE,
            source_run_id=source_run_id,
            created_at=now,
            updated_at=now,
        )
        try:
            self._message_repository.append(message)
        except ValueError as exc:
            raise DuplicateMessageError(f"Message already exists: {exc}") from exc
        return self._message_to_response(message)

    def get_message(self, conversation_id: str, message_id: str) -> MessageResponse | None:
        """Return a message within a conversation, or ``None`` if unknown.

        The message is looked up scoped to its conversation; return ``None``
        for an unknown conversation, an unknown message, or a known message
        from a different conversation.
        """
        record = self._message_repository.get(conversation_id, message_id)
        if record is None:
            return None
        return self._message_to_response(record)

    def list_messages(self, conversation_id: str) -> ConversationMessagesResponse | None:
        """Return a conversation's messages in stable append order.

        Returns ``None`` for an unknown conversation (distinguishable from an
        empty conversation, which yields an empty list).
        """
        if self._conversation_repository.get(conversation_id) is None:
            return None
        records = self._message_repository.list_for_conversation(conversation_id)
        return ConversationMessagesResponse(
            conversation_id=conversation_id,
            messages=[self._message_to_response(record) for record in records],
        )

    def _message_to_response(self, record: MessageRecord) -> MessageResponse:
        status = record.status
        error_code: str | None = None
        source_user_message_id: str | None = None
        if record.role == MessageRole.ASSISTANT and record.source_run_id and self._run_repository:
            run = self._run_repository.get(record.source_run_id)
            if run is not None:
                status = assistant_status_for_run(run.status)
                source_user_message_id = run.source_user_message_id
                if run.status.value == "failed" and self._run_event_repository is not None:
                    failed = [
                        event
                        for event in self._run_event_repository.get_events(run.run_id)
                        if event.event_type.value == "run_failed"
                    ]
                    if failed:
                        value = failed[-1].payload.get("error_code")
                        error_code = value if isinstance(value, str) else None
        return _message_to_response(
            record,
            status=status,
            source_user_message_id=source_user_message_id,
            error_code=error_code,
        )


# ============================================================
# END: Conversation Service
# ============================================================


# ============================================================
# BEGIN: Record → Response Conversion
# ============================================================


def _conversation_to_response(record: ConversationRecord) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=record.conversation_id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _message_to_response(
    record: MessageRecord,
    *,
    status: MessageStatus | None = None,
    source_user_message_id: str | None = None,
    error_code: str | None = None,
) -> MessageResponse:
    return MessageResponse(
        message_id=record.message_id,
        conversation_id=record.conversation_id,
        role=record.role,
        content=record.content,
        status=status or record.status,
        source_run_id=record.source_run_id,
        source_user_message_id=source_user_message_id,
        error_code=error_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ============================================================
# END: Record → Response Conversion
# ============================================================
