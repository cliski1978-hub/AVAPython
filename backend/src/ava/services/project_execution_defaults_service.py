"""Persistence-only Project execution preference behavior."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ava.contracts.projects import UpdateProjectExecutionDefaultsRequest
from ava.models.model_registry import ModelDisabledError, UnknownModelError
from ava.repositories.model_configuration_repository import ModelConfigurationRepository
from ava.repositories.project import ProjectExecutionDefaults, ProjectRecord
from ava.repositories.project_repository import ProjectRepository
from ava.runtimes.resolver import RuntimeResolver
from ava.services.project_service import ProjectNotFoundError


class ProjectExecutionDefaultsService:
    """Validate independent references and persist them without resolving runs."""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        models: ModelConfigurationRepository,
        runtimes: RuntimeResolver,
    ) -> None:
        self._projects = projects
        self._models = models
        self._runtimes = runtimes

    def get(self, project_id: str) -> ProjectRecord:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project

    def update(self, project_id: str, request: UpdateProjectExecutionDefaultsRequest) -> ProjectRecord:
        current = self.get(project_id)
        fields = request.model_fields_set
        defaults = current.execution_defaults
        runtime_key = defaults.runtime_key
        model_id = defaults.model_id
        if "runtime_key" in fields:
            runtime_key = request.runtime_key
            if runtime_key is not None:
                self._runtimes.resolve(runtime_key)
        if "model_id" in fields:
            model_id = request.model_id
            if model_id is not None:
                model = self._models.get(model_id)
                if model is None:
                    raise UnknownModelError(model_id)
                if not model.enabled:
                    raise ModelDisabledError(model_id)
        if runtime_key == defaults.runtime_key and model_id == defaults.model_id:
            return current
        now = datetime.now(UTC)
        if now <= current.updated_at:
            now = current.updated_at + timedelta(microseconds=1)
        updated = replace(
            current,
            execution_defaults=ProjectExecutionDefaults(runtime_key=runtime_key, model_id=model_id),
            updated_at=now,
        )
        persisted = self._projects.update(updated)
        if persisted is None:
            raise ProjectNotFoundError(project_id)
        return persisted
