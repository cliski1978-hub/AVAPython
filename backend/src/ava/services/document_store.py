"""In-memory AVA document store.

Holds the smallest generic document-state representation needed by the
current composition. This is Step 4.5 in-memory state only: no database,
cache, or queue. Revision/history semantics are deliberately absent
(Step 4.13 is reserved for document revision support).
"""

from dataclasses import replace
from datetime import UTC, datetime

from ava.contracts.documents import ContentFormat
from ava.repositories.document_repository import (
    DocumentRecord,
    DocumentRepository,
)

# ============================================================
# BEGIN: Document Store
# ============================================================


class DocumentStore(DocumentRepository):
    """In-memory, AVA-owned store of document records keyed by id.

    This is the in-memory ``DocumentRepository`` implementation used by the
    current composition. Step 4.5 state only: no database, cache, or queue.
    """

    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}

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
            The newly created record.

        Raises:
            ValueError: If a document with this identifier exists.
        """
        if document_id in self._documents:
            raise ValueError(f"Document already exists: {document_id}")
        now = datetime.now(UTC)
        record = DocumentRecord(
            document_id=document_id,
            title=title,
            content=content,
            content_format=content_format,
            created_at=now,
            updated_at=now,
        )
        self._documents[document_id] = record
        return record

    def get(self, document_id: str) -> DocumentRecord | None:
        """Return the document record for ``document_id``, or ``None``."""
        return self._documents.get(document_id)

    def list(self) -> list[DocumentRecord]:
        """Return all document records in insertion order."""
        return list(self._documents.values())

    def update_title(self, document_id: str, title: str) -> DocumentRecord | None:
        """Rename a document, refreshing its ``updated_at``.

        Returns:
            The updated record, or ``None`` if the document is unknown.
        """
        record = self._documents.get(document_id)
        if record is None:
            return None
        updated = replace(record, title=title, updated_at=datetime.now(UTC))
        self._documents[document_id] = updated
        return updated

    def update_content(
        self,
        document_id: str,
        *,
        content: str,
        content_format: ContentFormat,
    ) -> DocumentRecord | None:
        """Replace a document's content, refreshing its ``updated_at``.

        Returns:
            The updated record, or ``None`` if the document is unknown.
        """
        record = self._documents.get(document_id)
        if record is None:
            return None
        updated = replace(
            record,
            content=content,
            content_format=content_format,
            updated_at=datetime.now(UTC),
        )
        self._documents[document_id] = updated
        return updated

    def clear(self) -> None:
        """Remove all document records (test/observability helper)."""
        self._documents.clear()

    def snapshot(self) -> dict[str, DocumentRecord]:
        """Return an identity-preserving snapshot of every document record.

        Records are immutable snapshots, so the shallow copy fully captures
        the state. Used by the in-memory document write coordinator (Step
        4.13.B) for atomic rollback of current-state writes.
        """
        return dict(self._documents)

    def restore(self, snapshot: dict[str, DocumentRecord]) -> None:
        """Replace all document records with a prior snapshot (atomicity support).

        Test/observability helper in the same spirit as ``clear()``; used by
        the in-memory document write coordinator to roll back a current-state
        write whose companion revision append failed.
        """
        self._documents = dict(snapshot)


# ============================================================
# END: Document Store
# ============================================================
