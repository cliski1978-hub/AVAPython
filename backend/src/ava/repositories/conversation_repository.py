"""AVA-owned conversation repository port.

Expresses the conversation-domain semantics that ``ConversationService``
needs, so durable implementations (the in-memory store and the SQLite adapter)
can satisfy the same contract without changing conversation behavior.

The port is deliberately framework-neutral: no SQL, ORM entities, sessions,
transactions, queries, rows, or database drivers. Inputs and outputs use the
AVA-owned ``ConversationRecord`` snapshot and primitive values only.
Conversation identifiers are caller-supplied; a repository never mints ids.
"""

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

# ============================================================
# BEGIN: Conversation Record
# ============================================================


@dataclass(frozen=True)
class ConversationRecord:
    """AVA-owned snapshot of a conversation's state.

    ``created_at`` and ``updated_at`` are timezone-aware UTC timestamps
    (``datetime.now(UTC)`` semantics); durable adapters must preserve
    aware-UTC round-tripping. No archive field exists yet: lifecycle
    management (archive/delete) is deliberately out of Step 4.4 scope.
    """

    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime


# ============================================================
# END: Conversation Record
# ============================================================


# ============================================================
# BEGIN: Conversation Repository
# ============================================================


class ConversationRepository(ABC):
    """Port that conversation repositories must satisfy.

    Responsibilities:

    * ``create`` — open a new conversation; a duplicate id is an error.
    * ``get`` — read the current conversation snapshot, or ``None``.
    * ``list`` — enumerate conversations in stable insertion order.
    * ``update_title`` — rename a conversation, refreshing ``updated_at``.

    Deliberately not part of this port: conversation identity generation,
    archive/delete lifecycle management, sessions, transactions, query
    language, and observability helpers (``clear``).
    """

    @abstractmethod
    def create(self, conversation_id: str, *, title: str) -> ConversationRecord:
        """Create a new conversation record.

        Args:
            conversation_id: The AVA-generated conversation identifier.
            title: The conversation's initial title.

        Returns:
            The newly created snapshot.

        Raises:
            ValueError: If a conversation with this identifier exists.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, conversation_id: str) -> ConversationRecord | None:
        """Return the conversation's current snapshot, or ``None`` if unknown."""
        raise NotImplementedError

    @abstractmethod
    def list(self) -> Collection[ConversationRecord]:
        """Return all conversations in stable insertion order.

        Returns:
            An ordered immutable snapshot of every conversation.
        """
        raise NotImplementedError

    @abstractmethod
    def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        """Rename a conversation, refreshing its ``updated_at``.

        Returns:
            The updated snapshot, or ``None`` if the conversation is unknown.
        """
        raise NotImplementedError


# ============================================================
# END: Conversation Repository
# ============================================================