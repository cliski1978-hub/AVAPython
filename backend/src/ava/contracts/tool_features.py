"""Feature configuration values; availability never grants execution authority."""

from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ava.contracts.tools import ToolDefinition, ToolIdentifier


class ToolFeatureConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    framework_enabled: bool = Field(default=False, strict=True)
    enabled_tool_ids: tuple[ToolIdentifier, ...] = ()
    configuration_version: int = Field(default=0, ge=0, strict=True)
    contract_version: Literal["v1"] = Field(default="v1", frozen=True)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len(set(self.enabled_tool_ids)) != len(self.enabled_tool_ids):
            raise ValueError("enabled tool IDs must be unique")
        if self.configuration_version == 0 and (self.framework_enabled or self.enabled_tool_ids):
            raise ValueError("unconfigured version 0 cannot enable features")
        return self


class UpdateToolFeaturesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    framework_enabled: bool = Field(strict=True)
    enabled_tool_ids: tuple[ToolIdentifier, ...]
    expected_version: int = Field(ge=0, strict=True)
    contract_version: Literal["v1"] = Field(default="v1", frozen=True)


class ToolFeatureAvailability(BaseModel):
    definition: ToolDefinition
    configured_enabled: bool
    effective_enabled: bool
    reason: Literal["configuration_invalid", "framework_disabled", "tool_disabled", "feature_enabled"]


class ToolFeaturesResponse(BaseModel):
    configuration: ToolFeatureConfiguration
    configuration_status: Literal["missing", "valid", "invalid"]
    framework_effective_enabled: bool
    can_manage: bool
    tools: list[ToolFeatureAvailability]
    contract_version: Literal["v1"] = Field(default="v1", frozen=True)


class ToolFeatureAdministrationPort(Protocol):
    """Trusted deployment integration, never client claims or role headers.

    Must be backed by authenticated, request-scoped administrative authority
    or a deployment restriction that excludes untrusted network callers.
    No allowing implementation ships in AVA until that boundary exists.
    """

    def can_manage(self) -> bool: ...
