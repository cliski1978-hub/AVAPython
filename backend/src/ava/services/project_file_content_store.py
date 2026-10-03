"""In-memory implementation of the Project-file binary content port."""

from io import BytesIO
from typing import BinaryIO

from ava.repositories.project_file_content import ProjectFileContentPort


class InMemoryProjectFileContentStore(ProjectFileContentPort):
    def __init__(self) -> None:
        self._content: dict[str, bytes] = {}

    def write(self, content_ref: str, source: BinaryIO) -> int:
        if content_ref in self._content:
            raise ValueError("Project file content reference already exists")
        data = source.read()
        self._content[content_ref] = data
        return len(data)

    def read(self, content_ref: str) -> BinaryIO:
        try:
            return BytesIO(self._content[content_ref])
        except KeyError as exc:
            raise FileNotFoundError(content_ref) from exc

    def delete(self, content_ref: str) -> bool:
        return self._content.pop(content_ref, None) is not None

    def exists(self, content_ref: str) -> bool:
        return content_ref in self._content
