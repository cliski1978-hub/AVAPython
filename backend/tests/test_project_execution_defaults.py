"""Phase 5.72 Project execution-default persistence and validation coverage."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ava.configuration.settings import Settings
from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.contracts.projects import UpdateProjectExecutionDefaultsRequest
from ava.infrastructure.composition import create_application_persistence, create_runtime_registry
from ava.models.model_configurations import ModelConfiguration
from ava.models.model_registry import ModelDisabledError, UnknownModelError
from ava.models.provider_connections import ProviderConnection
from ava.repositories.project import ProjectExecutionDefaults, ProjectRecord
from ava.runtimes.resolver import RuntimeResolver, UnknownRuntimeError
from ava.services.project_execution_defaults_service import ProjectExecutionDefaultsService
from ava.services.project_service import ProjectNotFoundError


def _model(model_id: str = "model-a", *, enabled: bool = True) -> ModelConfiguration:
    return ModelConfiguration(
        model_id=model_id,
        provider_connection_id="connection-a",
        provider_model_name="provider-model-a",
        display_name="Model A",
        hosting_mode=ModelHostingMode.COMPANY_HOSTED,
        capabilities=ModelCapabilities(chat=True),
        enabled=enabled,
    )


def _service(provider: str, database_path: str | None = None):
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=database_path)
    )
    if persistence.provider_connection_repository.get("connection-a") is None:
        persistence.provider_connection_repository.create(ProviderConnection("connection-a", "provider-x", "Provider"))
    model = _model()
    if persistence.model_configuration_repository.get(model.model_id) is None:
        persistence.model_configuration_repository.create(model)
    if persistence.model_configuration_repository.get("model-b") is None:
        persistence.model_configuration_repository.create(_model("model-b"))
    if persistence.model_configuration_repository.get("disabled") is None:
        persistence.model_configuration_repository.create(_model("disabled", enabled=False))
    runtime_registry = create_runtime_registry()
    service = ProjectExecutionDefaultsService(
        projects=persistence.project_repository,
        models=persistence.model_configuration_repository,
        runtimes=RuntimeResolver(runtime_registry),
    )
    now = datetime(2026, 10, 1, tzinfo=UTC)
    return persistence, service, ProjectRecord("p1", "Project", now, now)


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_defaults_patch_null_omission_independence_and_validation(provider: str, tmp_path: Path) -> None:
    persistence, service, project = _service(provider, str(tmp_path / f"{provider}.sqlite3"))
    try:
        persistence.project_repository.create(project)
        assert service.get("p1").execution_defaults == ProjectExecutionDefaults()

        both = service.update("p1", UpdateProjectExecutionDefaultsRequest(runtime_key="native", model_id="model-a"))
        assert both.execution_defaults == ProjectExecutionDefaults("native", "model-a")
        archived = replace(both, is_archived=True)
        assert persistence.project_repository.update(archived) == archived
        assert service.update("p1", UpdateProjectExecutionDefaultsRequest(model_id="model-b")).execution_defaults == (
            ProjectExecutionDefaults("native", "model-b")
        )
        assert service.update("p1", UpdateProjectExecutionDefaultsRequest(runtime_key=None)).execution_defaults == (
            ProjectExecutionDefaults(None, "model-b")
        )
        assert service.update("p1", UpdateProjectExecutionDefaultsRequest(model_id=None)).execution_defaults == (
            ProjectExecutionDefaults(None, None)
        )
        unchanged = service.get("p1")
        with pytest.raises(UnknownRuntimeError):
            service.update("p1", UpdateProjectExecutionDefaultsRequest(runtime_key="missing"))
        with pytest.raises(UnknownModelError):
            service.update("p1", UpdateProjectExecutionDefaultsRequest(model_id="missing"))
        with pytest.raises(ModelDisabledError):
            service.update("p1", UpdateProjectExecutionDefaultsRequest(model_id="disabled"))
        assert service.get("p1") == unchanged
        with pytest.raises(ProjectNotFoundError):
            service.get("missing")
        assert persistence.project_repository.delete("p1") is True
        assert persistence.project_repository.get("p1") is None
    finally:
        persistence.dispose()


def test_sqlite_project_defaults_survive_restart_and_model_delete_clears_reference(tmp_path: Path) -> None:
    path = str(tmp_path / "project-defaults.sqlite3")
    persistence, service, project = _service("relational", path)
    persistence.project_repository.create(project)
    service.update("p1", UpdateProjectExecutionDefaultsRequest(runtime_key="openhands", model_id="model-a"))
    with persistence.database.connect() as connection:  # type: ignore[union-attr]
        row = connection.execute(
            "SELECT default_runtime_key, default_model_id FROM projects WHERE id='p1'"
        ).fetchone()
        assert tuple(row) == ("openhands", "model-a")
        connection.execute("DELETE FROM model_configurations WHERE model_id = 'model-a'")
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    persistence.dispose()

    reopened, reopened_service, _ = _service("relational", path)
    try:
        assert reopened_service.get("p1").execution_defaults == ProjectExecutionDefaults("openhands", None)
        reopened_service.update("p1", UpdateProjectExecutionDefaultsRequest(runtime_key=None))
    finally:
        reopened.dispose()

    after_clear, after_clear_service, _ = _service("relational", path)
    try:
        assert after_clear_service.get("p1").execution_defaults == ProjectExecutionDefaults()
    finally:
        after_clear.dispose()
