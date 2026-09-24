"""Local filesystem AVA attachment content store (Step 4.14.D).

The first physical ``AttachmentContentStore`` adapter: attachment content is
written as regular files beneath an explicitly configured storage root. This
is a physical infrastructure adapter (``ava.infrastructure``), so it may use
``os`` / ``pathlib`` / ``tempfile`` freely; the ports, contracts, and services
all stay storage-neutral.

Behavior:

* the configured root is required and explicit — a missing root is created
  (with parents), and a root that exists but is not a directory fails
  construction clearly;
* ``storage_key`` remains an opaque logical reference: absolute keys, ``..``
  traversal, symlink escapes, and keys resolving back onto the root itself
  are all rejected via resolved-path containment (never naive string
  checks);
* ``put`` streams the source in bounded chunks from its current position to
  a temporary file in the final directory, then atomically replaces it into
  place; duplicate and failed writes leave the final object untouched and
  clean the temporary file best-effort;
* ``open`` returns a real streaming binary reader; ``exists`` answers only
  for regular files (directories are never treated as stored content);
* selection stays independent of the metadata persistence provider
  (``AVA_PERSISTENCE != AVA_ATTACHMENT_STORAGE``).
"""

import contextlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from ava.repositories.attachment_content_store import (
    AttachmentContentStore,
    StoredContentInfo,
)

_READ_CHUNK_SIZE = 64 * 1024
_TEMP_PREFIX = ".avauptmp-"


class LocalAttachmentContentStore(AttachmentContentStore):
    """Filesystem ``AttachmentContentStore`` rooted at an explicit directory.

    ``put`` never writes directly to the final path: content is streamed to a
    temporary sibling file and atomically renamed into place, so a crash or
    source failure can never expose partially written content and a duplicate
    key can never be clobbered. Each ``open`` call returns an independent
    streaming binary reader; closing one affects nothing else.
    """

    def __init__(self, root_dir: Path) -> None:
        root = Path(root_dir)
        if root.exists() and not root.is_dir():
            raise ValueError(
                f"Attachment content storage root is not a directory: {root}"
            )
        root.mkdir(parents=True, exist_ok=True)
        #: Canonical absolute root used for containment checks. Resolved once:
        #: every candidate key resolves against the real root, so a symlinked
        #: path component cannot smuggle writes/reads outside it.
        self._root = root.resolve()

    def put(
        self,
        storage_key: str,
        source: BinaryIO,
    ) -> StoredContentInfo:
        final = self._resolve(storage_key)
        if final.exists():
            raise ValueError(
                f"Attachment content already exists for storage key: {storage_key}"
            )
        final.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=_TEMP_PREFIX, dir=final.parent)
        total = 0
        try:
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = source.read(_READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    out.write(chunk)
            if final.exists():
                raise ValueError(
                    f"Attachment content already exists for storage key: {storage_key}"
                )
            os.replace(tmp_name, final)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        return StoredContentInfo(size_bytes=total)

    def open(
        self,
        storage_key: str,
    ) -> BinaryIO:
        final = self._resolve(storage_key)
        if not final.is_file():
            raise FileNotFoundError(
                f"Attachment content not found for storage key: {storage_key}"
            )
        return final.open("rb")

    def exists(
        self,
        storage_key: str,
    ) -> bool:
        final = self._resolve(storage_key)
        return final.is_file()

    def _resolve(self, storage_key: str) -> Path:
        """Validate a logical key and resolve it strictly inside the root.

        Rejects empty keys, absolute (platform-)paths, keys containing ``..``
        (belt-and-braces; the resolved-containment check below is the real
        defense), and any key whose resolved path lands on the root itself or
        outside it — including symlink escapes. Consistency across all three
        public methods: an invalid key is always ``ValueError``.
        """
        if not storage_key:
            raise ValueError("Attachment storage key must not be empty")
        raw = Path(storage_key)
        if raw.is_absolute():
            raise ValueError(
                f"Attachment storage key must be a relative logical key: {storage_key!r}"
            )
        if ".." in raw.parts:
            raise ValueError(
                f"Attachment storage key must not contain parent traversal: {storage_key!r}"
            )
        final = (self._root / raw).resolve(strict=False)
        if final == self._root or self._root not in final.parents:
            raise ValueError(
                f"Attachment storage key escapes the storage root: {storage_key!r}"
            )
        return final