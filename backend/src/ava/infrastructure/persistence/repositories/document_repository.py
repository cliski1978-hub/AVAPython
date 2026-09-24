"""SQLite-backed document repository adapter (Step 4.6).

Implements the AVA ``DocumentRepository`` port over the shared
``SqliteDatabase``. Behavioral parity with the in-memory ``DocumentStore``:
duplicates raise ``ValueError``, unknown documents return ``None``,
``list()`` enumerates in stable insertion order, and updates refresh
``updated_at``.

Since Step 4.13.C the adapter also exposes private connection-accepting
seams (``_create_on``/``_replace_on``) so the document write coordinator can
run a document write and its revision append inside ONE shared transaction.
The public port surface is unchanged; ``document_id`` is never minted here.
"""

import sqlite3
from datetime import UTC, datetime

from ava.contracts.documents import ContentFormat
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import row_to_document_record, to_utc_iso
from ava.repositories.document_repository import DocumentRecord, DocumentRepository

_DOCUMENT_COLUMNS = "document_id, title, content, content_format, created_at, updated_at"

# ============================================================
# BEGIN: Relational Document Repository
# ============================================================


class RelationalDocumentRepository(DocumentRepository):
    """SQLite-backed implementation of the document repository port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(
        self,
        document_id: str,
        *,
        title: str,
        content: str,
        content_format: ContentFormat,
    ) -> DocumentRecord:
        now = datetime.now(UTC)
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO documents (document_id, title, content, content_format, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (document_id, title, content, content_format.value, to_utc_iso(now), to_utc_iso(now)),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Document", key=document_id) from exc
        return DocumentRecord(
            document_id=document_id,
            title=title,
            content=content,
            content_format=content_format,
            created_at=now,
            updated_at=now,
        )

    def get(self, document_id: str) -> DocumentRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return row_to_document_record(row) if row is not None else None

    def list(self) -> list[DocumentRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(f"SELECT {_DOCUMENT_COLUMNS} FROM documents ORDER BY id ASC").fetchall()
        return [row_to_document_record(row) for row in rows]

    def update_title(self, document_id: str, title: str) -> DocumentRecord | None:
        now = datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE documents SET title = ?, updated_at = ? WHERE document_id = ?",
                (title, to_utc_iso(now), document_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return row_to_document_record(row) if row is not None else None

    def update_content(
        self,
        document_id: str,
        *,
        content: str,
        content_format: ContentFormat,
    ) -> DocumentRecord | None:
        now = datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE documents SET content = ?, content_format = ?, updated_at = ? WHERE document_id = ?",
                (content, content_format.value, to_utc_iso(now), document_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return row_to_document_record(row) if row is not None else None

    # ------------------------------------------------------------------
    # Connection-accepting seams (Step 4.13.C)
    #
    # Used only by ``RelationalDocumentWriteCoordinator`` to fold a document
    # write and its revision append into a single caller-owned transaction.
    # They take a live connection (never opening or committing one) and
    # return records the way the public methods do; driver errors are left for
    # the coordinator to translate against the right entity.
    # ------------------------------------------------------------------

    def _create_on(
        self,
        connection: sqlite3.Connection,
        *,
        document_id: str,
        title: str,
        content: str,
        content_format: ContentFormat,
        created_at: datetime,
        updated_at: datetime,
    ) -> DocumentRecord:
        """Insert a document on ``connection`` without opening a transaction."""
        connection.execute(
            "INSERT INTO documents (document_id, title, content, content_format, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (document_id, title, content, content_format.value, to_utc_iso(created_at), to_utc_iso(updated_at)),
        )
        return DocumentRecord(
            document_id=document_id,
            title=title,
            content=content,
            content_format=content_format,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _replace_on(
        self,
        connection: sqlite3.Connection,
        *,
        document_id: str,
        title: str,
        content: str,
        content_format: ContentFormat,
        updated_at: datetime,
    ) -> DocumentRecord | None:
        """Replace title+content on ``connection``; return the stored snapshot or ``None``."""
        cursor = connection.execute(
            "UPDATE documents SET title = ?, content = ?, content_format = ?, updated_at = ? "
            "WHERE document_id = ?",
            (title, content, content_format.value, to_utc_iso(updated_at), document_id),
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return row_to_document_record(row) if row is not None else None


# ============================================================
# END: Relational Document Repository
# ============================================================