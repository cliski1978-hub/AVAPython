"""AVA attachment content-store port (Step 4.14.B).

Binary physical-content abstraction for attachments. Lives beside the
attachment metadata repository but stays deliberately separate: this port
deals only with ``storage_key``, binary content, and stored-content
information — never ``AttachmentRecord``, ownership, status, or media-type
metadata. Durable providers (local disk, object storage, volumes) satisfy it
in later steps.

    AttachmentRepository   → durable metadata only
    AttachmentContentStore → physical file/content bytes only

The ``storage_key`` is an opaque logical reference: the port neither generates
it nor interprets it as a filesystem path / URL / provider object key. The
port is storage-backend-neutral: only standard-library types and AVA-owned
types cross this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO


@dataclass(frozen=True)
class StoredContentInfo:
    """Results of a successful content-store write.

    ``size_bytes`` is the authoritative stored byte count, reported by the
    content-store implementation from what it actually wrote (never supplied
    by the caller) and therefore always ``>= 0``. Checksum, etag, version,
    bucket/container/path, and provider metadata are deliberately deferred.
    """

    size_bytes: int


class AttachmentContentStore(ABC):
    """Binary-only physical content abstraction for attachments.

    Streaming contract: ``put`` accepts a file-like binary source and reads it
    incrementally from its *current* stream position until EOF (no seek/tell
    requirement, no rewind); ``open`` returns a readable binary stream. Large
    payloads never need to be fully buffered by the caller, keeping the port
    compatible with local files, S3 streaming bodies, Azure blob streams, and
    Databricks/Volume files alike.

    Stream ownership: the caller owns the input source passed to ``put`` —
    this port never closes it — and owns every stream returned by ``open``,
    closing it when done. On duplicate ``storage_key``, ``put`` must reject
    (not silently overwrite) because a storage key is unique and immutable per
    attachment. ``open`` on an unknown key must raise ``FileNotFoundError``
    rather than return ``None``.
    """

    @abstractmethod
    def put(
        self,
        storage_key: str,
        source: BinaryIO,
    ) -> StoredContentInfo:
        """Copy ``source`` (from its current position to EOF) into storage.

        Rejects an existing ``storage_key`` with ``ValueError``. The caller
        keeps ownership of ``source``, which is left open and at EOF.
        """
        raise NotImplementedError()

    @abstractmethod
    def open(
        self,
        storage_key: str,
    ) -> BinaryIO:
        """Return a caller-owned readable stream over the stored bytes.

        Each call returns a fresh stream; closing one does not affect later
        reads or the stored content. Raises ``FileNotFoundError`` for an
        unknown key.
        """
        raise NotImplementedError()

    def delete(self, storage_key: str) -> bool:
        """Remove stored content by opaque key; return false when it is absent.

        Adapters that do not support deletion fail closed.
        """
        raise NotImplementedError()

    @abstractmethod
    def exists(
        self,
        storage_key: str,
    ) -> bool:
        """Return whether content exists for ``storage_key``. No side effects."""
        raise NotImplementedError()
