"""In-memory metadata adapter for Project files."""

from threading import RLock

from ava.repositories.project_file import ProjectFileRecord, normalize_project_file_name
from ava.repositories.project_file_repository import DuplicateProjectFileNameError, ProjectFileRepository


def _order(item: ProjectFileRecord) -> tuple[str, object, str]:
    return (item.file_name.casefold(), item.created_at, item.id)


class ProjectFileStore(ProjectFileRepository):
    def __init__(self) -> None:
        self._items: dict[str, ProjectFileRecord] = {}
        self._lock = RLock()

    def create(self, record: ProjectFileRecord) -> ProjectFileRecord:
        with self._lock:
            if record.id in self._items:
                raise ValueError(f"Project file {record.id!r} already exists")
            normalized = normalize_project_file_name(record.file_name)
            if any(
                item.project_id == record.project_id and normalize_project_file_name(item.file_name) == normalized
                for item in self._items.values()
            ):
                raise DuplicateProjectFileNameError(record.project_id, record.file_name)
            self._items[record.id] = record
        return record

    def get(self, file_id: str) -> ProjectFileRecord | None:
        with self._lock:
            return self._items.get(file_id)

    def list_by_project(self, project_id: str) -> list[ProjectFileRecord]:
        with self._lock:
            return sorted((item for item in self._items.values() if item.project_id == project_id), key=_order)

    def delete(self, file_id: str) -> ProjectFileRecord | None:
        with self._lock:
            return self._items.pop(file_id, None)

    def delete_by_project(self, project_id: str) -> list[ProjectFileRecord]:
        with self._lock:
            items = sorted((item for item in self._items.values() if item.project_id == project_id), key=_order)
            for item in items:
                self._items.pop(item.id, None)
            return items
