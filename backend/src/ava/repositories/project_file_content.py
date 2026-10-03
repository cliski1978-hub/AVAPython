"""Binary-content port for Project files, separate from their metadata."""

from abc import ABC, abstractmethod
from typing import BinaryIO


class ProjectFileContentPort(ABC):
    """Opaque-reference binary storage operations used by future services.

    This port is separate from ``AttachmentContentStore`` because that port's
    lifecycle contract is explicitly attachment-scoped. Implementations must
    treat ``content_ref`` as an opaque logical key, never as a public URL or
    caller-controlled filesystem path. The port is defined here without an
    infrastructure adapter; persistence and storage are later work.
    """

    @abstractmethod
    def write(self, content_ref: str, source: BinaryIO) -> int:
        """Store bytes under a new opaque reference and return the stored size.

        Existing references must not be overwritten. The caller owns the
        source stream.
        """
        raise NotImplementedError

    @abstractmethod
    def read(self, content_ref: str) -> BinaryIO:
        """Return a fresh caller-owned binary stream for the opaque reference."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, content_ref: str) -> bool:
        """Delete content, returning false when the reference is already absent."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, content_ref: str) -> bool:
        """Return whether bytes exist for the reference without side effects."""
        raise NotImplementedError
