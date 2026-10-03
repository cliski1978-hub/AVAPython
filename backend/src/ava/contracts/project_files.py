"""Public, storage-neutral contracts for Project file metadata."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ava.contracts.version import CONTRACT_VERSION


class CreateProjectFileRequest(BaseModel):
    """Metadata submitted with a future upload transport; bytes travel separately."""

    model_config = ConfigDict(extra="forbid")

    file_name: str
    content_type: str | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)

    @field_validator("file_name")
    @classmethod
    def file_name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("file_name must not be blank")
        return value

    @field_validator("content_type")
    @classmethod
    def content_type_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("content_type must not be blank when provided")
        return value


class ProjectFileResponse(BaseModel):
    """Safe Project file metadata; opaque content references stay internal."""

    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    file_name: str
    content_type: str | None
    size_bytes: int = Field(ge=0, strict=True)
    created_at: datetime
    updated_at: datetime
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class ProjectFileListResponse(BaseModel):
    """Metadata-only collection scoped to one owning Project."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    files: list[ProjectFileResponse]
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
