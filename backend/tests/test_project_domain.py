"""Phase 5.56 Project domain and contract boundary tests."""

from dataclasses import fields
from datetime import UTC, datetime
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from ava.contracts import (
    ConversationResponse,
    CreateProjectRequest,
    ProjectListResponse,
    ProjectResponse,
    SetProjectArchivedRequest,
    UpdateProjectRequest,
)
from ava.contracts.version import CONTRACT_VERSION
from ava.repositories import ConversationRecord, ProjectRecord


def test_project_record_has_the_canonical_fields_and_defaults() -> None:
    created_at = datetime(2026, 10, 1, tzinfo=UTC)
    updated_at = datetime(2026, 10, 2, tzinfo=UTC)
    project = ProjectRecord(
        id="project-1",
        name="Research",
        created_at=created_at,
        updated_at=updated_at,
    )

    assert [field.name for field in fields(project)] == [
        "id",
        "name",
        "created_at",
        "updated_at",
        "description",
        "instructions",
        "is_archived",
        "execution_defaults",
    ]
    assert project.description is None
    assert project.instructions is None
    assert project.is_archived is False
    assert project.execution_defaults.runtime_key is None
    assert project.execution_defaults.model_id is None
    assert project.created_at is created_at
    assert project.updated_at is updated_at


def test_project_record_supports_optional_context_metadata() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    project = ProjectRecord(
        id="project-2",
        name="Planning",
        created_at=now,
        updated_at=now,
        description="Planning workspace",
        instructions="Use concise answers",
        is_archived=True,
    )

    assert (project.id, project.name) == ("project-2", "Planning")
    assert project.description == "Planning workspace"
    assert project.instructions == "Use concise answers"
    assert project.is_archived is True


def test_project_response_matches_the_public_snapshot_shape() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    response = ProjectResponse(
        id="project-1",
        name="Research",
        created_at=now,
        updated_at=now,
    )

    expected = {
        "id",
        "name",
        "description",
        "instructions",
        "is_archived",
        "created_at",
        "updated_at",
        "contract_version",
    }
    assert set(ProjectResponse.model_fields) == expected
    assert set(response.model_dump()) == expected
    assert response.description is None
    assert response.instructions is None
    assert response.is_archived is False
    assert response.contract_version == CONTRACT_VERSION


@pytest.mark.parametrize("request_type", [CreateProjectRequest, UpdateProjectRequest])
def test_project_write_contracts_reject_blank_names(request_type: type) -> None:
    assert request_type(name="Research").name == "Research"
    # The contract preserves input; the application service trims on write.
    assert request_type(name="  Research  ").name == "  Research  "
    with pytest.raises(ValidationError):
        request_type(name="")
    with pytest.raises(ValidationError):
        request_type(name=" \t\n ")


def test_project_write_contracts_keep_only_descriptive_metadata() -> None:
    create = CreateProjectRequest(name="Research", description="", instructions=None)
    update = UpdateProjectRequest(name="Research", description="Changed", instructions="Guide")

    assert create.description == ""
    assert create.instructions is None
    assert update.description == "Changed"
    assert update.instructions == "Guide"
    assert set(CreateProjectRequest.model_fields) == {
        "name",
        "description",
        "instructions",
        "contract_version",
    }
    assert set(UpdateProjectRequest.model_fields) == {
        "name",
        "description",
        "instructions",
        "contract_version",
    }


def test_project_display_names_do_not_need_to_be_unique() -> None:
    first = CreateProjectRequest(name="Research")
    second = CreateProjectRequest(name="Research")

    assert first.name == second.name


def test_project_list_and_archive_contracts_are_explicit() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    project = ProjectResponse(id="project-1", name="Research", created_at=now, updated_at=now)
    listed = ProjectListResponse(projects=[project])

    assert listed.projects == [project]
    assert SetProjectArchivedRequest(is_archived=True).is_archived is True
    with pytest.raises(ValidationError):
        SetProjectArchivedRequest(is_archived="yes")


def test_project_has_no_future_relationship_or_execution_fields() -> None:
    forbidden = {
        "model_id",
        "runtime_id",
        "workspace_id",
        "files",
        "folder_id",
        "conversation_ids",
        "knowledge_status",
        "vector_store_id",
    }
    record_fields = {field.name for field in fields(ProjectRecord)}
    response_fields = set(ProjectResponse.model_fields)

    assert forbidden.isdisjoint(record_fields)
    assert forbidden.isdisjoint(response_fields)
    hints = get_type_hints(ProjectRecord)
    assert hints["description"] == str | None
    assert hints["instructions"] == str | None
    assert get_type_hints(ConversationRecord)["project_id"] == str | None
    assert "project_id" in ConversationResponse.model_fields
