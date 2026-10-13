"""AVA-owned document revision repository port (Step 4.13).

Expresses the immutable document-revision semantics AVA needs so durable
implementations (the in-memory store and the SQLite adapter) can satisfy the
same contract without changing document behavior.

Core semantics:

* ``Document`` is a stable mutable current state; ``DocumentRevision`` is an
  immutable full snapshot of that document at a point in time.
* A revision stores ``revision_id`` (backend-owned opaque identity),
  ``document_id``, ``revision_number`` (monotonically increasing per document),
  the snapshot ``title``/``content``/``content_format``, and an aware-UTC
  ``created_at`` snapshot timestamp.
* Revisions are append-only: the port exposes no update/delete/replace/rename
  operations. Future restore works by reading an immutable revision and
  creating a new current-state write plus a new revision, never by mutating
  history.

Ownership split (from the 4.13 audit): the service owns ``revision_id``
generation and the snapshot timestamp; the repository owns ``revision_number``
assignment, performed atomically by implementations (ordering collisions are
implementation work for later slices and are never caller-supplied).

The port is deliberately framework-neutral: no SQL, ORM entities, sessions,
transactions, queries, rows, or database drivers. Inputs and outputs use the
AVA-owned ``DocumentRevisionRecord`` snapshot and primitive values only.
"""

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from ava.contracts.documents import ContentFormat

# ============================================================
# BEGIN: Document Revision Record
# ============================================================


@dataclass(frozen=True)
class DocumentRevisionRecord:
    """AVA-owned immutable snapshot of a document at a point in time.

    ``content`` is the canonical serialized-HTML, ``content_format`` is the
    AVA-owned format vocabulary (only ``html`` exists today), and
    ``revision_number`` is a per-document monotonically increasing integer.
    ``created_at`` is a timezone-aware UTC snapshot timestamp. The record holds
    no editor/runtime objects and no persistence- or wire-only fields
    (no surrogate integer primary key, no ``contract_version``).
    """

    revision_id: str
    document_id: str
    revision_number: int
    title: str
    content: str
    content_format: ContentFormat
    created_at: datetime


# ============================================================
# END: Document Revision Record
# ============================================================


# ============================================================
# BEGIN: Document Revision Repository
# ============================================================


class DocumentRevisionRepository(ABC):
    """Port that document revision repositories must satisfy.

    Revisions are immutable, append-only snapshots. Responsibilities:

    * ``append`` — append one immutable revision snapshot, assigning its
      ``revision_number`` atomically; the repository never mints
      ``revision_id``.
    * ``list_for_document`` — return a document's revisions in deterministic
      ``revision_number`` ascending order.
    * ``get`` — return an exact document/revision lookup, or ``None``.
    * ``get_latest`` — return the document's most recent revision, or ``None``
      when no revisions exist.

    Deliberately not part of this port: current-document read/write behavior
    (stays on ``DocumentRepository``), revision identity generation, content
    validation/sanitization, restoration/revert semantics, sessions,
    transactions, query language, and observability helpers.
    """

    @abstractmethod
    def append(
        self,
        document_id: str,
        *,
        revision_id: str,
        title: str,
        content: str,
        content_format: ContentFormat,
        created_at: datetime,
    ) -> DocumentRevisionRecord:
        """Append one immutable revision snapshot for a document.

        Args:
            document_id: The AVA-owned document identifier.
            revision_id: The AVA-generated, caller-supplied revision
                identifier (the repository never mints one).
            title: The snapshot's title.
            content: The snapshot's canonical serialized-HTML content.
            content_format: The snapshot's AVA-owned content format.
            created_at: The authoritative aware-UTC snapshot timestamp.

        Returns:
            The appended immutable revision record.

        Raises:
            ValueError: If a revision with this ``revision_id`` already exists.

        The implementation assigns ``revision_number`` atomically; callers
        never supply it. Document existence is the caller's concern (see
        ``DocumentRepository``).
        """
        raise NotImplementedError

    @abstractmethod
    def list_for_document(self, document_id: str) -> Collection[DocumentRevisionRecord]:
        """Return a document's revisions in revision-number ascending order.

        Args:
            document_id: The AVA-owned document identifier.

        Returns:
            An ordered immutable snapshot of every revision. An unknown
            document yields an empty collection; document existence is the
            caller's concern.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, document_id: str, revision_id: str) -> DocumentRevisionRecord | None:
        """Return the exact document/revision lookup, or ``None`` when missing.

        Args:
            document_id: The AVA-owned document identifier.
            revision_id: The revision identifier to locate.

        Returns:
            The exact immutable revision, or ``None`` if either the document
            or the revision is unknown.
        """
        raise NotImplementedError

    @abstractmethod
    def get_latest(self, document_id: str) -> DocumentRevisionRecord | None:
        """Return the document's most recent revision, or ``None`` if none.

        Args:
            document_id: The AVA-owned document identifier.

        Returns:
            The highest-numbered immutable revision for the document, or
            ``None`` when the document has no revisions.
        """
        raise NotImplementedError


# ============================================================
# END: Document Revision Repository
# ============================================================
