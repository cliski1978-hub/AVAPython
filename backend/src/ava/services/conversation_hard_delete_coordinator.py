"""Atomic in-memory adapter for conversation hard deletion."""

from copy import deepcopy
from dataclasses import replace

from ava.contracts.attachments import AttachmentOwnerType
from ava.repositories.conversation_hard_delete import (
    ActiveConversationRunDeletionError,
    ConversationDeletion,
    ConversationHardDeleteCoordinator,
)
from ava.repositories.core_prompt_assignment import CorePromptScopeType
from ava.repositories.core_prompt_assignment_repository import CorePromptAssignmentRepository
from ava.services.attachment_store import InMemoryAttachmentRepository
from ava.services.context_summary_store import ContextSummaryStore
from ava.services.conversation_store import ConversationStore
from ava.services.message_store import MessageStore
from ava.services.run_event_store import RunEventStore
from ava.services.run_store import RunStore


class InMemoryConversationHardDeleteCoordinator(ConversationHardDeleteCoordinator):
    """Remove a conversation graph from the selected in-memory stores atomically."""

    def __init__(
        self,
        *,
        conversations: ConversationStore,
        messages: MessageStore,
        runs: RunStore,
        run_events: RunEventStore,
        attachments: InMemoryAttachmentRepository,
        assignments: CorePromptAssignmentRepository | None = None,
        context_summaries: ContextSummaryStore | None = None,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._runs = runs
        self._run_events = run_events
        self._attachments = attachments
        self._assignments = assignments
        self._context_summaries = context_summaries

    def delete(self, conversation_id: str) -> ConversationDeletion | None:
        if conversation_id not in self._conversations._conversations:
            return None
        snapshots = (
            deepcopy(self._conversations._conversations),
            deepcopy(self._messages._messages),
            deepcopy(self._runs._runs),
            deepcopy(self._run_events._events),
            deepcopy(self._attachments._attachments),
            deepcopy(self._attachments._storage_keys),
            deepcopy(self._assignments._items)
            if self._assignments is not None and hasattr(self._assignments, "_items")
            else None,
            deepcopy(getattr(self._context_summaries, "_items", None)),
        )
        try:
            messages = self._messages._messages.get(conversation_id, {})
            message_ids = set(messages)
            source_run_ids = {message.source_run_id for message in messages.values() if message.source_run_id}
            ambiguous_message_ids = {
                message_id
                for other_conversation_id, other_messages in self._messages._messages.items()
                if other_conversation_id != conversation_id
                for message_id in other_messages
            }
            externally_referenced_run_ids = {
                message.source_run_id
                for other_conversation_id, other_messages in self._messages._messages.items()
                if other_conversation_id != conversation_id
                for message in other_messages.values()
                if message.source_run_id
            }
            runs = {
                run_id: record
                for run_id, record in self._runs._runs.items()
                if record.conversation_id == conversation_id
                or (
                    record.conversation_id is None
                    and run_id in source_run_ids
                    and run_id not in externally_referenced_run_ids
                )
                or (
                    record.conversation_id is None
                    and run_id not in externally_referenced_run_ids
                    and record.source_user_message_id in message_ids - ambiguous_message_ids
                )
                or (
                    record.conversation_id is None
                    and run_id not in externally_referenced_run_ids
                    and record.assistant_message_id in message_ids - ambiguous_message_ids
                )
            }
            active_run_ids = tuple(run_id for run_id, record in runs.items() if record.status.is_active)
            if active_run_ids:
                raise ActiveConversationRunDeletionError(conversation_id, active_run_ids)
            run_ids = set(runs)
            storage_keys: list[str] = []
            for attachment_id, record in list(self._attachments._attachments.items()):
                if record.owner_type is AttachmentOwnerType.CONVERSATION and record.owner_id == conversation_id:
                    storage_keys.append(record.storage_key)
                    del self._attachments._attachments[attachment_id]
                    self._attachments._storage_keys.discard(record.storage_key)
                elif record.owner_type is AttachmentOwnerType.MESSAGE and record.owner_id in message_ids:
                    ambiguous = any(
                        other_id != conversation_id and record.owner_id in other_messages
                        for other_id, other_messages in self._messages._messages.items()
                    )
                    if ambiguous:
                        self._attachments._attachments[attachment_id] = replace(record, owner_type=None, owner_id=None)
                    else:
                        storage_keys.append(record.storage_key)
                        del self._attachments._attachments[attachment_id]
                        self._attachments._storage_keys.discard(record.storage_key)
            for other_conversation_id, other_messages in self._messages._messages.items():
                if other_conversation_id != conversation_id:
                    for message_id, message in other_messages.items():
                        if message.source_run_id in run_ids:
                            other_messages[message_id] = replace(message, source_run_id=None)
            for run_id in run_ids:
                self._run_events._events.pop(run_id, None)
                self._runs._runs.pop(run_id, None)
            self._messages._messages.pop(conversation_id, None)
            if self._assignments is not None:
                self._assignments.delete_for_scope(CorePromptScopeType.CONVERSATION, conversation_id)
            if self._context_summaries is not None:
                self._context_summaries.delete_for_conversation(conversation_id)
            del self._conversations._conversations[conversation_id]
            return ConversationDeletion(attachment_storage_keys=tuple(storage_keys))
        except BaseException:
            (
                self._conversations._conversations,
                self._messages._messages,
                self._runs._runs,
                self._run_events._events,
                self._attachments._attachments,
                self._attachments._storage_keys,
                assignment_snapshot,
                summary_snapshot,
            ) = snapshots
            if (
                assignment_snapshot is not None
                and self._assignments is not None
                and hasattr(self._assignments, "_items")
            ):
                self._assignments._items = assignment_snapshot
            if summary_snapshot is not None and self._context_summaries is not None:
                self._context_summaries._items = summary_snapshot
            raise

    def delete_many(self, conversation_ids: tuple[str, ...]) -> ConversationDeletion:
        snapshots = (
            deepcopy(self._conversations._conversations),
            deepcopy(self._messages._messages),
            deepcopy(self._runs._runs),
            deepcopy(self._run_events._events),
            deepcopy(self._attachments._attachments),
            deepcopy(self._attachments._storage_keys),
            deepcopy(self._assignments._items)
            if self._assignments is not None and hasattr(self._assignments, "_items")
            else None,
            deepcopy(getattr(self._context_summaries, "_items", None)),
        )
        storage_keys: list[str] = []
        deleted_ids: list[str] = []
        try:
            for conversation_id in dict.fromkeys(conversation_ids):
                deletion = self.delete(conversation_id)
                if deletion is not None:
                    storage_keys.extend(deletion.attachment_storage_keys)
                    deleted_ids.append(conversation_id)
        except BaseException:
            (
                self._conversations._conversations,
                self._messages._messages,
                self._runs._runs,
                self._run_events._events,
                self._attachments._attachments,
                self._attachments._storage_keys,
                assignment_snapshot,
                summary_snapshot,
            ) = snapshots
            if (
                assignment_snapshot is not None
                and self._assignments is not None
                and hasattr(self._assignments, "_items")
            ):
                self._assignments._items = assignment_snapshot
            if summary_snapshot is not None and self._context_summaries is not None:
                self._context_summaries._items = summary_snapshot
            raise
        return ConversationDeletion(tuple(storage_keys), tuple(deleted_ids))
