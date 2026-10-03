"""Phase 5.58 Project service behavior across repository adapters."""

from pathlib import Path
from uuid import UUID

import pytest

from ava.configuration.settings import Settings
from ava.contracts.projects import UpdateProjectRequest
from ava.infrastructure.composition import create_application_persistence
from ava.services.project_service import InvalidProjectNameError, ProjectNotFoundError, ProjectService


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_service_create_normalizes_names_and_allows_duplicates(provider: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}.sqlite3"))
    )
    service = ProjectService(project_repository=persistence.project_repository)
    try:
        first = service.create_project(
            name="  AVA Engineering  ",
            description=None,
            instructions="Inert instruction data",
        )
        second = service.create_project(name="AVA Engineering", description="")

        assert first.name == "AVA Engineering"
        assert first.id != second.id
        assert UUID(first.id).version == 4
        assert first.created_at.utcoffset() is not None
        assert first.created_at == first.updated_at
        assert first.is_archived is False
        assert first.description is None
        assert first.instructions == "Inert instruction data"
        assert second.description == ""
        assert second.instructions is None
        listed = service.list_projects()
        assert {project.id for project in listed} == {first.id, second.id}

        with pytest.raises(InvalidProjectNameError):
            service.create_project(name=" \t\n ")
    finally:
        persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_service_updates_partial_metadata_and_preserves_identity_state(provider: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}-update.sqlite3"))
    )
    service = ProjectService(project_repository=persistence.project_repository)
    try:
        created = service.create_project(
            name="Before",
            description="Keep description",
            instructions="Keep instructions",
        )
        archived = service.set_archived(created.id, True)
        updated = service.update_project(created.id, request=UpdateProjectRequest(name="  After  "))

        assert updated.id == created.id
        assert updated.name == "After"
        assert updated.created_at == created.created_at
        assert updated.updated_at > archived.updated_at
        assert updated.description == "Keep description"
        assert updated.instructions == "Keep instructions"
        assert updated.is_archived is True

        cleared = service.update_project(
            created.id,
            UpdateProjectRequest(name="After", description=None, instructions="Changed"),
        )
        assert cleared.description is None
        assert cleared.instructions == "Changed"
        assert cleared.is_archived is True
        assert cleared.created_at == created.created_at
        assert cleared.updated_at > updated.updated_at
    finally:
        persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_instruction_create_update_clear_and_archive_preserve_other_metadata(
    provider: str, tmp_path: Path
) -> None:
    persistence = create_application_persistence(
        Settings(
            persistence_provider=provider,
            persistence_database_url=str(tmp_path / f"{provider}-instructions.sqlite3"),
        )
    )
    service = ProjectService(project_repository=persistence.project_repository)
    original_text = "You are working on AVA.\n\nRules:\n- Keep spaces:   exactly.\n- 日本語 →"
    replacement_text = "Updated\n  multiline → text"
    try:
        created = service.create_project(
            name="Instructions", description="Description", instructions=original_text
        )
        assert created.instructions == original_text

        archived = service.set_archived(created.id, True)
        updated = service.update_project(
            created.id,
            UpdateProjectRequest(name="Instructions", instructions=replacement_text),
        )
        assert updated.instructions == replacement_text
        assert updated.id == created.id
        assert updated.name == created.name
        assert updated.description == created.description
        assert updated.is_archived is True
        assert updated.created_at == created.created_at
        assert updated.updated_at > archived.updated_at

        # An unrelated metadata update omits instructions and must preserve them.
        unrelated = service.update_project(created.id, UpdateProjectRequest(name="Renamed"))
        assert unrelated.instructions == replacement_text
        assert unrelated.updated_at > updated.updated_at

        # Archive/restore mutates only archive metadata; instructions survive both transitions.
        restored = service.set_archived(created.id, False)
        assert restored.instructions == replacement_text
        assert restored.is_archived is False

        cleared = service.update_project(created.id, UpdateProjectRequest(name="Renamed", instructions=None))
        assert cleared.instructions is None
        assert cleared.id == created.id
        assert cleared.name == unrelated.name
        assert cleared.description == created.description
        assert cleared.is_archived is False
        assert cleared.created_at == created.created_at
        assert cleared.updated_at > restored.updated_at
    finally:
        persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_archive_restore_are_idempotent_and_archived_projects_stay_listed(
    provider: str, tmp_path: Path
) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}-archive.sqlite3"))
    )
    service = ProjectService(project_repository=persistence.project_repository)
    try:
        project = service.create_project(name="Archive me")
        archived = service.set_archived(project.id, True)
        archived_again = service.set_archived(project.id, True)
        assert archived.is_archived is True
        assert archived_again == archived
        assert service.list_projects() == [archived]

        restored = service.set_archived(project.id, False)
        restored_again = service.set_archived(project.id, False)
        assert restored.is_archived is False
        assert restored_again == restored
        assert service.list_projects() == [restored]
    finally:
        persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_service_delete_and_not_found_behavior(provider: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}-delete.sqlite3"))
    )
    service = ProjectService(project_repository=persistence.project_repository)
    try:
        first = service.create_project(name="Delete me")
        second = service.create_project(name="Keep me")

        assert service.get_project(first.id) == first
        with pytest.raises(ProjectNotFoundError):
            service.get_project("missing")
        with pytest.raises(ProjectNotFoundError):
            service.update_project("missing", UpdateProjectRequest(name="No Project"))
        with pytest.raises(ProjectNotFoundError):
            service.set_archived("missing", True)

        service.delete_project(first.id)
        assert [project.id for project in service.list_projects()] == [second.id]
        with pytest.raises(ProjectNotFoundError):
            service.get_project(first.id)
        with pytest.raises(ProjectNotFoundError):
            service.delete_project(first.id)
    finally:
        persistence.dispose()


def test_project_service_lifecycle_survives_relational_restarts(tmp_path: Path) -> None:
    settings = Settings(persistence_provider="relational", persistence_database_url=str(tmp_path / "lifecycle.sqlite3"))
    first = create_application_persistence(settings)
    service = ProjectService(project_repository=first.project_repository)
    project = service.create_project(name="  Durable  ", description="Initial")
    first.dispose()

    second = create_application_persistence(settings)
    service = ProjectService(project_repository=second.project_repository)
    updated = service.update_project(
        project.id,
        UpdateProjectRequest(name="Durable updated", instructions="Still inert"),
    )
    assert updated.description == "Initial"
    second.dispose()

    third = create_application_persistence(settings)
    service = ProjectService(project_repository=third.project_repository)
    archived = service.set_archived(project.id, True)
    assert archived.is_archived is True
    third.dispose()

    fourth = create_application_persistence(settings)
    service = ProjectService(project_repository=fourth.project_repository)
    assert service.get_project(project.id) == archived
    service.set_archived(project.id, False)
    service.delete_project(project.id)
    fourth.dispose()

    fifth = create_application_persistence(settings)
    try:
        with pytest.raises(ProjectNotFoundError):
            ProjectService(project_repository=fifth.project_repository).get_project(project.id)
    finally:
        fifth.dispose()
