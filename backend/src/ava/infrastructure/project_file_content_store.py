"""Local filesystem implementation of Project-file content storage."""

import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO

from ava.repositories.project_file_content import ProjectFileContentPort

_SAFE_REF = re.compile(r"^[a-f0-9]{32}$")


class LocalProjectFileContentStore(ProjectFileContentPort):
    """Store bytes below an AVA-controlled root using opaque UUID hex refs."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, content_ref: str) -> Path:
        if not _SAFE_REF.fullmatch(content_ref):
            raise ValueError("Invalid Project file content reference")
        return self._root / content_ref

    def write(self, content_ref: str, source: BinaryIO) -> int:
        target = self._path(content_ref)
        if target.exists():
            raise ValueError("Project file content reference already exists")
        fd, temporary = tempfile.mkstemp(prefix=".ava-project-file-", dir=self._root)
        size = 0
        try:
            with os.fdopen(fd, "wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, target)
            return size
        finally:
            Path(temporary).unlink(missing_ok=True)

    def read(self, content_ref: str) -> BinaryIO:
        return self._path(content_ref).open("rb")

    def delete(self, content_ref: str) -> bool:
        target = self._path(content_ref)
        try:
            target.unlink()
        except FileNotFoundError:
            return False
        return True

    def exists(self, content_ref: str) -> bool:
        return self._path(content_ref).is_file()
