"""Runtime-neutral preflight decisions, never executable authorization tokens."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ava.contracts.tools import ToolIdentifier, ToolOperationBinding, ToolReference, ToolRequest


class ToolPolicyDecisionType(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRES_APPROVAL = "requires_approval"


class ToolPolicyReason(StrEnum):
    ALLOWED = "allowed"
    APPROVAL_REQUIRED = "approval_required"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN_TOOL = "unknown_tool"
    VERSION_MISMATCH = "tool_version_mismatch"
    FEATURE_DISABLED = "feature_disabled"
    CONFIGURATION_INVALID = "configuration_invalid"
    CONFIGURATION_CHANGED = "configuration_changed"
    OPERATION_UNSUPPORTED = "operation_unsupported"
    INVALID_ARGUMENTS = "invalid_arguments"
    AUTHORITY_MISSING = "authority_missing"
    AUTHORITY_INVALID = "authority_invalid"
    AUTHORITY_REVOKED = "authority_revoked"
    AUTHORITY_CHANGED = "authority_changed"
    TOOL_NOT_AUTHORIZED = "tool_not_authorized"
    CAPABILITY_DENIED = "capability_denied"
    RUNTIME_UNSUPPORTED = "runtime_unsupported"
    WORKSPACE_UNAVAILABLE = "workspace_unavailable"
    WORKSPACE_DENIED = "workspace_denied"
    WORKSPACE_CHANGED = "workspace_changed"
    PATH_OUTSIDE_WORKSPACE = "path_outside_workspace"
    RESOURCE_UNSUPPORTED = "resource_unsupported"
    NETWORK_UNSUPPORTED = "network_unsupported"
    COMMAND_UNAVAILABLE = "command_unavailable"
    COMMAND_POLICY_DENIED = "command_policy_denied"
    COMMAND_POLICY_INSUFFICIENT = "command_policy_insufficient"


class ToolPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: ToolRequest
    contract_version: Literal["v1"] = "v1"


class ToolPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invocation_id: ToolReference | None = None
    tool_id: ToolIdentifier | None = None
    decision: ToolPolicyDecisionType
    reason: ToolPolicyReason
    explanation: str = Field(min_length=1)
    approval_required: bool = False
    configuration_version: int | None = Field(default=None, ge=0, strict=True)
    policy_version: ToolReference
    operation_binding: ToolOperationBinding | None = None
    requires_execution_revalidation: Literal[True] = True
    execution_authorized: Literal[False] = False
    contract_version: Literal["v1"] = "v1"

    @model_validator(mode="after")
    def consistent_decision(self) -> Self:
        if self.decision == ToolPolicyDecisionType.ALLOW and self.reason != ToolPolicyReason.ALLOWED:
            raise ValueError("allow requires allowed reason")
        if self.decision == ToolPolicyDecisionType.DENY and self.reason in {
            ToolPolicyReason.ALLOWED,
            ToolPolicyReason.APPROVAL_REQUIRED,
        }:
            raise ValueError("deny requires a denial reason")
        if self.decision == ToolPolicyDecisionType.REQUIRES_APPROVAL:
            if not self.approval_required or self.reason != ToolPolicyReason.APPROVAL_REQUIRED:
                raise ValueError("approval decision requires approval metadata")
        elif self.approval_required:
            raise ValueError("only requires_approval has pending approval metadata")
        if self.decision != ToolPolicyDecisionType.DENY:
            if self.operation_binding is None or self.invocation_id is None or self.tool_id is None:
                raise ValueError("eligible decision requires an operation binding and identities")
            if (
                self.operation_binding.invocation_id != self.invocation_id
                or self.operation_binding.tool_id != self.tool_id
            ):
                raise ValueError("decision identity must match operation binding")
        return self
