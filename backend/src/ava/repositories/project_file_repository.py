"""AVA-owned metadata repository port for Project files."""

from abc import ABC, abstractmethod
from collections.abc import Collection

from ava.repositories.project_file import ProjectFileRecord


class DuplicateProjectFileNameError(ValueError):
    """A Project already owns a filename with the same normalized key."""

    def __init__(self, project_id: str, file_name: str) -> None:
        super().__init__(f"Project {project_id!r} already contains filename {file_name!r}")
        self.project_id = project_id
        self.file_name = file_name


class ProjectFileRepository(ABC):
    """Metadata-only persistence operations for Project-owned file records.

    Returned collections from ``list_by_project`` must use this canonical
    order: case-insensitive filename (Unicode ``casefold``), then
    ``created_at`` ascending, then opaque ``id`` ascending. Filenames are
    unique per Project after whitespace trimming and case-folding.

    ``delete`` and ``delete_by_project`` remove metadata only. The future
    ProjectFileService coordinates those operations with content deletion;
    repositories never read, write, or return binary bytes.
    """

    @abstractmethod
    def create(self, record: ProjectFileRecord) -> ProjectFileRecord:
        """Persist a new metadata record; duplicate IDs and Project names fail."""
        raise NotImplementedError

    @abstractmethod
    def get(self, file_id: str) -> ProjectFileRecord | None:
        """Return metadata for one file, or ``None`` when its ID is unknown."""
        raise NotImplementedError

    @abstractmethod
    def list_by_project(self, project_id: str) -> Collection[ProjectFileRecord]:
        """Return the Project's records in canonical deterministic order."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, file_id: str) -> ProjectFileRecord | None:
        """Delete metadata by ID and return the removed record, or ``None``."""
        raise NotImplementedError

    @abstractmethod
    def delete_by_project(self, project_id: str) -> Collection[ProjectFileRecord]:
        """Delete and return metadata rows owned by a Project in canonical order."""
        raise NotImplementedError
