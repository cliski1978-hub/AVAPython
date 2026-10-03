"""SQLite-backed document write coordinator (Step 4.13.C).

Ensures the document current state and its immutable revision history advance
together atomically over one shared SQLite database: every create persists a
document *and* its first revision; every update advances the current state
into the provided merged snapshot *and* appends exactly one next revision. The
entire write runs inside a single ``BEGIN IMMEDIATE`` transaction, so a failed
revision append rolls the current-state write back with it — no snapshot
bookkeeping is needed (the database transaction is the atomicity boundary).

This is the relational counterpart of
``ava.services.document_write_coordinator.InMemoryDocumentWriteCoordinator``.
Step 4.13.D wires the coordinator into ``DocumentService`` through the
``DocumentWriteCoordinator`` seam, and application composition selects the
relational coordinator whenever ``AVA_PERSISTENCE=relational``.

Design rules honored here:

* the coordinator owns the transaction; the document write and the revision
  append run against the same live connection via the repository adapters'
  connection-accepting seams (``_create_on``/``_replace_on``/``_append_on``).
  The public repository methods (which open their own transactions) are never
  called inside this transaction.
* the coordinator mints no identities or timestamps: the document's identity,
  title, content, format, and timestamps come from the fully prepared
  ``DocumentRecord``; the ``revision_id`` and authoritative snapshot timestamp
  come from the caller. Only ``revision_number`` is repository-owned.
* driver errors are translated per statement against the affected entity
  (``Document`` for the current-state write, ``Revision`` for the append) by
  the shared error boundary, so duplicates surface as ``ValueError`` and the
  transaction rolls back whole.
"""

import sqlite3
from datetime import datetime

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.repositories.document_repository import (
    RelationalDocumentRepository,
)
from ava.infrastructure.persistence.repositories.document_revision_repository import (
    RelationalDocumentRevisionRepository,
)
from ava.repositories.document_repository import DocumentRecord
from ava.repositories.document_revision_repository import DocumentRevisionRecord

# ============================================================
# BEGIN: Relational Document Write Coordinator
# ============================================================


class RelationalDocumentWriteCoordinator:
    """Atomically advance document current state and revision history together.

    Holds the shared ``SqliteDatabase`` plus the ``RelationalDocumentRepository``
    (current state) and ``RelationalDocumentRevisionRepository`` (immutable
    history). All three are injected, never constructed implicitly, so the
    composition stays explicit and shares one database/connection.

    Invariants:

    * ``create`` results in exactly one revision (number 1); ``update``
      results in exactly one next revision, never zero and never more than one.
    * Each write is one ``BEGIN IMMEDIATE`` transaction: a failed revision
      append rolls back the current-state write, leaving no trace.
    * History is immutable: an append failing on a duplicate ``revision_id``
      raises ``ValueError`` and rolls back the whole write.
    """

    def __init__(
        self,
        *,
        database: SqliteDatabase,
        document_repository: RelationalDocumentRepository,
        revision_repository: RelationalDocumentRevisionRepository,
    ) -> None:
        self._database = database
        self._document_repository = document_repository
        self._revision_repository = revision_repository

    def create(
        self,
        document: DocumentRecord,
        *,
        revision_id: str,
        revision_created_at: datetime,
    ) -> tuple[DocumentRecord, DocumentRevisionRecord]:
        """Persist a new document and append its first revision as one unit.

        Args:
            document: The fully prepared current-state record. Its identity,
                title, content, content format, and timestamps drive the write
                (no minting happens here).
            revision_id: The AVA-generated, coordinator-passed revision
                identifier for revision 1.
            revision_created_at: The authoritative aware-UTC snapshot
                timestamp for revision 1.

        Returns:
            The persisted current record and the appended revision 1.

        Raises:
            ValueError: If the document already exists or ``revision_id`` is
                already in use (the whole write rolls back).
        """
        with self._database.transaction() as connection:
            try:
                current = self._document_repository._create_on(
                    connection,
                    document_id=document.document_id,
                    title=document.title,
                    content=document.content,
                    content_format=document.content_format,
                    created_at=document.created_at,
                    updated_at=document.updated_at,
                )
            except sqlite3.Error as exc:
                raise translate_database_error(exc, entity="Document", key=document.document_id) from exc
            try:
                revision = self._revision_repository._append_on(
                    connection,
                    document.document_id,
                    revision_id=revision_id,
                    title=document.title,
                    content=document.content,
                    content_format=document.content_format,
                    created_at=revision_created_at,
                )
            except sqlite3.Error as exc:
                raise translate_database_error(exc, entity="Revision", key=revision_id) from exc
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
        the current state in a single UPDATE so a combined title+content save
        produces exactly one revision.

        Args:
            document: The fully prepared merged snapshot the current state
                must reach. Its identity, title, content, content format, and
                ``updated_at`` drive the write (no minting happens here).
            revision_id: The AVA-generated, coordinator-passed revision
                identifier for the appended revision.
            revision_created_at: The authoritative aware-UTC snapshot
                timestamp for the appended revision.

        Returns:
            The persisted current record and the appended next revision.

        Raises:
            ValueError: If the document is unknown or ``revision_id`` is
                already in use (the whole write rolls back).
        """
        with self._database.transaction() as connection:
            try:
                current = self._document_repository._replace_on(
                    connection,
                    document_id=document.document_id,
                    title=document.title,
                    content=document.content,
                    content_format=document.content_format,
                    updated_at=document.updated_at,
                )
            except sqlite3.Error as exc:
                raise translate_database_error(exc, entity="Document", key=document.document_id) from exc
            if current is None:
                raise ValueError(f"Document not found: {document.document_id}")
            try:
                revision = self._revision_repository._append_on(
                    connection,
                    document.document_id,
                    revision_id=revision_id,
                    title=document.title,
                    content=document.content,
                    content_format=document.content_format,
                    created_at=revision_created_at,
                )
            except sqlite3.Error as exc:
                raise translate_database_error(exc, entity="Revision", key=revision_id) from exc
        return current, revision


# ============================================================
# END: Relational Document Write Coordinator
# ============================================================
