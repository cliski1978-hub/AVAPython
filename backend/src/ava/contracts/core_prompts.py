"""Public contracts for reusable AVA CORE system prompt definitions."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from ava.contracts.capabilities import CapabilityName
from ava.contracts.version import CONTRACT_VERSION
from ava.repositories.core_prompt import CorePromptCategory
from ava.repositories.core_prompt_assignment import CorePromptAssignmentMode, CorePromptScopeType


class _CorePromptWriteRequest(BaseModel):
    """Shared validation for mutable prompt-definition fields."""

    name: str
    description: str | None = None
    prompt_text: str
    category: CorePromptCategory

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        """Reject whitespace-only names without normalizing user input."""
        if not value.strip():
            raise ValueError("name must not be blank")
        return value

    @field_validator("prompt_text")
    @classmethod
    def prompt_text_must_not_be_blank(cls, value: str) -> str:
        """Require content while preserving all meaningful whitespace."""
        if not value.strip():
            raise ValueError("prompt_text must not be blank")
        return value


class CreateCorePromptRequest(_CorePromptWriteRequest):
    """Request contract for creating an enabled CORE prompt definition."""

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class SetCorePromptEnabledRequest(BaseModel):
    """Dedicated mutation for the definition's availability state."""

    is_enabled: StrictBool
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class UpdateCorePromptRequest(_CorePromptWriteRequest):
    """Request contract for updating prompt metadata and content.

    ``name`` is required like Project updates. Optional ``description`` keeps
    omitted-versus-null semantics through Pydantic's ``model_fields_set``.
    """

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class CorePromptResponse(BaseModel):
    """Public snapshot of a reusable CORE prompt definition."""

    id: str
    name: str
    description: str | None
    prompt_text: str
    category: CorePromptCategory
    is_enabled: StrictBool
    created_at: datetime
    updated_at: datetime
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class CorePromptListResponse(BaseModel):
    """Deterministically ordered CORE prompt definition collection."""

    core_prompts: list[CorePromptResponse]
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class SetCorePromptAssignmentRequest(BaseModel):
    scope_type: CorePromptScopeType
    scope_id: str | None = None
    state: str
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)

    @field_validator("state")
    @classmethod
    def valid_control_state(cls, value: str) -> str:
        if value not in {"inherit", CorePromptAssignmentMode.ENABLE.value, CorePromptAssignmentMode.DISABLE.value}:
            raise ValueError("state must be inherit, enable, or disable")
        return value


class CorePromptAssignmentResponse(BaseModel):
    core_prompt_id: str
    scope_type: CorePromptScopeType
    scope_id: str | None
    state: str
    assignment_id: str | None
    created_at: datetime | None
    updated_at: datetime | None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class CorePromptAssignmentListResponse(BaseModel):
    assignments: list[CorePromptAssignmentResponse]
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ResolveCorePromptsRequest(BaseModel):
    """Read-only preview context; conversation membership is derived server-side."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    runtime_key: str | None = None
    capabilities: list[CapabilityName] = Field(default_factory=list)
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class PromptResolutionContextResponse(BaseModel):
    conversation_id: str | None
    project_id: str | None
    folder_id: str | None
    runtime_key: str | None
    capabilities: list[str]


class ResolvedCorePromptResponse(BaseModel):
    core_prompt_id: str
    name: str
    category: CorePromptCategory
    prompt_text: str
    effective_state: str
    definition_enabled: StrictBool
    reason: str
    winning_scope_type: CorePromptScopeType | None
    winning_scope_id: str | None
    winning_assignment_mode: CorePromptAssignmentMode | None
    winning_assignment_id: str | None


class EffectivePromptSetResponse(BaseModel):
    context: PromptResolutionContextResponse
    enabled_prompts: list[ResolvedCorePromptResponse]
    excluded_prompts: list[ResolvedCorePromptResponse]
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
