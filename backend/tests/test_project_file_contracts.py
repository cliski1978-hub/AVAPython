"""Public wire contracts for Project file metadata."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ava.contracts import (
    CreateProjectFileRequest,
    ProjectFileListResponse,
    ProjectFileResponse,
)


def response(**overrides: object) -> ProjectFileResponse:
    values: dict[str, object] = {
        "id": "file-1",
        "project_id": "project-1",
        "file_name": "résumé-日本語.pdf",
        "content_type": "application/pdf",
        "size_bytes": 12,
        "created_at": datetime(2026, 10, 2, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 2, tzinfo=UTC),
    }
    values.update(overrides)
    return ProjectFileResponse(**values)  # type: ignore[arg-type]


def test_create_request_contains_authored_metadata_but_no_bytes_or_storage_reference() -> None:
    request = CreateProjectFileRequest(file_name="résumé-日本語.pdf", content_type="application/pdf")

    assert request.file_name == "résumé-日本語.pdf"
    assert request.content_type == "application/pdf"
    assert "content" not in CreateProjectFileRequest.model_fields
    assert "content_ref" not in CreateProjectFileRequest.model_fields
    assert "size_bytes" not in CreateProjectFileRequest.model_fields


@pytest.mark.parametrize("file_name", ["", "  ", "\t\n"])
def test_create_request_rejects_blank_filename(file_name: str) -> None:
    with pytest.raises(ValidationError, match="file_name must not be blank"):
        CreateProjectFileRequest(file_name=file_name)


def test_response_exposes_safe_metadata_only() -> None:
    value = response()

    assert set(value.model_fields_set) == {
        "id",
        "project_id",
        "file_name",
        "content_type",
        "size_bytes",
        "created_at",
        "updated_at",
    }
    assert "content_ref" not in ProjectFileResponse.model_fields
    assert "absolute_path" not in ProjectFileResponse.model_fields
    assert "storage_path" not in ProjectFileResponse.model_fields
    assert "s3_url" not in ProjectFileResponse.model_fields
    assert value.file_name == "résumé-日本語.pdf"
    assert value.contract_version == "v1"


def test_response_allows_optional_content_type_and_zero_byte_size() -> None:
    value = response(content_type=None, size_bytes=0)

    assert value.content_type is None
    assert value.size_bytes == 0


def test_response_rejects_negative_size() -> None:
    with pytest.raises(ValidationError):
        response(size_bytes=-1)


def test_response_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        response(created_at=datetime(2026, 10, 2))


def test_list_response_wraps_project_owned_files() -> None:
    result = ProjectFileListResponse(project_id="project-1", files=[response()])

    assert result.project_id == "project-1"
    assert result.files == [response()]
    assert result.contract_version == "v1"
