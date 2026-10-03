"""AVA-owned execution-context construction.

This service is the single authority for *which durable messages* a run may
send to a runtime, and it is deliberately the only place that answers that
question. Native and OpenHands receive the resulting neutral ``RunContext``;
neither re-derives history, re-orders turns, or re-reads the conversation
store.

The context policy, in one list:

1. A run's context is scoped to ``run.conversation_id``. Messages from any
   other conversation are unreachable — the port is conversation-scoped.
2. Context is the durable conversation prefix that ends with, and includes,
   ``run.source_user_message_id``. The source user message is therefore
   present exactly once, and no assistant answer to that same user message
   (an earlier regeneration) can leak into the new run.
3. Consecutive assistant messages collapse to the last one, which is the same
   structural rule the conversation transcript uses to render a regenerated
   turn. Superseded answers are not resurrected.
4. After collapsing, only assistant messages whose status resolves to
   ``complete`` remain. Status is resolved from the authoritative run via
   ``assistant_status_for_run``; a message with no resolvable run falls back
   to its own stored status, which is what a legacy client-authored message
   has. A superseded answer is not resurrected when a later answer for the
   same turn failed: that turn contributes its user message only.
5. ``run.assistant_message_id`` — the current run's own pending placeholder —
   is excluded.
6. User and system messages are never hidden, reordered, or merged.

Nothing here budgets tokens, opens a context window, summarizes, or retrieves
documents; those remain out of scope. No attachment or tool semantics are
introduced: a message's stored text is passed through as-is.
"""

from collections.abc import Sequence

from ava.contracts.conversations import (
    ContextMessage,
    MessageRole,
    MessageStatus,
    RunContext,
    assistant_status_for_run,
)
from ava.repositories.conversation_repository import ConversationRepository
from ava.repositories.message_repository import MessageRecord, MessageRepository
from ava.repositories.run_repository import RunRepository

# ============================================================
# BEGIN: Context Construction Errors
# ============================================================


class ContextConstructionError(ValueError):
    """Durable run/context state cannot produce an execution context."""


class ContextRunNotFoundError(ContextConstructionError):
    """No run exists for the requested run id."""


class ContextConversationNotFoundError(ContextConstructionError):
    """The run names a conversation that no longer exists."""


class ContextSourceMessageNotFoundError(ContextConstructionError):
    """The run's source user message is missing from its conversation."""


class ContextSourceMessageRoleError(ContextConstructionError):
    """The run's source message is not a user message."""


# ============================================================
# END: Context Construction Errors
# ============================================================


# ============================================================
# BEGIN: Context Construction Service
# ============================================================


class ContextConstructionService:
    """Builds the neutral execution context for a persisted run.

    The service programs against repository ports only. It holds no state
    between calls, performs no writes, and never consults a client-supplied
    transcript.
    """

    def __init__(
        self,
        *,
        run_repository: RunRepository,
        message_repository: MessageRepository,
        conversation_repository: ConversationRepository,
    ) -> None:
        """Construct the service over the durable read ports it needs.

        Args:
            run_repository: Reads the run whose relationships scope the
                context, and the authoritative lifecycle of each historical
                assistant message.
            message_repository: Reads a conversation's messages in stable
                append order.
            conversation_repository: Confirms the run's conversation still
                exists, so a dangling relationship is never mistaken for an
                empty conversation.
        """
        self._run_repository = run_repository
        self._message_repository = message_repository
        self._conversation_repository = conversation_repository

    def build_for_run(self, run_id: str) -> RunContext:
        """Return the durable context for ``run_id``.

        A ``RunContext`` with no messages means the run is not linked to a
        conversation (a legacy direct ``/runs`` caller); such runs keep their
        existing single-prompt behavior. Every other unresolved or
        inconsistent relationship raises a ``ContextConstructionError``
        subclass rather than degrading to a prompt-only run.
        """
        run = self._run_repository.get(run_id)
        if run is None:
            raise ContextRunNotFoundError(f"run {run_id} does not exist")
        if run.conversation_id is None:
            return RunContext()
        return self._build(
            run.conversation_id,
            run.source_user_message_id,
            exclude_message_id=run.assistant_message_id,
        )

    def build_for_source(
        self,
        conversation_id: str,
        source_user_message_id: str | None,
    ) -> RunContext:
        """Return the durable context for one conversation turn.

        This is the pre-run shape: the caller has already validated the pair
        and needs the context before the run record exists. ``None`` as the
        source message selects the legacy transcript rule.
        """
        return self._build(conversation_id, source_user_message_id)

    def _build(
        self,
        conversation_id: str,
        source_user_message_id: str | None,
        *,
        exclude_message_id: str | None = None,
    ) -> RunContext:
        """Resolve one conversation's canonical prefix into context messages."""
        if self._conversation_repository.get(conversation_id) is None:
            raise ContextConversationNotFoundError(f"conversation {conversation_id} does not exist")
        records = list(self._message_repository.list_for_conversation(conversation_id))
        if source_user_message_id is None:
            # Defensive legacy path. A run normally cannot carry a
            # conversation without a source message, because the run service
            # only ever writes the pair together. Use the conversation's own
            # visible transcript through its last user message so an ordinary
            # old conversation still produces sensible context.
            return RunContext(
                conversation_id=conversation_id,
                messages=self._visible_transcript(records, through_index=self._last_user_index(records)),
            )
        source_index = self._source_index(records, conversation_id, source_user_message_id)
        return RunContext(
            conversation_id=conversation_id,
            source_user_message_id=source_user_message_id,
            messages=self._visible_transcript(
                records,
                through_index=source_index,
                exclude_message_id=exclude_message_id,
            ),
        )

    def _source_index(
        self,
        records: Sequence[MessageRecord],
        conversation_id: str,
        source_user_message_id: str,
    ) -> int:
        """Locate and validate the run's source message in append order."""
        source = self._message_repository.get(conversation_id, source_user_message_id)
        if source is None:
            raise ContextSourceMessageNotFoundError(
                f"source message {source_user_message_id} does not exist in conversation {conversation_id}"
            )
        if source.role != MessageRole.USER:
            raise ContextSourceMessageRoleError(f"source message {source_user_message_id} is not a user message")
        for index, record in enumerate(records):
            if record.message_id == source_user_message_id:
                return index
        raise ContextSourceMessageNotFoundError(
            f"source message {source_user_message_id} is not part of conversation {conversation_id} order"
        )

    @staticmethod
    def _last_user_index(records: Sequence[MessageRecord]) -> int | None:
        """Return the index of the last user message, or ``None`` if there is none."""
        for index in range(len(records) - 1, -1, -1):
            if records[index].role == MessageRole.USER:
                return index
        return None

    def _visible_transcript(
        self,
        records: Sequence[MessageRecord],
        *,
        through_index: int | None,
        exclude_message_id: str | None = None,
    ) -> list[ContextMessage]:
        """Apply the collapse-then-complete policy to one conversation prefix.

        Args:
            records: The conversation's messages in stable append order.
            through_index: Last index the context may include; ``None``
                yields no context.
            exclude_message_id: A message to drop, used for the current run's
                own assistant placeholder.
        """
        if through_index is None:
            return []
        prefix = [
            record
            for record in records[: through_index + 1]
            if exclude_message_id is None or record.message_id != exclude_message_id
        ]
        collapsed: list[MessageRecord] = []
        for record in prefix:
            if record.role == MessageRole.ASSISTANT and collapsed and collapsed[-1].role == MessageRole.ASSISTANT:
                # A regenerated answer supersedes the previous answer for the
                # same turn. Collapse positionally, never by message text.
                collapsed[-1] = record
                continue
            collapsed.append(record)
        return [
            ContextMessage(
                message_id=record.message_id,
                role=record.role,
                content=record.content,
            )
            for record in collapsed
            if record.role != MessageRole.ASSISTANT or self._is_complete(record)
        ]

    def _is_complete(self, record: MessageRecord) -> bool:
        """Whether a historical assistant message is eligible as context.

        The run is authoritative whenever the message links to one; otherwise
        the message's own stored status stands, which is the only status a
        legacy client-authored assistant message has.
        """
        if record.source_run_id is None:
            return record.status == MessageStatus.COMPLETE
        run = self._run_repository.get(record.source_run_id)
        if run is None:
            return record.status == MessageStatus.COMPLETE
        return assistant_status_for_run(run.status) == MessageStatus.COMPLETE


# ============================================================
# END: Context Construction Service
# ============================================================
