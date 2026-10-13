"""AVA-owned document repository port.

Expresses the document-domain semantics that ``DocumentService`` needs, so
durable implementations (the in-memory store and the SQLite adapter) can
satisfy the same contract without changing document behavior.

The port is deliberately framework-neutral: no SQL, ORM entities, sessions,
transactions, queries, rows, or database drivers. Inputs and outputs use the
AVA-owned ``DocumentRecord`` snapshot and primitive values only. Document
identifiers are caller-supplied; a repository never mints ids. Revision and
history semantics are deliberately absent: Step 4.13 is reserved for document
revision support.
"""

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from ava.contracts.documents import ContentFormat

# ============================================================
# BEGIN: Document Record
# ============================================================


@dataclass(frozen=True)
class DocumentRecord:
    """AVA-owned snapshot of a document's state.

    ``content`` is the canonical serialized-HTML string and ``content_format``
    is the AVA-owned format vocabulary (only ``html`` exists today). The
    record holds no editor/runtime objects: Tiptap, ProseMirror, and
    framework node classes never cross this boundary.

    ``created_at`` and ``updated_at`` are timezone-aware UTC timestamps
    (``datetime.now(UTC)`` semantics); durable adapters must preserve
    aware-UTC round-tripping. No revision/version field exists yet: document
    revision support is reserved for Step 4.13.
    """

    document_id: str
    title: str
    content: str
    content_format: ContentFormat
    created_at: datetime
    updated_at: datetime


# ============================================================
# END: Document Record
# ============================================================


# ============================================================
# BEGIN: Document Repository
# ============================================================


class DocumentRepository(ABC):
    """Port that document repositories must satisfy.

    Responsibilities:

    * ``create`` — open a new document; a duplicate id is an error.
    * ``get`` — read the current document snapshot, or ``None``.
    * ``list`` — enumerate documents in stable insertion order.
    * ``update_title`` — rename a document, refreshing ``updated_at``.
    * ``update_content`` — replace a document's content, refreshing
      ``updated_at``.

    Deliberately not part of this port: document identity generation, content
    validation/sanitization, revision/history semantics, sessions,
    transactions, query language, and observability helpers (``clear``).
    """

    @abstractmethod
    def create(
        self,
        document_id: str,
        *,
        title: str,
        content: str,
        content_format: ContentFormat,
    ) -> DocumentRecord:
        """Create a new document record.

        Args:
            document_id: The AVA-generated document identifier.
            title: The document's initial title.
            content: The canonical serialized-HTML content.
            content_format: The AVA-owned content format.

        Returns:
            The newly created snapshot.

        Raises:
            ValueError: If a document with this identifier exists.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, document_id: str) -> DocumentRecord | None:
        """Return the document's current snapshot, or ``None`` if unknown."""
        raise NotImplementedError

    @abstractmethod
    def list(self) -> Collection[DocumentRecord]:
        """Return all documents in stable insertion order.

        Returns:
            An ordered immutable snapshot of every document.
        """
        raise NotImplementedError

    @abstractmethod
    def update_title(self, document_id: str, title: str) -> DocumentRecord | None:
        """Rename a document, refreshing its ``updated_at``.

        Returns:
            The updated snapshot, or ``None`` if the document is unknown.
        """
        raise NotImplementedError

    @abstractmethod
    def update_content(
        self,
        document_id: str,
        *,
        content: str,
        content_format: ContentFormat,
    ) -> DocumentRecord | None:
        """Replace a document's content, refreshing its ``updated_at``.

        Returns:
            The updated snapshot, or ``None`` if the document is unknown.
        """
        raise NotImplementedError


# ============================================================
# END: Document Repository
# ============================================================
