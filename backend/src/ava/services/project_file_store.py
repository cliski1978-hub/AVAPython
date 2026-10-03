"""In-memory metadata adapter for Project files."""

from ava.repositories.project_file import ProjectFileRecord
from ava.repositories.project_file_repository import ProjectFileRepository


def _order(item: ProjectFileRecord) -> tuple[str, object, str]:
    return (item.file_name.casefold(), item.created_at, item.id)


class ProjectFileStore(ProjectFileRepository):
    def __init__(self) -> None:
        self._items: dict[str, ProjectFileRecord] = {}

    def create(self, record: ProjectFileRecord) -> ProjectFileRecord:
        if record.id in self._items:
            raise ValueError(f"Project file {record.id!r} already exists")
        self._items[record.id] = record
        return record

    def get(self, file_id: str) -> ProjectFileRecord | None:
        return self._items.get(file_id)

    def list_by_project(self, project_id: str) -> list[ProjectFileRecord]:
        return sorted((item for item in self._items.values() if item.project_id == project_id), key=_order)

    def delete(self, file_id: str) -> ProjectFileRecord | None:
        return self._items.pop(file_id, None)

    def delete_by_project(self, project_id: str) -> list[ProjectFileRecord]:
        items = self.list_by_project(project_id)
        for item in items:
            self._items.pop(item.id, None)
        return items
