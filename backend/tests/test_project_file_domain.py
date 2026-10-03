"""Domain and port contracts for Project-owned files."""

import inspect
from datetime import UTC, datetime, timedelta, timezone

import pytest

from ava.repositories import ProjectFileContentPort, ProjectFileRecord, ProjectFileRepository
from ava.repositories.attachment_content_store import AttachmentContentStore
from ava.repositories.attachment_repository import AttachmentRecord


def record(**overrides: object) -> ProjectFileRecord:
    now = datetime(2026, 10, 2, tzinfo=UTC)
    values: dict[str, object] = {
        "id": "4ee474bd-68d1-4fd4-b15f-a48d918c944c",
        "project_id": "project-1",
        "file_name": "résumé-日本語.pdf",
        "content_type": "application/pdf",
        "size_bytes": 0,
        "content_ref": "ava-content:55dfa2b6",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return ProjectFileRecord(**values)  # type: ignore[arg-type]


def test_record_preserves_unicode_and_allows_zero_byte_files() -> None:
    value = record()

    assert value.file_name == "résumé-日本語.pdf"
    assert value.size_bytes == 0
    assert value.content_type == "application/pdf"
    assert value.content_ref == "ava-content:55dfa2b6"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", " \t"),
        ("project_id", " "),
        ("file_name", "\n"),
        ("content_ref", " "),
    ],
)
def test_record_rejects_blank_required_identity_and_metadata(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        record(**{field: value})


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_record_rejects_negative_or_non_integer_size(value: object) -> None:
    with pytest.raises(ValueError, match="size_bytes"):
        record(size_bytes=value)


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
def test_record_requires_timezone_aware_timestamps(field: str) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        record(**{field: datetime(2026, 10, 2)})


def test_record_accepts_non_utc_aware_timestamps_without_rewriting_them() -> None:
    eastern = timezone(timedelta(hours=-4))
    value = record(created_at=datetime(2026, 10, 2, tzinfo=eastern))

    assert value.created_at.utcoffset() == timedelta(hours=-4)


def test_duplicate_filenames_are_distinct_project_file_resources() -> None:
    first = record(id="file-1")
    second = record(id="file-2")

    assert first.file_name == second.file_name
    assert first.id != second.id
    assert first.project_id == second.project_id


def test_record_contains_only_project_file_metadata_and_opaque_content_identity() -> None:
    assert set(ProjectFileRecord.__dataclass_fields__) == {
        "id",
        "project_id",
        "file_name",
        "content_type",
        "size_bytes",
        "content_ref",
        "created_at",
        "updated_at",
    }


def test_project_file_repository_is_a_metadata_only_port() -> None:
    assert set(ProjectFileRepository.__abstractmethods__) == {
        "create",
        "get",
        "list_by_project",
        "delete",
        "delete_by_project",
    }
    assert "read" not in ProjectFileRepository.__abstractmethods__
    assert "content" not in ProjectFileRecord.__dataclass_fields__


def test_project_file_content_port_is_separate_from_attachment_port() -> None:
    assert ProjectFileContentPort is not AttachmentContentStore
    assert not issubclass(ProjectFileContentPort, AttachmentContentStore)
    assert set(ProjectFileContentPort.__abstractmethods__) == {"write", "read", "delete", "exists"}
    assert ProjectFileRecord is not AttachmentRecord


def test_project_file_architecture_keeps_routes_and_service_on_ports() -> None:
    from ava.api.routes import projects
    from ava.infrastructure.project_file_content_store import LocalProjectFileContentStore
    from ava.services import project_file_service

    route_source = inspect.getsource(projects)
    service_source = inspect.getsource(project_file_service)
    assert "LocalProjectFileContentStore" not in route_source
    assert "ava.infrastructure" not in service_source
    assert issubclass(LocalProjectFileContentStore, ProjectFileContentPort)
