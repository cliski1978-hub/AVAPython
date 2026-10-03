"""Public contracts for AVA Projects."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from ava.contracts.version import CONTRACT_VERSION


class _ProjectWriteRequest(BaseModel):
    """Shared nonblank-name validation for Project write contracts."""

    name: str
    description: str | None = None
    instructions: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        """Reject empty and whitespace-only names without normalizing them."""
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class CreateProjectRequest(_ProjectWriteRequest):
    """Request contract for creating an unarchived Project."""

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class UpdateProjectRequest(_ProjectWriteRequest):
    """Request contract for updating Project descriptive metadata."""

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class SetProjectArchivedRequest(BaseModel):
    """Archive or restore a Project independently from metadata updates."""

    is_archived: StrictBool
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ProjectResponse(BaseModel):
    """Public snapshot of a Project's domain metadata."""

    id: str
    name: str
    description: str | None = None
    instructions: str | None = None
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ProjectListResponse(BaseModel):
    """Canonical ordered Project collection response."""

    projects: list[ProjectResponse]
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class UpdateProjectExecutionDefaultsRequest(BaseModel):
    """Patch independent Project execution preferences; omitted means preserve."""

    model_config = ConfigDict(extra="forbid")

    runtime_key: str | None = None
    model_id: str | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)

    @field_validator("runtime_key", "model_id")
    @classmethod
    def references_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("reference must not be blank")
        return value


class ProjectExecutionDefaultsResponse(BaseModel):
    """Project preference snapshot without provider- or runtime-specific data."""

    project_id: str
    runtime_key: str | None
    model_id: str | None
    runtime_available: bool | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
