"""AVA-owned repository port for Project persistence."""

from abc import ABC, abstractmethod
from collections.abc import Collection

from ava.repositories.project import ProjectRecord
from ava.repositories.project_file import ProjectFileRecord
from ava.repositories.project_file_repository import ProjectFileRepository


class ProjectRepository(ABC):
    """Persistence operations for independent Project metadata."""

    @abstractmethod
    def create(self, project: ProjectRecord) -> ProjectRecord:
        """Persist the supplied Project snapshot; duplicate IDs are rejected."""
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str) -> ProjectRecord | None:
        """Return a Project snapshot, or ``None`` when its ID is unknown."""
        raise NotImplementedError

    @abstractmethod
    def list(self) -> Collection[ProjectRecord]:
        """Return all Projects in deterministic repository order."""
        raise NotImplementedError

    @abstractmethod
    def update(self, project: ProjectRecord) -> ProjectRecord | None:
        """Replace the matching snapshot, or return ``None`` when not found."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, project_id: str) -> bool:
        """Delete a Project and clear conversation memberships atomically."""
        raise NotImplementedError

    def delete_with_project_files(
        self, project_id: str, files: ProjectFileRepository
    ) -> tuple[bool, Collection[ProjectFileRecord]]:
        """Delete the Project and return its removed file metadata.

        Adapters with a shared transactional database should override this to
        collect metadata and delete the Project in one transaction. The
        synchronous in-memory adapter can use this default safely because no
        other operation interleaves between these calls.
        """
        records = tuple(files.list_by_project(project_id))
        return self.delete(project_id), records
