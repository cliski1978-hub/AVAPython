"""Principal-scoped access grants over configured execution Workspaces."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ava.contracts.security_identity import VerifiedPrincipal
from ava.contracts.tools import ToolCapability
from ava.contracts.workspace_access import WorkspaceId

GrantId = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{32}$", max_length=32)]
PrincipalRef = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$", max_length=64)]


class WorkspaceGrantStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class WorkspaceGrant(BaseModel):
    """Durable authorization grant, independent from Workspace configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_id: GrantId
    workspace_id: WorkspaceId
    principal_ref: PrincipalRef
    tenant_ref: str | None = Field(default=None, strict=True, min_length=1, max_length=512)
    run_id: str | None = Field(default=None, strict=True, min_length=1, max_length=256)
    capabilities: tuple[ToolCapability, ...]
    workspace_configuration_revision: int = Field(ge=1, strict=True)
    status: WorkspaceGrantStatus
    revision: int = Field(ge=1, strict=True)
    created_at: datetime
    updated_at: datetime
    contract_version: Literal["v1"] = Field(default="v1", frozen=True)

    @field_validator("created_at", "updated_at")
    @classmethod
    def aware_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("grant timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def unique_capabilities(self) -> Self:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("grant capabilities must be unique")
        if self.updated_at < self.created_at:
            raise ValueError("grant update time cannot precede creation")
        return self


class CreateWorkspaceGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_ref: PrincipalRef
    tenant_ref: str | None = Field(default=None, strict=True, min_length=1, max_length=512)
    run_id: str | None = Field(default=None, strict=True, min_length=1, max_length=256)
    capabilities: tuple[ToolCapability, ...]
    expected_workspace_revision: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def unique_capabilities(self) -> Self:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("grant capabilities must be unique")
        return self


class UpdateWorkspaceGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capabilities: tuple[ToolCapability, ...]
    expected_revision: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def unique_capabilities(self) -> Self:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("grant capabilities must be unique")
        return self


class WorkspaceGrantItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_id: GrantId
    workspace_id: WorkspaceId
    principal_ref: PrincipalRef
    tenant_ref: str | None
    run_id: str | None
    capabilities: tuple[ToolCapability, ...]
    workspace_configuration_revision: int
    status: WorkspaceGrantStatus
    revision: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_grant(cls, grant: WorkspaceGrant) -> "WorkspaceGrantItem":
        return cls.model_validate(grant.model_dump(exclude={"contract_version"}))


class WorkspaceGrantAdministrationPort(Protocol):
    """Separate trusted authority for grant provisioning and revocation."""

    def can_manage(
        self,
        principal: VerifiedPrincipal,
        *,
        workspace_id: str,
        action: str,
    ) -> bool:
        """Authorize one administration action for this verified principal."""
        ...


class DenyWorkspaceGrantAdministration:
    """No grant changes are available until a trusted admin adapter is injected."""

    def can_manage(
        self,
        principal: VerifiedPrincipal,
        *,
        workspace_id: str,
        action: str,
    ) -> bool:
        del principal, workspace_id, action
        return False
