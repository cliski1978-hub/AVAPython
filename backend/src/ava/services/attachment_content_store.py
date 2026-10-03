"""In-memory AVA attachment content store (Step 4.14.B development/test adapter).

The smallest concrete ``AttachmentContentStore`` needed to validate the
streaming port before any local-filesystem work. Holds ``storage_key -> bytes``
in memory because it is explicitly an in-memory adapter; the public streaming
contract is unchanged. Binary content only: no ``AttachmentRecord``, ownership,
status, filename, or media-type knowledge, and no storage-key generation.
"""

from io import BytesIO
from typing import BinaryIO

from ava.repositories.attachment_content_store import (
    AttachmentContentStore,
    StoredContentInfo,
)

_READ_CHUNK_SIZE = 64 * 1024


class InMemoryAttachmentContentStore(AttachmentContentStore):
    """In-memory ``storage_key -> bytes`` content store for tests and dev.

    Reads the caller-provided source incrementally in bounded chunks from its
    current position until EOF, stores the exact bytes under the given opaque
    key, and never closes the caller's stream. Duplicate keys are rejected so
    existing content is never silently overwritten; ``open`` returns a fresh
    ``BytesIO`` per call.
    """

    def __init__(self) -> None:
        self._contents: dict[str, bytes] = {}

    def put(
        self,
        storage_key: str,
        source: BinaryIO,
    ) -> StoredContentInfo:
        if storage_key in self._contents:
            raise ValueError(f"Attachment content already exists for storage key: {storage_key}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = source.read(_READ_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            chunks.append(chunk)
        self._contents[storage_key] = b"".join(chunks)
        return StoredContentInfo(size_bytes=total)

    def open(
        self,
        storage_key: str,
    ) -> BinaryIO:
        try:
            content = self._contents[storage_key]
        except KeyError:
            raise FileNotFoundError(f"Attachment content not found for storage key: {storage_key}") from None
        return BytesIO(content)

    def exists(
        self,
        storage_key: str,
    ) -> bool:
        return storage_key in self._contents

    def delete(self, storage_key: str) -> bool:
        """Delete stored bytes by key, returning false when absent."""
        return self._contents.pop(storage_key, None) is not None

    def clear(self) -> None:
        """Drop all stored content; the store returns to its initial state."""
        self._contents.clear()
