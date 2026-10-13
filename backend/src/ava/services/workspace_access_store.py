from threading import Lock

from ava.contracts.workspace_access import WorkspaceAccessConfiguration
from ava.repositories.workspace_access_repository import (
    WorkspaceAccessAlreadyExistsError,
    WorkspaceAccessConflictError,
    WorkspaceAccessRepository,
)


class WorkspaceAccessStore(WorkspaceAccessRepository):
    def __init__(self) -> None:
        self._items: dict[str, WorkspaceAccessConfiguration] = {}
        self._lock = Lock()

    def list(self) -> list[WorkspaceAccessConfiguration]:
        with self._lock:
            return [self._items[key] for key in sorted(self._items)]

    def get(self, workspace_id: str) -> WorkspaceAccessConfiguration | None:
        with self._lock:
            return self._items.get(workspace_id)

    def create(self, configuration: WorkspaceAccessConfiguration) -> None:
        with self._lock:
            if configuration.workspace_id in self._items:
                raise WorkspaceAccessAlreadyExistsError(configuration.workspace_id)
            if configuration.revision != 1:
                raise ValueError("new Workspace revision must be 1")
            self._items[configuration.workspace_id] = configuration

    def compare_and_set(self, expected_revision: int, configuration: WorkspaceAccessConfiguration) -> None:
        with self._lock:
            current = self._items.get(configuration.workspace_id)
            if current is None or current.revision != expected_revision:
                raise WorkspaceAccessConflictError(configuration.workspace_id)
            if configuration.revision != expected_revision + 1:
                raise ValueError("Workspace revision must advance by one")
            if current.status.value == "revoked" and configuration.status.value != "revoked":
                raise ValueError("revoked Workspace identity cannot be reactivated")
            self._items[configuration.workspace_id] = configuration
