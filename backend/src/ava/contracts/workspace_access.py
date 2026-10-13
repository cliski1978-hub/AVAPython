"""AVA-owned, durable configuration for execution Workspaces."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ava.contracts.tools import ToolCapability
from ava.workspaces.contracts import WorkspaceKind

WorkspaceId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=128)
]


class WorkspaceAccessStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class WorkspaceAccessConfiguration(BaseModel):
    """One administrator-configured host root and its capability ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: WorkspaceId
    name: str | None = Field(default=None, strict=True, max_length=160)
    kind: WorkspaceKind
    root_path: str = Field(strict=True, min_length=1, max_length=4096)
    allowed_capabilities: tuple[ToolCapability, ...] = ()
    status: WorkspaceAccessStatus = WorkspaceAccessStatus.ACTIVE
    revision: int = Field(ge=1, strict=True)
    created_at: datetime
    updated_at: datetime
    contract_version: Literal["v1"] = Field(default="v1", frozen=True)

    @field_validator("root_path")
    @classmethod
    def absolute_root(cls, value: str) -> str:
        from pathlib import Path

        path = Path(value)
        if not path.is_absolute():
            raise ValueError("workspace root must be an absolute path")
        return value

    @model_validator(mode="after")
    def unique_capabilities(self) -> Self:
        if len(set(self.allowed_capabilities)) != len(self.allowed_capabilities):
            raise ValueError("workspace capabilities must be unique")
        return self


class CreateWorkspaceAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: WorkspaceId
    name: str | None = Field(default=None, strict=True, max_length=160)
    kind: WorkspaceKind
    root_path: str = Field(strict=True, min_length=1, max_length=4096)
    allowed_capabilities: tuple[ToolCapability, ...] = ()
    contract_version: Literal["v1"] = Field(default="v1", frozen=True)


class UpdateWorkspaceAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, strict=True, max_length=160)
    kind: WorkspaceKind
    root_path: str = Field(strict=True, min_length=1, max_length=4096)
    allowed_capabilities: tuple[ToolCapability, ...] = ()
    status: WorkspaceAccessStatus = WorkspaceAccessStatus.ACTIVE
    expected_revision: int = Field(ge=1, strict=True)
    contract_version: Literal["v1"] = Field(default="v1", frozen=True)


class WorkspaceAccessItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: WorkspaceId
    name: str | None
    kind: WorkspaceKind
    root_path: str | None
    allowed_capabilities: tuple[ToolCapability, ...]
    status: WorkspaceAccessStatus
    revision: int
    created_at: datetime
    updated_at: datetime


class WorkspaceAccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspaces: tuple[WorkspaceAccessItem, ...]
    can_manage: bool
    roots_disclosed: bool
    configuration_status: Literal["valid", "invalid"]
    contract_version: Literal["v1"] = Field(default="v1", frozen=True)


class WorkspaceAdministrationPort(Protocol):
    """Trusted server integration; client claims and role headers are ignored."""

    def can_manage(self) -> bool: ...
