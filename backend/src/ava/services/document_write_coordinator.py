"""In-memory AVA document write coordinator (Step 4.13.B).

Ensures the document current state and its immutable revision history advance
together atomically in the in-memory composition: every create persists a
document *and* its first revision; every save advances the current state into
the provided merged snapshot *and* appends exactly one next revision. If any
part fails, both stores roll back to their pre-write snapshots.

This is the in-memory counterpart of the transactional write path the
relational coordinator provides over one ``BEGIN IMMEDIATE`` transaction.
Step 4.13.D wires the coordinator into ``DocumentService`` through the
``DocumentWriteCoordinator`` seam defined here. Framework-neutral, no SQL, no
threads, no locks — in-memory state only.
"""

from datetime import datetime
from typing import Protocol

from ava.repositories.document_repository import DocumentRecord
from ava.repositories.document_revision_repository import (
    DocumentRevisionRecord,
)
from ava.services.document_revision_store import InMemoryDocumentRevisionStore
from ava.services.document_store import DocumentStore

# ============================================================
# BEGIN: Document Write Coordinator Port
# ============================================================


class DocumentWriteCoordinator(Protocol):
    """Structural type for the document write coordinator seam (Step 4.13).

    Both the in-memory coordinator (``ava.services``) and the relational
    coordinator (``ava.infrastructure.persistence.repositories``) advance a
    document's current state and its immutable revision history as one unit;
    neither mints document/revision identities or timestamps. ``DocumentService``
    programs against this protocol so it stays persistence-mode-neutral, and
    composition types its ``ApplicationPersistence.document_write_coordinator``
    field with it. The relational implementation must stay confined to the
    persistence package and structurally conforms without importing this port.
    """

    def create(
        self,
        document: DocumentRecord,
        *,
        revision_id: str,
        revision_created_at: datetime,
    ) -> tuple[DocumentRecord, DocumentRevisionRecord]: ...

    def update(
        self,
        document: DocumentRecord,
        *,
        revision_id: str,
        revision_created_at: datetime,
    ) -> tuple[DocumentRecord, DocumentRevisionRecord]: ...


# ============================================================
# END: Document Write Coordinator Port
# ============================================================

# ============================================================
# BEGIN: Document Write Coordinator
# ============================================================


class InMemoryDocumentWriteCoordinator:
    """Atomically advance document current state and revision history together.

    Holds the in-memory ``DocumentStore`` (current state; the incoming
    ``DocumentRecord`` drives every write) and the in-memory
    ``InMemoryDocumentRevisionStore`` (immutable history). Both stores are
    passed in, never constructed implicitly, so the composition stays explicit.

    Invariants:

    * ``create`` results in exactly one revision (number 1); ``update``
      results in exactly one next revision, never zero and never more than one.
    * On any failure the current state and every revision return to their
      pre-write snapshots; a failed write leaves no trace.
    * History is immutable: an append failing on a duplicate ``revision_id``
      raises ``ValueError`` after rolling back the current-state write.
    """

    def __init__(
        self,
        *,
        documents: DocumentStore,
        revisions: InMemoryDocumentRevisionStore,
    ) -> None:
        self._documents = documents
        self._revisions = revisions

    def create(
        self,
        document: DocumentRecord,
        *,
        revision_id: str,
        revision_created_at: datetime,
    ) -> tuple[DocumentRecord, DocumentRevisionRecord]:
        """Persist a new document and append its first revision as one unit.

        Args:
            document: The Ava-owned record of the document being created. Its
                identity, title, content, and content format drive the write;
                the record's internal timestamps are ignored (stores stamp
                their own).
            revision_id: The Ava-generated, coordinator-supplied revision
                identifier for revision 1.
            revision_created_at: The authoritative aware-UTC snapshot
                timestamp for revision 1.

        Returns:
            The persisted current record and the appended revision 1.

        Raises:
            ValueError: If the document already exists or ``revision_id`` is
                already in use.
        """
        documents_snapshot = self._documents.snapshot()
        revisions_snapshot = self._revisions.snapshot()
        try:
            current = self._documents.create(
                document.document_id,
                title=document.title,
                content=document.content,
                content_format=document.content_format,
            )
            revision = self._revisions.append(
                document.document_id,
                revision_id=revision_id,
                title=document.title,
                content=document.content,
                content_format=document.content_format,
                created_at=revision_created_at,
            )
        except BaseException:
            self._documents.restore(documents_snapshot)
            self._revisions.restore(revisions_snapshot)
            raise
        return current, revision

    def update(
        self,
        document: DocumentRecord,
        *,
        revision_id: str,
        revision_created_at: datetime,
    ) -> tuple[DocumentRecord, DocumentRevisionRecord]:
        """Advance the current state to ``document`` and append one next revision.

        The document must already exist (callers read-then-write through the
        coordinator or service). ``title`` and ``content`` are both applied to
        the current state so a combined title+content save produces exactly one
        revision.

        Args:
            document: The Ava-owned merged snapshot the current state must
                reach. Its identity, title, content, and content format drive
                the write; internal timestamps are ignored (stores stamp their
                own).
            revision_id: The Ava-generated, coordinator-supplied revision
                identifier for the appended revision.
            revision_created_at: The authoritative aware-UTC snapshot
                timestamp for the appended revision.

        Returns:
            The persisted current record and the appended next revision.

        Raises:
            ValueError: If the document is unknown or ``revision_id`` is
                already in use.
        """
        documents_snapshot = self._documents.snapshot()
        revisions_snapshot = self._revisions.snapshot()
        try:
            if self._documents.get(document.document_id) is None:
                raise ValueError(f"Document not found: {document.document_id}")
            updated = self._documents.update_title(document.document_id, document.title)
            assert updated is not None
            final = self._documents.update_content(
                document.document_id,
                content=document.content,
                content_format=document.content_format,
            )
            assert final is not None
            revision = self._revisions.append(
                document.document_id,
                revision_id=revision_id,
                title=document.title,
                content=document.content,
                content_format=document.content_format,
                created_at=revision_created_at,
            )
        except BaseException:
            self._documents.restore(documents_snapshot)
            self._revisions.restore(revisions_snapshot)
            raise
        return final, revision


# ============================================================
# END: Document Write Coordinator
# ============================================================