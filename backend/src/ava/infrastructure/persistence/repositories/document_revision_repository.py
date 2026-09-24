"""SQLite-backed document revision repository adapter (Step 4.13.C).

Implements the AVA ``DocumentRevisionRepository`` port over the shared
``SqliteDatabase``. Behavioral parity with the in-memory
``InMemoryDocumentRevisionStore``:

* revisions are immutable, append-only full snapshots (no update/delete);
* ``revision_number`` is assigned atomically inside a write transaction as
  ``MAX(revision_number) + 1`` per document — never caller-supplied, and the
  ``UNIQUE(document_id, revision_number)`` + ``UNIQUE(revision_id)`` database
  constraints back that ordering under concurrency;
* a duplicate ``revision_id`` raises ``ValueError`` (driver errors translated
  through the shared error boundary);
* ``list_for_document`` enumerates in ``revision_number`` ascending order and
  an unknown document yields ``[]``;
* ``get`` resolves only through the owning document and ``get_latest`` returns
  the highest-numbered revision.

The coordinator-facing ``_append_on`` seam accepts a live connection so the
document write coordinator can append the next revision inside the same
transaction as the current-state document write.
"""

import sqlite3
from datetime import datetime

from ava.contracts.documents import ContentFormat
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import row_to_document_revision_record, to_utc_iso
from ava.repositories.document_revision_repository import (
    DocumentRevisionRecord,
    DocumentRevisionRepository,
)

_REVISION_COLUMNS = "revision_id, document_id, revision_number, title, content, content_format, created_at"

# ============================================================
# BEGIN: Relational Document Revision Repository
# ============================================================


class RelationalDocumentRevisionRepository(DocumentRevisionRepository):
    """SQLite-backed implementation of the document revision repository port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

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
        try:
            with self._database.transaction() as connection:
                record = self._append_on(
                    connection,
                    document_id,
                    revision_id=revision_id,
                    title=title,
                    content=content,
                    content_format=content_format,
                    created_at=created_at,
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Revision", key=revision_id) from exc
        return record

    def list_for_document(self, document_id: str) -> list[DocumentRevisionRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_REVISION_COLUMNS} FROM document_revisions "
                "WHERE document_id = ? ORDER BY revision_number ASC",
                (document_id,),
            ).fetchall()
        return [row_to_document_revision_record(row) for row in rows]

    def get(self, document_id: str, revision_id: str) -> DocumentRevisionRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_REVISION_COLUMNS} FROM document_revisions "
                "WHERE document_id = ? AND revision_id = ?",
                (document_id, revision_id),
            ).fetchone()
        return row_to_document_revision_record(row) if row is not None else None

    def get_latest(self, document_id: str) -> DocumentRevisionRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_REVISION_COLUMNS} FROM document_revisions "
                "WHERE document_id = ? ORDER BY revision_number DESC LIMIT 1",
                (document_id,),
            ).fetchone()
        return row_to_document_revision_record(row) if row is not None else None

    # ------------------------------------------------------------------
    # Connection-accepting seam (Step 4.13.C)
    #
    # Used by ``RelationalDocumentWriteCoordinator`` so a revision append
    # runs inside the coordinator's single caller-owned transaction. It takes
    # a live connection, assigns the next ``revision_number`` from
    # ``MAX(revision_number) + 1`` and inserts — the caller owns commit.
    # Driver errors are left for the caller to translate as a revision error.
    # ------------------------------------------------------------------

    def _append_on(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        *,
        revision_id: str,
        title: str,
        content: str,
        content_format: ContentFormat,
        created_at: datetime,
    ) -> DocumentRevisionRecord:
        """Append an immutable revision snapshot on ``connection``."""
        row = connection.execute(
            "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM document_revisions WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        revision_number = int(row[0])
        connection.execute(
            "INSERT INTO document_revisions (revision_id, document_id, revision_number, title, content, "
            "content_format, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                revision_id,
                document_id,
                revision_number,
                title,
                content,
                content_format.value,
                to_utc_iso(created_at),
            ),
        )
        return DocumentRevisionRecord(
            revision_id=revision_id,
            document_id=document_id,
            revision_number=revision_number,
            title=title,
            content=content,
            content_format=content_format,
            created_at=created_at,
        )


# ============================================================
# END: Relational Document Revision Repository
# ============================================================