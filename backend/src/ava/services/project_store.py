"""In-memory Project repository adapter."""

from ava.repositories.conversation_repository import ConversationRepository
from ava.repositories.core_prompt_assignment import CorePromptScopeType
from ava.repositories.core_prompt_assignment_repository import CorePromptAssignmentRepository
from ava.repositories.project import ProjectRecord
from ava.repositories.project_file_repository import ProjectFileRepository
from ava.repositories.project_repository import ProjectRepository


class ProjectStore(ProjectRepository):
    """Memory implementation preserving complete canonical Project snapshots."""

    def __init__(
        self,
        conversations: ConversationRepository,
        assignments: CorePromptAssignmentRepository | None = None,
        files: ProjectFileRepository | None = None,
    ) -> None:
        self._conversations = conversations
        self._assignments = assignments
        self._files = files
        self._projects: dict[str, ProjectRecord] = {}

    def create(self, project: ProjectRecord) -> ProjectRecord:
        if project.id in self._projects:
            raise ValueError(f"Project {project.id!r} already exists")
        self._projects[project.id] = project
        return project

    def get(self, project_id: str) -> ProjectRecord | None:
        return self._projects.get(project_id)

    def list(self) -> list[ProjectRecord]:
        return sorted(
            self._projects.values(),
            key=lambda item: (item.is_archived, item.name.casefold(), item.created_at, item.id),
        )

    def update(self, project: ProjectRecord) -> ProjectRecord | None:
        if project.id not in self._projects:
            return None
        self._projects[project.id] = project
        return project

    def delete(self, project_id: str) -> bool:
        if project_id not in self._projects:
            return False
        affected = [item for item in self._conversations.list() if item.project_id == project_id]
        removed_files = []
        try:
            for item in affected:
                self._conversations.set_project(item.conversation_id, None)
            if self._assignments is not None:
                self._assignments.delete_for_scope(CorePromptScopeType.PROJECT, project_id)
            if self._files is not None:
                removed_files = list(self._files.delete_by_project(project_id))
            del self._projects[project_id]
        except BaseException:
            for item in affected:
                self._conversations.set_project(item.conversation_id, project_id)
            for record in removed_files:
                if self._files is not None:
                    self._files.create(record)
            raise
        return True
