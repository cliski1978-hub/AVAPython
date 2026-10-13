"""AVA attachment application service (Step 4.14.E).

Coordinates the attachment domain against the AVA-owned metadata repository
and content-store ports. The service owns what a repository must not:
``attachment_id`` minting (the existing ``uuid4`` convention), timezone-aware
UTC timestamps, the opaque per-attachment ``storage_key``, and the
pending → put → verify → available lifecycle.

Upload is two-resource work (metadata + physical content) that cannot share a
transaction, so the service orders the writes deliberately (audit §25):

* mint identity/key/timestamp and insert a ``pending`` metadata record first
  (a metadata failure means no content is ever written);
* write the bytes through the content store and verify the content exists;
* only then advance the record to ``available`` with the content store's
  authoritative ``size_bytes``.

On any handled failure the record is marked ``failed`` so it never reports a
lie: a ``pending`` or ``failed`` attachment never exposes its content, and
``available`` is only ever reached after the content store confirmed the
bytes. A record that genuinely reaches ``available`` is the service's only
content-bearing state. Best-effort ``failed`` marking on the final transition
is spelled out in code so a broken repository cannot leave a misleading
``available`` OR silently swallow a real storage error.

The storage key is derived from the backend-owned ``attachment_id`` only —
never from the display filename (audit §7) — and is an opaque logical
reference interpreted solely by the content-store adapter.

The service programs against ports, never concrete stores. Composition
(``create_app``) injects the implementations. The service is framework-neutral:
no FastAPI, sessions, SQL/ORM, or storage paths.
"""

import contextlib
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO
from uuid import uuid4

from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.repositories.attachment_content_store import AttachmentContentStore
from ava.repositories.attachment_repository import (
    AttachmentRecord,
    AttachmentRepository,
)

#: Logical storage-key shape: one key per attachment, derived from the
#: backend-owned id. The display filename never participates.
ATTACHMENT_STORAGE_KEY_NOTATION = "attachments/{attachment_id}/content"


# ============================================================
# BEGIN: Attachment Domain Errors
# ============================================================


class AttachmentStorageError(Exception):
    """Physical content storage, verification, or finalization failed."""


class AttachmentStateError(Exception):
    """An attachment's lifecycle state forbids the requested operation."""


# ============================================================
# END: Attachment Domain Errors
# ============================================================


# ============================================================
# BEGIN: Attachment Content Reference
# ============================================================


@dataclass(frozen=True)
class AttachmentContentRef:
    """An available attachment's metadata plus a caller-owned binary stream.

    ``stream`` is caller-owned: the service opens it and never closes it. The
    metadata and its content are returned together so the caller can stream
    bytes against the exact record they were looked up with.
    """

    record: AttachmentRecord
    stream: BinaryIO


# ============================================================
# END: Attachment Content Reference
# ============================================================


# ============================================================
# BEGIN: Attachment Service
# ============================================================


class AttachmentService:
    """Coordinates attachment metadata and physical content.

    Args:
        attachment_repository: The injected attachment metadata repository
            port (``create``/``get``/``list_for_owner``/``update_state``).
        attachment_content_store: The injected physical content-store port
            (``put``/``open``/``exists``).

    Unknown-attachment lookups return ``None`` (the route normalizes to 404);
    lifecycle-forbidden reads raise ``AttachmentStateError``; storage and
    finalization faults raise ``AttachmentStorageError``.
    """

    def __init__(
        self,
        *,
        attachment_repository: AttachmentRepository,
        attachment_content_store: AttachmentContentStore,
    ) -> None:
        self._repository = attachment_repository
        self._content_store = attachment_content_store

    def create_attachment(
        self,
        *,
        file_name: str,
        media_type: str,
        source: BinaryIO,
        owner_type: AttachmentOwnerType | None = None,
        owner_id: str | None = None,
        retain_failed_record: bool = True,
    ) -> AttachmentRecord:
        """Create an attachment from a binary source stream.

        Runs the pending → put → verify → available lifecycle described in the
        module docstring. ``file_name`` is display metadata only — it never
        affects the physical ``storage_key``. ``source`` is caller-owned and
        is read from its current position to EOF without rewind.

        Returns:
            The finalized ``available`` metadata snapshot with the content
            store's authoritative ``size_bytes``.

        Raises:
            ValueError: If the owner pair is not both-set/both-``None``.
            AttachmentStorageError: If metadata creation, content storage,
                content verification, or final metadata transition fails. By
                default a failed record is retained; set
                ``retain_failed_record=False`` to clean up rejected uploads.
        """
        if (owner_type is None) != (owner_id is None):
            raise ValueError(
                "owner_type and owner_id must be both set or both None, "
                f"got owner_type={owner_type!r} owner_id={owner_id!r}"
            )
        attachment_id = str(uuid4())
        storage_key = ATTACHMENT_STORAGE_KEY_NOTATION.format(attachment_id=attachment_id)
        created_at = datetime.now(UTC)
        try:
            self._repository.create(
                AttachmentRecord(
                    attachment_id=attachment_id,
                    file_name=file_name,
                    media_type=media_type,
                    size_bytes=0,
                    storage_key=storage_key,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    status=AttachmentStatus.PENDING,
                    created_at=created_at,
                )
            )
        except ValueError as exc:
            raise AttachmentStorageError(f"Failed to record attachment metadata: {exc}") from exc

        try:
            info = self._content_store.put(storage_key, source)
        except Exception as exc:
            self._handle_upload_failure(attachment_id, storage_key, retain_failed_record)
            raise AttachmentStorageError(f"Failed to store attachment content: {exc}") from exc

        try:
            present = self._content_store.exists(storage_key)
        except Exception as exc:
            self._handle_upload_failure(attachment_id, storage_key, retain_failed_record)
            raise AttachmentStorageError(f"Failed to verify attachment content: {exc}") from exc
        if not present:
            self._handle_upload_failure(attachment_id, storage_key, retain_failed_record)
            raise AttachmentStorageError("Attachment content verification failed: content is not present after put")

        try:
            finalized = self._repository.update_state(
                attachment_id,
                size_bytes=info.size_bytes,
                status=AttachmentStatus.AVAILABLE,
            )
        except Exception as exc:
            if not retain_failed_record:
                self._discard_failed_upload(attachment_id, storage_key)
                raise AttachmentStorageError(
                    "Attachment content was stored but final metadata transition failed; the upload was removed."
                ) from exc
            try:
                self._repository.update_state(
                    attachment_id,
                    size_bytes=0,
                    status=AttachmentStatus.FAILED,
                )
            except Exception as failed_exc:
                raise AttachmentStorageError(
                    "Attachment content stored but final metadata transition failed; "
                    f"the failed state could not be recorded either ({failed_exc}). "
                    "The record may remain pending and referenced content may be orphaned."
                ) from exc
            raise AttachmentStorageError(
                "Attachment content stored but the final metadata transition failed; the record was marked failed."
            ) from exc
        if finalized is None:
            if not retain_failed_record:
                self._discard_failed_upload(attachment_id, storage_key)
            raise AttachmentStorageError("Attachment content stored but its metadata is missing during finalization.")
        return finalized

    def get_attachment(self, attachment_id: str) -> AttachmentRecord | None:
        """Return an attachment's metadata snapshot, or ``None`` if unknown.

        Metadata only: never touches the content store.
        """
        return self._repository.get(attachment_id)

    def list_attachments(
        self,
        owner_type: AttachmentOwnerType,
        owner_id: str,
    ) -> Collection[AttachmentRecord]:
        """Return an owner's attachments in stable insertion order."""
        return self._repository.list_for_owner(owner_type, owner_id)

    def open_attachment_content(self, attachment_id: str) -> AttachmentContentRef | None:
        """Open an available attachment's content, or ``None`` if unknown.

        Content is only ever exposed for ``available`` attachments — the sole
        state in which ``available ⇒ content exists`` holds (audit §12).
        ``pending`` and ``failed`` attachments raise ``AttachmentStateError``.
        An unknown id is resolved before the content store is touched, and the
        returned stream is caller-owned.

        Raises:
            AttachmentStateError: If the attachment is pending or failed.
            AttachmentStorageError: If content is missing despite the record
                being available (an internal verification inconsistency).
        """
        record = self._repository.get(attachment_id)
        if record is None:
            return None
        if record.status is not AttachmentStatus.AVAILABLE:
            raise AttachmentStateError(
                f"Cannot open content for attachment {attachment_id}: status is {record.status.value}"
            )
        try:
            stream = self._content_store.open(record.storage_key)
        except FileNotFoundError as exc:
            raise AttachmentStorageError(
                f"Attachment content is missing for {attachment_id} despite being available"
            ) from exc
        return AttachmentContentRef(record=record, stream=stream)

    def delete_attachment(self, attachment_id: str) -> AttachmentRecord | None:
        """Delete one attachment and its stored bytes, if it exists."""
        record = self._repository.get(attachment_id)
        if record is None:
            return None
        try:
            self._content_store.delete(record.storage_key)
            return self._repository.delete(attachment_id)
        except Exception as exc:
            raise AttachmentStorageError(f"Failed to delete attachment {attachment_id}") from exc

    def _handle_upload_failure(self, attachment_id: str, storage_key: str, retain_failed_record: bool) -> None:
        if retain_failed_record:
            self._mark_failed(attachment_id)
        else:
            self._discard_failed_upload(attachment_id, storage_key)

    def _discard_failed_upload(self, attachment_id: str, storage_key: str) -> None:
        """Remove rejected upload metadata and best-effort remove its bytes."""
        content_error: Exception | None = None
        try:
            self._content_store.delete(storage_key)
        except Exception as exc:
            content_error = exc
        try:
            self._repository.delete(attachment_id)
        except Exception as exc:
            raise AttachmentStorageError("Failed to remove attachment metadata after upload failure") from exc
        if content_error is not None:
            raise AttachmentStorageError("Failed to remove stored content after upload failure") from content_error

    def _mark_failed(self, attachment_id: str) -> None:
        """Best-effort ``failed`` side effect on a handled storage failure.

        The content store owns the primary failure; recording the failed state
        is best-effort so a broken repository cannot mask the real error. Bytes
        written before a later failure are never deleted here — orphan
        reconciliation is a future sweep (audit §25/§26).
        """
        with contextlib.suppress(Exception):
            self._repository.update_state(
                attachment_id,
                size_bytes=0,
                status=AttachmentStatus.FAILED,
            )


# ============================================================
# END: Attachment Service
# ============================================================
