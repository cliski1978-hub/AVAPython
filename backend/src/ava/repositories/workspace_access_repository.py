from abc import ABC, abstractmethod

from ava.contracts.workspace_access import WorkspaceAccessConfiguration


class WorkspaceAccessConflictError(ValueError):
    """A newer Workspace configuration already exists."""


class WorkspaceAccessAlreadyExistsError(ValueError):
    """Workspace identity is already reserved, including revoked records."""


class WorkspaceAccessRepository(ABC):
    @abstractmethod
    def list(self) -> list[WorkspaceAccessConfiguration]: ...

    @abstractmethod
    def get(self, workspace_id: str) -> WorkspaceAccessConfiguration | None: ...

    @abstractmethod
    def create(self, configuration: WorkspaceAccessConfiguration) -> None: ...

    @abstractmethod
    def compare_and_set(self, expected_revision: int, configuration: WorkspaceAccessConfiguration) -> None:
        """Atomically replace one identity only when its revision still matches."""
