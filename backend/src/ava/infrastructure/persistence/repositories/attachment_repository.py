"""SQLite-backed attachment metadata repository adapter (Step 4.14.C).

Implements the AVA ``AttachmentRepository`` port over the shared
``SqliteDatabase``. Behavioral parity with the in-memory
``InMemoryAttachmentRepository`` (Step 4.14.A):

* ``create`` persists the supplied immutable record exactly: no minted
  ``attachment_id``/``storage_key``, no altered timestamps, enums and owner
  nullability preserved;
* duplicate ``attachment_id`` raises ``ValueError("Attachment already exists: ...")``
  and duplicate ``storage_key`` raises the distinct
  ``ValueError("Attachment storage key already in use: ...")`` — both
  pre-validated like the in-memory store, with the database ``UNIQUE``
  constraints as the backstop;
* the owner pair is enforced both-``None``-or-both-set and ``size_bytes`` is
  non-negative (zero valid), matching the in-memory validation boundary;
* ``list_for_owner`` returns exact owner matches (never unassociated
  attachments) in deterministic insertion order via the surrogate rowid
  ``ORDER BY id ASC`` — the surrogate id is never exposed;
* ``update_state`` advances exactly the two lifecycle-controlled fields
  (``size_bytes``, ``status``) by ``attachment_id`` with the same
  non-negative-size validation, and yields ``None`` for an unknown id;
* unknown ``get`` yields ``None``.
"""

import sqlite3

from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import (
    row_to_attachment_record,
    to_utc_iso,
)
from ava.repositories.attachment_repository import (
    AttachmentRecord,
    AttachmentRepository,
)

_ATTACHMENT_COLUMNS = (
    "attachment_id, file_name, media_type, size_bytes, storage_key, "
    "owner_type, owner_id, status, created_at"
)

# ============================================================
# BEGIN: Relational Attachment Repository
# ============================================================


class RelationalAttachmentRepository(AttachmentRepository):
    """SQLite-backed implementation of the attachment metadata repository port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, record: AttachmentRecord) -> AttachmentRecord:
        """Persist a new attachment metadata record exactly as supplied.

        Args:
            record: The AVA-owned immutable metadata snapshot to store.

        Returns:
            The record as stored, unchanged.

        Raises:
            ValueError: If an attachment with this ``attachment_id`` or
                ``storage_key`` already exists, if the owner pair is not
                both-set/both-``None``, or if ``size_bytes`` is negative.
        """
        if (record.owner_type is None) != (record.owner_id is None):
            raise ValueError(
                "owner_type and owner_id must be both set or both None, "
                f"got owner_type={record.owner_type!r} owner_id={record.owner_id!r}"
            )
        if record.size_bytes < 0:
            raise ValueError(f"size_bytes must be non-negative: {record.size_bytes}")
        try:
            with self._database.transaction() as connection:
                existing = connection.execute(
                    "SELECT attachment_id FROM attachments WHERE attachment_id = ?",
                    (record.attachment_id,),
                ).fetchone()
                if existing is not None:
                    raise ValueError(f"Attachment already exists: {record.attachment_id}")
                existing_key = connection.execute(
                    "SELECT storage_key FROM attachments WHERE storage_key = ?",
                    (record.storage_key,),
                ).fetchone()
                if existing_key is not None:
                    raise ValueError(
                        f"Attachment storage key already in use: {record.storage_key}"
                    )
                connection.execute(
                    "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                    "storage_key, owner_type, owner_id, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.attachment_id,
                        record.file_name,
                        record.media_type,
                        record.size_bytes,
                        record.storage_key,
                        record.owner_type.value if record.owner_type is not None else None,
                        record.owner_id,
                        record.status.value,
                        to_utc_iso(record.created_at),
                    ),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Attachment", key=record.attachment_id) from exc
        return record

    def get(self, attachment_id: str) -> AttachmentRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments WHERE attachment_id = ?",
                (attachment_id,),
            ).fetchone()
        return row_to_attachment_record(row) if row is not None else None

    def list_for_owner(
        self,
        owner_type: AttachmentOwnerType,
        owner_id: str,
    ) -> list[AttachmentRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments "
                "WHERE owner_type = ? AND owner_id = ? ORDER BY id ASC",
                (owner_type.value, owner_id),
            ).fetchall()
        return [row_to_attachment_record(row) for row in rows]

    def update_state(
        self,
        attachment_id: str,
        *,
        size_bytes: int,
        status: AttachmentStatus,
    ) -> AttachmentRecord | None:
        """Advance the lifecycle-controlled ``size_bytes``/``status`` pair by id.

        SQL mutates exactly the two lifecycle-controlled fields; an unknown id
        is a successful no-op that yields ``None``. The database ``CHECK``
        constraints (``size_bytes >= 0``, ``status IN (...)``) stay the
        backstop, with the same pre-validation as ``create``.

        Args:
            attachment_id: The AVA-owned attachment identifier.
            size_bytes: The authoritative stored byte count (``>= 0``).
            status: The lifecycle status to record.

        Returns:
            The refreshed metadata snapshot, or ``None`` if the attachment is
            unknown.

        Raises:
            ValueError: If ``size_bytes`` is negative.
        """
        if size_bytes < 0:
            raise ValueError(f"size_bytes must be non-negative: {size_bytes}")
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    "UPDATE attachments SET size_bytes = ?, status = ? WHERE attachment_id = ?",
                    (size_bytes, status.value, attachment_id),
                )
                if cursor.rowcount == 0:
                    return None
                row = connection.execute(
                    f"SELECT {_ATTACHMENT_COLUMNS} FROM attachments WHERE attachment_id = ?",
                    (attachment_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Attachment", key=attachment_id) from exc
        return row_to_attachment_record(row) if row is not None else None


# ============================================================
# END: Relational Attachment Repository
# ============================================================