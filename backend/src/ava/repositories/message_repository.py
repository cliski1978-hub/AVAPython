"""AVA-owned message repository port.

Message persistence is deliberately conversation-agnostic, mirroring how
``RunEventRepository`` relates to run persistence: a durable adapter must be
able to store and enumerate messages without any conversation machinery. The
``ConversationService`` enforces that messages only exist inside known
conversations; a repository never checks conversation existence itself.

The port is framework-neutral: no SQL, ORM entities, sessions, transactions,
queries, rows, or database drivers. Inputs and outputs use the AVA-owned
``MessageRecord`` snapshot and primitive values only. Message identifiers
are caller-supplied; a repository never mints ids.
"""

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from ava.contracts.conversations import MessageRole, MessageStatus

# ============================================================
# BEGIN: Message Record
# ============================================================


@dataclass(frozen=True)
class MessageRecord:
    """AVA-owned snapshot of a message's state.

    ``created_at`` and ``updated_at`` are timezone-aware UTC timestamps
    (``datetime.now(UTC)`` semantics); durable adapters must preserve
    aware-UTC round-tripping. ``source_run_id`` optionally links the message
    to the AVA run that produced it — the minimum message/run linkage
    established in Step 4.4. No attachment/streaming machinery exists yet:
    both are deliberately out of Step 4.4 scope.
    """

    message_id: str
    conversation_id: str
    role: MessageRole
    content: str
    status: MessageStatus
    created_at: datetime
    updated_at: datetime
    source_run_id: str | None = None


# ============================================================
# END: Message Record
# ============================================================


# ============================================================
# BEGIN: Message Repository
# ============================================================


class MessageRepository(ABC):
    """Port that message repositories must satisfy.

    Responsibilities:

    * ``append`` — persist a new message; a duplicate id is an error.
    * ``get`` — read a message within a conversation, or ``None``.
    * ``list_for_conversation`` — enumerate a conversation's messages in
      stable append order.

    Deliberately not part of this port: message identity generation,
    message update/removal semantics, conversation existence checks, query
    language, and observability helpers (``clear``).
    """

    @abstractmethod
    def append(self, message: MessageRecord) -> MessageRecord:
        """Append a new message record.

        Args:
            message: The AVA-owned message snapshot to persist.

        Returns:
            The message as stored, unchanged.

        Raises:
            ValueError: If a message with this identifier already exists.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, conversation_id: str, message_id: str) -> MessageRecord | None:
        """Return the message within ``conversation_id``, or ``None``.

        Message lookup is scoped to its conversation: a message that exists
        under a different conversation is treated as unknown.
        """
        raise NotImplementedError

    @abstractmethod
    def list_for_conversation(self, conversation_id: str) -> Collection[MessageRecord]:
        """Return the conversation's messages in stable append order.

        Returns:
            An ordered immutable snapshot of the messages. An unknown
            conversation yields the empty collection (the port is
            conversation-agnostic; the service filters existence).
        """
        raise NotImplementedError


# ============================================================
# END: Message Repository
# ============================================================