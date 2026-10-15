"""Application behavior for Project lifecycle and metadata."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ava.contracts.projects import UpdateProjectRequest
from ava.repositories.project import ProjectRecord
from ava.repositories.project_repository import ProjectRepository
from ava.services.project_file_service import ProjectFileService


class ProjectNotFoundError(Exception):
    """Raised when an operation targets an unknown Project."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"Unknown Project: {project_id}")


class InvalidProjectNameError(ValueError):
    """Raised when a Project name is blank after trimming."""


class DuplicateProjectIdentityError(Exception):
    """Raised if the generated Project identity collides with a stored ID."""


class ProjectService:
    """Own Project identity, name, timestamp, archive, and delete semantics."""

    def __init__(
        self,
        *,
        project_repository: ProjectRepository,
        project_file_service: ProjectFileService | None = None,
        delete_project_conversations: Callable[[str], tuple[str, ...]] | None = None,
    ) -> None:
        self._projects = project_repository
        self._project_files = project_file_service
        self._delete_project_conversations = delete_project_conversations

    def create_project(
        self,
        *,
        name: str,
        description: str | None = None,
        instructions: str | None = None,
        owner_principal_ref: str | None = None,
        owner_tenant_ref: str | None = None,
    ) -> ProjectRecord:
        normalized_name = self._normalize_name(name)
        now = datetime.now(UTC)
        project = ProjectRecord(
            id=str(uuid4()),
            name=normalized_name,
            description=description,
            instructions=instructions,
            is_archived=False,
            created_at=now,
            updated_at=now,
            owner_principal_ref=owner_principal_ref,
            owner_tenant_ref=owner_tenant_ref,
        )
        try:
            return self._projects.create(project)
        except ValueError as exc:
            raise DuplicateProjectIdentityError("Could not create Project due to an identity collision.") from exc

    def get_project(self, project_id: str) -> ProjectRecord:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project

    def list_projects(self) -> list[ProjectRecord]:
        """Return all Projects, including archived ones, in repository order."""
        return list(self._projects.list())

    def list_projects_for_owner(self, principal_ref: str, tenant_ref: str | None) -> list[ProjectRecord]:
        return [
            item for item in self._projects.list()
            if item.owner_principal_ref == principal_ref and item.owner_tenant_ref == tenant_ref
        ]

    def is_owned_by(self, project_id: str, principal_ref: str, tenant_ref: str | None) -> bool:
        project = self._projects.get(project_id)
        return project is not None and (
            project.owner_principal_ref == principal_ref and project.owner_tenant_ref == tenant_ref
        )

    def update_project(self, project_id: str, request: UpdateProjectRequest) -> ProjectRecord:
        current = self.get_project(project_id)
        normalized_name = self._normalize_name(request.name)
        updated = replace(
            current,
            name=normalized_name,
            description=(request.description if "description" in request.model_fields_set else current.description),
            instructions=(request.instructions if "instructions" in request.model_fields_set else current.instructions),
            updated_at=self._next_updated_at(current.updated_at),
        )
        persisted = self._projects.update(updated)
        if persisted is None:
            raise ProjectNotFoundError(project_id)
        return persisted

    def set_archived(self, project_id: str, is_archived: bool) -> ProjectRecord:
        current = self.get_project(project_id)
        if current.is_archived == is_archived:
            return current
        updated = replace(
            current,
            is_archived=is_archived,
            updated_at=self._next_updated_at(current.updated_at),
        )
        persisted = self._projects.update(updated)
        if persisted is None:
            raise ProjectNotFoundError(project_id)
        return persisted

    def delete_project(self, project_id: str, *, delete_conversations: bool = False) -> tuple[str, ...] | None:
        if self._projects.get(project_id) is None:
            raise ProjectNotFoundError(project_id)
        deleted_conversation_ids: tuple[str, ...] = ()
        if delete_conversations:
            if self._delete_project_conversations is None:
                raise RuntimeError("Project conversation deletion is not configured")
            deleted_conversation_ids = self._delete_project_conversations(project_id)
        if self._project_files is not None:
            self._project_files.delete_project(project_id)
        elif not self._projects.delete(project_id):
            raise ProjectNotFoundError(project_id)
        return deleted_conversation_ids if delete_conversations else None

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise InvalidProjectNameError("Project name must not be blank.")
        return normalized

    @staticmethod
    def _next_updated_at(previous: datetime) -> datetime:
        now = datetime.now(UTC)
        if now <= previous:
            return previous + timedelta(microseconds=1)
        return now
