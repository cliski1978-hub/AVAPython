"""In-memory AVA document revision store (Step 4.13.B).

Stores immutable ``DocumentRevisionRecord`` snapshots per document in
append order with globally unique revision identities. This is Step 4.13.B
in-memory state only: no database, cache, or queue.

Revision numbering starts at 1 per document and increments monotonically;
history is immutable and retrievable in deterministic ascending
``revision_number`` order. Revision identifiers are opaque backend identities
and are enforced globally unique across all documents.
"""

from datetime import datetime

from ava.contracts.documents import ContentFormat
from ava.repositories.document_revision_repository import (
    DocumentRevisionRecord,
    DocumentRevisionRepository,
)

# ============================================================
# BEGIN: Document Revision Store
# ============================================================


class InMemoryDocumentRevisionStore(DocumentRevisionRepository):
    """In-memory, AVA-owned store of immutable document revisions keyed by document id.

    Revisions are grouped per ``document_id`` in append order, which equals
    ``revision_number`` ascending order. ``revision_id`` values are enforced
    globally unique; ``revision_number`` is always assigned by the store, never
    supplied by callers.
    """

    def __init__(self) -> None:
        self._revisions: dict[str, list[DocumentRevisionRecord]] = {}
        self._revision_ids: set[str] = set()

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
        """Append one immutable revision snapshot, assigning the next revision number.

        Args:
            document_id: The AVA-owned document identifier.
            revision_id: The AVA-generated, caller-supplied revision identifier.
            title: The snapshot's title.
            content: The snapshot's canonical serialized-HTML content.
            content_format: The snapshot's AVA-owned content format.
            created_at: The authoritative aware-UTC snapshot timestamp.

        Returns:
            The appended immutable revision record (revision number 1, 2, 3, …).

        Raises:
            ValueError: If ``revision_id`` is already in use by any document.
        """
        if revision_id in self._revision_ids:
            raise ValueError(f"Revision already exists: {revision_id}")
        record = DocumentRevisionRecord(
            revision_id=revision_id,
            document_id=document_id,
            revision_number=len(self._revisions.setdefault(document_id, [])) + 1,
            title=title,
            content=content,
            content_format=content_format,
            created_at=created_at,
        )
        self._revision_ids.add(revision_id)
        self._revisions[document_id].append(record)
        return record

    def list_for_document(self, document_id: str) -> list[DocumentRevisionRecord]:
        """Return the document's revisions in revision-number ascending order.

        An unknown document yields an empty list; document existence is the
        caller's concern (see the document store / coordinator).
        """
        return sorted(
            self._revisions.get(document_id, []),
            key=lambda record: record.revision_number,
        )

    def get(self, document_id: str, revision_id: str) -> DocumentRevisionRecord | None:
        """Return the exact document/revision lookup, or ``None`` when missing.

        A revision is only ever resolvable through its own document: a
        ``revision_id`` belonging to another document never resolves here.
        """
        for record in self._revisions.get(document_id, []):
            if record.revision_id == revision_id:
                return record
        return None

    def get_latest(self, document_id: str) -> DocumentRevisionRecord | None:
        """Return the document's most recent (highest-numbered) revision, if any."""
        revisions = self._revisions.get(document_id)
        return revisions[-1] if revisions else None

    def clear(self) -> None:
        """Remove all revisions and forget every revision id (test/observability helper)."""
        self._revisions.clear()
        self._revision_ids.clear()

    def snapshot(self) -> dict[str, list[DocumentRevisionRecord]]:
        """Return an identity-preserving snapshot of every revision group.

        Records are immutable, so shallow list copies fully capture the state.
        Used by the in-memory write coordinator for atomic rollback.
        """
        return {document_id: list(revisions) for document_id, revisions in self._revisions.items()}

    def restore(self, snapshot: dict[str, list[DocumentRevisionRecord]]) -> None:
        """Replace all revisions with a prior snapshot (atomicity support).

        Rebuilds both the per-document ordering and the global revision id set
        from the snapshot's records. Test/observability helper in the same
        spirit as ``clear()``; used by the in-memory write coordinator.
        """
        self._revisions = {document_id: list(revisions) for document_id, revisions in snapshot.items()}
        self._revision_ids = {
            record.revision_id for revisions in self._revisions.values() for record in revisions
        }


# ============================================================
# END: Document Revision Store
# ============================================================