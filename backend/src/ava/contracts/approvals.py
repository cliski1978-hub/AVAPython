"""Runtime-neutral contracts for durable human approvals."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ava.contracts.tools import ToolIdentifier, ToolOperationBinding, ToolReference, ToolRequest

ApprovalSummary = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=240)]


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"


class ApprovalReason(StrEnum):
    HUMAN_APPROVED = "human_approved"
    HUMAN_DENIED = "human_denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    RUN_CANCELLED = "run_cancelled"
    WORKSPACE_REVOKED_OR_CHANGED = "workspace_revoked_or_changed"
    POLICY_OR_AUTHORITY_CHANGED = "policy_or_authority_changed"
    OPERATION_CHANGED = "operation_changed"
    ELIGIBILITY_UNAVAILABLE = "eligibility_unavailable"


class ApprovalDecisionValue(StrEnum):
    APPROVE = "approve"
    DENY = "deny"


class ApprovalRequest(BaseModel):
    """Untrusted invocation submitted for server-side policy evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: ToolReference
    tool_request: ToolRequest


class ApprovalDecision(BaseModel):
    """Human choice only; identity is resolved from a trusted server adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: ApprovalDecisionValue
    reason: str | None = Field(default=None, max_length=500)


class ApprovalDecisionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: ApprovalDecisionValue
    principal_ref: ToolReference
    authority_revision_ref: ToolReference
    decided_at: datetime
    reason: str | None = Field(default=None, max_length=500)


class ApprovalRecord(BaseModel):
    """Persisted approval facts; deliberately contains no operation arguments or root path."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    approval_id: ToolReference
    run_id: ToolReference
    invocation_id: ToolReference
    tool_id: ToolIdentifier
    tool_version: ToolReference
    operation_binding: ToolOperationBinding
    status: ApprovalStatus
    requested_at: datetime
    expires_at: datetime
    summary: ApprovalSummary
    policy_version: ToolReference
    feature_configuration_version: int = Field(ge=0, strict=True)
    workspace_id: ToolReference
    workspace_authorization_ref: ToolReference
    workspace_configuration_revision: int = Field(ge=0, strict=True)
    authority_revision_ref: ToolReference
    decision_metadata: ApprovalDecisionMetadata | None = None
    resolution_reason: ApprovalReason | None = None
    contract_version: Literal["v1"] = "v1"

    def model_post_init(self, __context: object) -> None:
        if self.requested_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("approval timestamps must be timezone-aware")
        if self.expires_at <= self.requested_at:
            raise ValueError("approval expiry must be after request time")
        if self.decision_metadata is not None and self.decision_metadata.decided_at.tzinfo is None:
            raise ValueError("approval decision timestamp must be timezone-aware")
        if self.operation_binding.invocation_id != self.invocation_id:
            raise ValueError("approval must match its invocation binding")
        if self.operation_binding.tool_id != self.tool_id or self.operation_binding.tool_version != self.tool_version:
            raise ValueError("approval must match its tool binding")
        if self.status == ApprovalStatus.PENDING:
            if self.decision_metadata is not None or self.resolution_reason is not None:
                raise ValueError("pending approval cannot have resolution metadata")
        elif self.status in {ApprovalStatus.APPROVED, ApprovalStatus.DENIED}:
            expected = (
                ApprovalDecisionValue.APPROVE if self.status == ApprovalStatus.APPROVED else ApprovalDecisionValue.DENY
            )
            if self.decision_metadata is None or self.decision_metadata.decision != expected:
                raise ValueError("human-resolved approval requires matching decision metadata")
            if self.resolution_reason is not None:
                raise ValueError("human decision cannot have a system resolution reason")
        elif self.decision_metadata is not None or self.resolution_reason is None:
            raise ValueError("non-human resolution requires a reason and no decision metadata")


@dataclass(frozen=True)
class ApprovalHumanAuthority:
    """Trusted identity and current approval scope supplied by server auth."""

    principal_ref: str
    authority_revision_ref: str
    workspace_ids: frozenset[str]
    can_decide: bool


class ApprovalDecisionAuthorityPort(Protocol):
    def resolve_for(self, approval: ApprovalRecord) -> ApprovalHumanAuthority | None:
        """Resolve the authenticated human and current scope; never accept client identity."""
        ...


class ApprovalInvocationResolverPort(Protocol):
    def resolve_current_request(self, invocation_id: str) -> ToolRequest | None:
        """Resolve the current AVA invocation without trusting caller arguments."""
        ...


class DenyApprovalDecisionAuthority:
    def resolve_for(self, approval: ApprovalRecord) -> ApprovalHumanAuthority | None:
        return None
