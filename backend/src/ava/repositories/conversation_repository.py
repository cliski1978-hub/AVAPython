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
    aware-UTC round-tripping.

    Organization metadata (Phase 5.42) is descriptive only. ``is_pinned`` and
    ``is_archived`` default to ``False`` and ``folder_id`` to ``None``, so every
    existing construction site keeps working unchanged.

    ``is_pinned``
        Marks a conversation that later sorting and display treat as pinned.
        Purely presentational: it never affects execution, run lifecycle, or
        durability.

    ``is_archived``
        A reversible hidden state. The conversation stays in the database and
        archiving never removes messages, runs, or events — archive is not
        delete. Listing is still unfiltered, so no conversation disappears.

    ``folder_id``
        A nullable, AVA-owned folder identifier expressing an organizational
        relationship only. It is not an execution reference. Folder identity
        is represented separately; referential integrity is not enforced by
        this domain record.

    ``project_id``
        A nullable relationship to one Project workspace. It is independent
        from folder membership and is not an execution reference in this
        phase. Project existence is validated by the service on assignment.
    """

    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    is_pinned: bool = False
    is_archived: bool = False
    folder_id: str | None = None
    project_id: str | None = None
    is_title_custom: bool = False


def normalize_conversation_search(search: str | None) -> str | None:
    """Trim a title-search term; an empty result means an unfiltered list."""
    if search is None:
        return None
    normalized = search.strip()
    return normalized or None


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
    * ``list`` — enumerate conversations in canonical pin/activity order,
      optionally filtering title substrings case-insensitively.
    * ``update_title`` — rename a conversation, refreshing ``updated_at``.

    Deliberately not part of this port: conversation identity generation,
    sessions, transactions, query language, and observability helpers
    (``clear``).

    Folder assignment and delete are absent by design. Pin and archive state
    are writable through their dedicated narrow methods. ``ConversationRecord``
    carries the organization fields so the domain
    can express them, but folder assignment and delete remain outside this port until their
    corresponding steps define those behaviors.
    """

    @abstractmethod
    def create(
        self,
        conversation_id: str,
        *,
        title: str,
        project_id: str | None = None,
        folder_id: str | None = None,
        is_title_custom: bool = False,
    ) -> ConversationRecord:
        """Create a new conversation record.

        Args:
            conversation_id: The AVA-generated conversation identifier.
            title: The conversation's initial title.
            project_id: Optional Project owner, written with the initial record.
            folder_id: Optional organizational Folder, written with the initial record.

        Returns:
            The newly created snapshot.

        Raises:
            ValueError: If a conversation with this identifier exists.
        """
        raise NotImplementedError

    def list_by_project(self, project_id: str) -> Collection[ConversationRecord]:
        """Return matching Project conversations in canonical list order.

        Implementations with query support should override this narrow read;
        this default preserves compatibility for small test adapters.
        """
        return [record for record in self.list() if record.project_id == project_id]

    @abstractmethod
    def get(self, conversation_id: str) -> ConversationRecord | None:
        """Return the conversation's current snapshot, or ``None`` if unknown."""
        raise NotImplementedError

    @abstractmethod
    def list(self, search: str | None = None) -> Collection[ConversationRecord]:
        """Return conversations in canonical order, optionally title-filtered.

        Missing, empty, and whitespace-only terms return every conversation.
        Non-empty terms match title substrings without regard to case.
        Pinned records come first, then ``updated_at`` descending, then
        ``created_at`` descending, then ``conversation_id`` ascending.

        Returns:
            An ordered snapshot of every matching conversation, without
            changing the repository's stored collection order.
        """
        raise NotImplementedError

    @abstractmethod
    def set_pinned(self, conversation_id: str, is_pinned: bool) -> ConversationRecord | None:
        """Set pin state only; preserve all other fields. Return None if unknown."""
        raise NotImplementedError

    @abstractmethod
    def set_archived(self, conversation_id: str, is_archived: bool) -> ConversationRecord | None:
        """Set archive state only; preserve all other fields. Return None if unknown."""
        raise NotImplementedError

    @abstractmethod
    def set_folder(self, conversation_id: str, folder_id: str | None) -> ConversationRecord | None:
        """Set the organizational folder only, preserving timestamps and state."""
        raise NotImplementedError

    @abstractmethod
    def set_project(self, conversation_id: str, project_id: str | None) -> ConversationRecord | None:
        """Set the Project relationship only, preserving folder and timestamps."""
        raise NotImplementedError

    def relocate(
        self, conversation_id: str, *, folder_id: str | None, project_id: str | None
    ) -> ConversationRecord | None:
        """Atomically replace both organizational destinations."""
        raise NotImplementedError

    @abstractmethod
    def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        """Rename a conversation, refreshing its ``updated_at``.

        Returns:
            The updated snapshot, or ``None`` if the conversation is unknown.
        """
        raise NotImplementedError

    def update_auto_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        """Set an automatic title only while the conversation has no user title.

        Adapters should perform the user-title check and write atomically so an
        automatic title cannot race with a manual rename.
        """
        return None


# ============================================================
# END: Conversation Repository
# ============================================================
