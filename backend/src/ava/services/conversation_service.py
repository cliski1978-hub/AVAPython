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
from ava.repositories.attachment_content_store import AttachmentContentStore
from ava.repositories.conversation_folder_repository import ConversationFolderRepository
from ava.repositories.conversation_hard_delete import (
    ActiveConversationRunDeletionError,
    ConversationHardDeleteCoordinator,
)
from ava.repositories.conversation_repository import (
    ConversationRecord,
    ConversationRepository,
)
from ava.repositories.message_repository import MessageRecord, MessageRepository
from ava.repositories.project_repository import ProjectRepository
from ava.repositories.run_event_repository import RunEventRepository
from ava.repositories.run_repository import RunRepository
from ava.services.project_service import ProjectNotFoundError

DEFAULT_CONVERSATION_TITLE = "New Conversation"
CONVERSATION_TITLE_MAX_LENGTH = 40


def _derive_auto_title(prompt: str) -> str:
    single_line = " ".join(prompt.split())
    if len(single_line) <= CONVERSATION_TITLE_MAX_LENGTH:
        return single_line
    return f"{single_line[:CONVERSATION_TITLE_MAX_LENGTH].rstrip()}…"


# ============================================================
# BEGIN: Conversation Domain Errors
# ============================================================


class ConversationNotFoundError(Exception):
    """Raised when an operation targets an unknown conversation."""


class DuplicateConversationError(Exception):
    """Raised when a conversation identifier collides with an existing one."""


class ConversationFolderNotFoundForCreationError(Exception):
    """Raised when a new conversation names a Folder that no longer exists."""


class DuplicateMessageError(Exception):
    """Raised when a message identifier collides with an existing one."""


class ConversationHasActiveRunError(Exception):
    """Raised when hard deletion would remove a conversation with an active run."""

    def __init__(self, conversation_id: str, run_ids: tuple[str, ...]) -> None:
        self.conversation_id = conversation_id
        self.run_ids = run_ids
        super().__init__(f"Conversation has active runs: {', '.join(run_ids)}")


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
        hard_delete_coordinator: ConversationHardDeleteCoordinator | None = None,
        attachment_content_store: AttachmentContentStore | None = None,
        project_repository: ProjectRepository | None = None,
        folder_repository: ConversationFolderRepository | None = None,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._message_repository = message_repository
        self._run_repository = run_repository
        self._run_event_repository = run_event_repository
        self._hard_delete_coordinator = hard_delete_coordinator
        self._attachment_content_store = attachment_content_store
        self._project_repository = project_repository
        self._folder_repository = folder_repository

    def create_conversation(
        self, title: str | None = None, *, folder_id: str | None = None,
        owner_principal_ref: str | None = None, owner_tenant_ref: str | None = None,
    ) -> ConversationResponse:
        """Create a new conversation, returning its response contract.

        Args:
            title: Optional initial title; blank/omitted values resolve to
                ``DEFAULT_CONVERSATION_TITLE``.

        Returns:
            The created conversation's response contract.

        Raises:
            DuplicateConversationError: If a conversation identifier collides.
        """
        if folder_id is not None:
            if self._folder_repository is None:
                raise RuntimeError("Folder conversation creation is not configured")
            folder = self._folder_repository.get(folder_id)
            if (
                folder is None
                or folder.owner_principal_ref != owner_principal_ref
                or folder.owner_tenant_ref != owner_tenant_ref
            ):
                raise ConversationFolderNotFoundForCreationError(folder_id)
        return self._create_conversation(
            title=title, project_id=None, folder_id=folder_id,
            owner_principal_ref=owner_principal_ref, owner_tenant_ref=owner_tenant_ref,
        )

    def create_conversation_in_project(
        self, project_id: str, title: str | None = None, *,
        owner_principal_ref: str | None = None, owner_tenant_ref: str | None = None,
    ) -> ConversationResponse:
        """Create a conversation with Project membership in its first durable write.

        Archived Projects remain readable and writable: Project archive is
        informational in the current lifecycle model and does not block edits.
        """
        if self._project_repository is None:
            raise RuntimeError("Project conversation creation is not configured")
        project = self._project_repository.get(project_id)
        if project is None or (
            project.owner_principal_ref != owner_principal_ref or project.owner_tenant_ref != owner_tenant_ref
        ):
            raise ProjectNotFoundError(project_id)
        return self._create_conversation(
            title=title, project_id=project_id, folder_id=None,
            owner_principal_ref=owner_principal_ref, owner_tenant_ref=owner_tenant_ref,
        )

    def _create_conversation(
        self, *, title: str | None, project_id: str | None, folder_id: str | None,
        owner_principal_ref: str | None = None, owner_tenant_ref: str | None = None,
    ) -> ConversationResponse:
        """Share normal identity, title, timestamp, and persistence semantics."""
        resolved_title = (title or "").strip() or DEFAULT_CONVERSATION_TITLE
        is_title_custom = bool((title or "").strip())
        try:
            conversation_id = str(uuid4())
            if folder_id is not None:
                if is_title_custom:
                    record = self._conversation_repository.create(
                        conversation_id, title=resolved_title, folder_id=folder_id, is_title_custom=True,
                        owner_principal_ref=owner_principal_ref, owner_tenant_ref=owner_tenant_ref,
                    )
                else:
                    record = self._conversation_repository.create(
                        conversation_id, title=resolved_title, folder_id=folder_id,
                        owner_principal_ref=owner_principal_ref, owner_tenant_ref=owner_tenant_ref
                    )
            elif project_id is not None:
                if is_title_custom:
                    record = self._conversation_repository.create(
                        conversation_id, title=resolved_title, project_id=project_id, is_title_custom=True,
                        owner_principal_ref=owner_principal_ref, owner_tenant_ref=owner_tenant_ref
                    )
                else:
                    record = self._conversation_repository.create(
                        conversation_id, title=resolved_title, project_id=project_id,
                        owner_principal_ref=owner_principal_ref, owner_tenant_ref=owner_tenant_ref
                    )
            elif is_title_custom:
                record = self._conversation_repository.create(
                    conversation_id, title=resolved_title, is_title_custom=True,
                    owner_principal_ref=owner_principal_ref, owner_tenant_ref=owner_tenant_ref
                )
            else:
                record = self._conversation_repository.create(
                    conversation_id, title=resolved_title,
                    owner_principal_ref=owner_principal_ref, owner_tenant_ref=owner_tenant_ref,
                )
        except ValueError as exc:
            raise DuplicateConversationError(f"Conversation already exists: {exc}") from exc
        return _conversation_to_response(record)

    def get_conversation(self, conversation_id: str) -> ConversationResponse | None:
        """Return the conversation, or ``None`` if it is unknown."""
        record = self._conversation_repository.get(conversation_id)
        if record is None:
            return None
        return _conversation_to_response(record)

    def list_conversations(self, search: str | None = None) -> ConversationListResponse:
        """Return the canonical ordered list, optionally searching titles."""
        records = self._conversation_repository.list(search)
        return ConversationListResponse(conversations=[_conversation_to_response(record) for record in records])

    def list_conversations_for_owner(
        self, principal_ref: str, tenant_ref: str | None, search: str | None = None
    ) -> ConversationListResponse:
        records = self._conversation_repository.list_for_owner(principal_ref, tenant_ref, search)
        return ConversationListResponse(conversations=[_conversation_to_response(record) for record in records])

    def list_project_conversations(self, project_id: str) -> ConversationListResponse:
        """Validate a Project, then return all of its conversations in canonical order."""
        if self._project_repository is None:
            raise RuntimeError("Project conversation listing is not configured")
        if self._project_repository.get(project_id) is None:
            raise ProjectNotFoundError(project_id)
        records = self._conversation_repository.list_by_project(project_id)
        return ConversationListResponse(conversations=[_conversation_to_response(record) for record in records])

    def list_project_conversations_for_owner(
        self, project_id: str, principal_ref: str, tenant_ref: str | None
    ) -> ConversationListResponse:
        if self._project_repository is None:
            raise RuntimeError("Project conversation listing is not configured")
        if self._project_repository.get(project_id) is None:
            raise ProjectNotFoundError(project_id)
        records = self._conversation_repository.list_by_project_for_owner(project_id, principal_ref, tenant_ref)
        return ConversationListResponse(conversations=[_conversation_to_response(record) for record in records])

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

    def set_pinned(self, conversation_id: str, is_pinned: bool) -> ConversationResponse | None:
        """Persist the requested pin state, returning the updated snapshot."""
        record = self._conversation_repository.set_pinned(conversation_id, is_pinned)
        return _conversation_to_response(record) if record is not None else None

    def set_archived(self, conversation_id: str, is_archived: bool) -> ConversationResponse | None:
        """Persist the requested archive state, returning the updated snapshot."""
        record = self._conversation_repository.set_archived(conversation_id, is_archived)
        return _conversation_to_response(record) if record is not None else None

    def set_project(self, conversation_id: str, project_id: str | None) -> ConversationResponse | None:
        """Assign, move, or unassign a Project without changing conversation activity."""
        if self._conversation_repository.get(conversation_id) is None:
            return None
        if project_id is not None:
            if self._project_repository is None:
                raise RuntimeError("Project assignment is not configured")
            if self._project_repository.get(project_id) is None:
                raise ProjectNotFoundError(project_id)
        record = self._conversation_repository.set_project(conversation_id, project_id)
        return _conversation_to_response(record) if record is not None else None

    def relocate(
        self,
        conversation_id: str,
        *,
        destination_type: str,
        destination_id: str | None,
    ) -> ConversationResponse | None:
        """Move a conversation to exactly one organizational destination."""
        if self._conversation_repository.get(conversation_id) is None:
            return None
        folder_id = project_id = None
        if destination_type == "folder":
            if destination_id is None:
                raise ValueError("Folder destination requires an id")
            if self._folder_repository is None or self._folder_repository.get(destination_id) is None:
                from ava.services.conversation_folder_service import ConversationFolderNotFoundError

                raise ConversationFolderNotFoundError(destination_id)
            folder_id = destination_id
        elif destination_type == "project":
            if destination_id is None:
                raise ValueError("Project destination requires an id")
            if self._project_repository is None or self._project_repository.get(destination_id) is None:
                raise ProjectNotFoundError(destination_id)
            project_id = destination_id
        elif destination_type != "ungrouped":
            raise ValueError(f"Unknown conversation destination: {destination_type}")
        record = self._conversation_repository.relocate(conversation_id, folder_id=folder_id, project_id=project_id)
        return _conversation_to_response(record) if record is not None else None

    def delete_conversation(self, conversation_id: str) -> bool:
        """Permanently delete a conversation and its owned records.

        Returns false for an unknown conversation. This service operation is
        internal; transport routes are added separately.
        """
        if self._hard_delete_coordinator is None:
            raise RuntimeError("Conversation hard delete is not configured")
        try:
            deletion = self._hard_delete_coordinator.delete(conversation_id)
        except ActiveConversationRunDeletionError as exc:
            raise ConversationHasActiveRunError(exc.conversation_id, exc.run_ids) from exc
        if deletion is None:
            return False
        if self._attachment_content_store is not None:
            for storage_key in deletion.attachment_storage_keys:
                self._attachment_content_store.delete(storage_key)
        return True

    def delete_conversations(self, conversation_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Hard-delete several conversation aggregates through the same lifecycle boundary."""
        if self._hard_delete_coordinator is None:
            raise RuntimeError("Conversation hard delete is not configured")
        try:
            deletion = self._hard_delete_coordinator.delete_many(conversation_ids)
        except ActiveConversationRunDeletionError as exc:
            raise ConversationHasActiveRunError(exc.conversation_id, exc.run_ids) from exc
        if self._attachment_content_store is not None:
            for storage_key in deletion.attachment_storage_keys:
                self._attachment_content_store.delete(storage_key)
        return deletion.deleted_conversation_ids

    def delete_project_conversations(self, project_id: str) -> tuple[str, ...]:
        """Hard-delete every current Project conversation through the conversation lifecycle."""
        records = self._conversation_repository.list_by_project(project_id)
        return self.delete_conversations(tuple(record.conversation_id for record in records))

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
        conversation = self._conversation_repository.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(f"Conversation not found: {conversation_id}")
        first_user_message = (
            role == MessageRole.USER
            and not conversation.is_title_custom
            and not any(
                message.role == MessageRole.USER
                for message in self._message_repository.list_for_conversation(conversation_id)
            )
        )
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
        if first_user_message:
            self._conversation_repository.update_auto_title(conversation_id, _derive_auto_title(content))
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
        is_pinned=record.is_pinned,
        is_archived=record.is_archived,
        folder_id=record.folder_id,
        project_id=record.project_id,
        is_title_custom=record.is_title_custom,
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
