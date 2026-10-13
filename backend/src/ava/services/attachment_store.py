"""In-memory AVA attachment metadata store (Step 4.14.A).

Stores immutable ``AttachmentRecord`` metadata snapshots keyed by id with a
separate unique-storage-key index. This is Step 4.14.A metadata-only state:
no database, cache, queue, and no physical file bytes (the content store
seam arrives in Step 4.14.B+).

``create`` is the validation boundary this slice guarantees: the owner pair
must be both-set or both-``None``, ``size_bytes`` must be non-negative, and
a duplicate ``attachment_id`` or duplicate ``storage_key`` is a
``ValueError``. Conversation attachment filenames are unique within their
Conversation after trimming and Unicode case-folding; other owner types retain
their existing filename behavior.
"""

from collections.abc import Collection
from threading import RLock

from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.repositories.attachment_repository import (
    AttachmentRecord,
    AttachmentRepository,
    DuplicateConversationAttachmentNameError,
    normalize_conversation_attachment_name,
)

# ============================================================
# BEGIN: In-Memory Attachment Repository
# ============================================================


class InMemoryAttachmentRepository(AttachmentRepository):
    """In-memory, AVA-owned store of attachment metadata records.

    Keyed by ``attachment_id`` with a ``dict`` of immutable records (insertion
    order = deterministic listing order) plus a set of unique ``storage_key``
    values. Metadata only: no content store, no file bytes, no paths.
    """

    def __init__(self) -> None:
        self._attachments: dict[str, AttachmentRecord] = {}
        self._storage_keys: set[str] = set()
        self._lock = RLock()

    def create(self, record: AttachmentRecord) -> AttachmentRecord:
        """Persist a new attachment metadata record.

        Args:
            record: The AVA-owned immutable metadata snapshot to store.

        Returns:
            The record as stored, unchanged.

        Raises:
            ValueError: If an attachment with this ``attachment_id`` or
                ``storage_key`` already exists, if the owner pair is not
                both-set/both-``None``, or if ``size_bytes`` is negative.
        """
        with self._lock:
            if record.attachment_id in self._attachments:
                raise ValueError(f"Attachment already exists: {record.attachment_id}")
            if record.storage_key in self._storage_keys:
                raise ValueError(f"Attachment storage key already in use: {record.storage_key}")
            if (record.owner_type is None) != (record.owner_id is None):
                raise ValueError(
                    "owner_type and owner_id must be both set or both None, "
                    f"got owner_type={record.owner_type!r} owner_id={record.owner_id!r}"
                )
            if record.size_bytes < 0:
                raise ValueError(f"size_bytes must be non-negative: {record.size_bytes}")
            if record.owner_type is AttachmentOwnerType.CONVERSATION:
                normalized_name = normalize_conversation_attachment_name(record.file_name)
                existing = next(
                    (
                        item
                        for item in self._attachments.values()
                        if item.owner_type is AttachmentOwnerType.CONVERSATION
                        and item.owner_id == record.owner_id
                        and normalize_conversation_attachment_name(item.file_name) == normalized_name
                    ),
                    None,
                )
                if existing is not None:
                    raise DuplicateConversationAttachmentNameError(existing.file_name)
            self._attachments[record.attachment_id] = record
            self._storage_keys.add(record.storage_key)
            return record

    def get(self, attachment_id: str) -> AttachmentRecord | None:
        """Return the attachment's metadata snapshot, or ``None`` if unknown."""
        return self._attachments.get(attachment_id)

    def list_for_owner(
        self,
        owner_type: AttachmentOwnerType,
        owner_id: str,
    ) -> Collection[AttachmentRecord]:
        """Return the owner's attachments in stable insertion order.

        Unassociated attachments and attachments owned by another type or id
        are never returned. The returned collection is caller-isolated: the
        immutable records are shared, but the list itself is fresh.
        """
        return [
            record
            for record in self._attachments.values()
            if record.owner_type == owner_type and record.owner_id == owner_id
        ]

    def update_state(
        self,
        attachment_id: str,
        *,
        size_bytes: int,
        status: AttachmentStatus,
    ) -> AttachmentRecord | None:
        """Advance the lifecycle-controlled ``size_bytes``/``status`` pair by id.

        The only mutation this store supports beyond ``create``: exactly the
        two fields the ``AttachmentService`` owns are replaced with the
        supplied values; everything else (identity, storage key, owner,
        filename, media type, timestamp) stays immutable. An unknown id yields
        ``None`` and a negative size is a ``ValueError``.

        Args:
            attachment_id: The AVA-owned attachment identifier.
            size_bytes: The authoritative stored byte count (``>= 0``).
            status: The lifecycle status to record.

        Returns:
            The refreshed metadata snapshot, or ``None`` if unknown.
        """
        current = self._attachments.get(attachment_id)
        if current is None:
            return None
        if size_bytes < 0:
            raise ValueError(f"size_bytes must be non-negative: {size_bytes}")
        refreshed = AttachmentRecord(
            attachment_id=current.attachment_id,
            file_name=current.file_name,
            media_type=current.media_type,
            size_bytes=size_bytes,
            storage_key=current.storage_key,
            owner_type=current.owner_type,
            owner_id=current.owner_id,
            status=status,
            created_at=current.created_at,
        )
        self._attachments[attachment_id] = refreshed
        return refreshed

    def delete(self, attachment_id: str) -> AttachmentRecord | None:
        with self._lock:
            record = self._attachments.pop(attachment_id, None)
            if record is not None:
                self._storage_keys.discard(record.storage_key)
            return record

    def clear(self) -> None:
        """Remove all attachment metadata and forget every storage key.

        Test/observability helper in the same spirit as the other in-memory
        stores; deliberately not part of the port.
        """
        self._attachments.clear()
        self._storage_keys.clear()


# ============================================================
# END: In-Memory Attachment Repository
# ============================================================
