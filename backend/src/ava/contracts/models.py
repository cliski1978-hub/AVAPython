"""AVA-owned model provider data contracts.

Framework-neutral, provider-neutral, JSON-compatible contracts for model
request/response and provider metadata. Provider adapters translate between
their SDK types and these AVA-owned contracts; provider SDK types must never
escape adapters.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Model Provider Health
# ============================================================


class ModelProviderHealthStatus(StrEnum):
    """Normalized model provider health status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    MODEL_NOT_LOADED = "model_not_loaded"
    AUTHENTICATION_FAILED = "authentication_failed"
    CONFIGURATION_INVALID = "configuration_invalid"


class ModelProviderHealth(BaseModel):
    """Structured health report for a model provider.

    `available` is the coarse usable flag; `status` carries the normalized
    reason, and `message` may hold a human-readable explanation. A boolean
    alone cannot distinguish degraded, not-loaded, or misconfigured states.
    """

    available: bool
    status: ModelProviderHealthStatus
    message: str | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Model Provider Health
# ============================================================


# ============================================================
# BEGIN: Model Capabilities
# ============================================================


class ModelCapabilities(BaseModel):
    """Provider-neutral capabilities of a model.

    A typed boolean record, not a set of vendor feature names. Defaults are
    deliberately conservative: a capability is only ``True`` when the model is
    known to support it. Providers populate this through adapters; AVA core
    consumes it to answer "what can this model do?" without knowing which
    provider hosts it.
    """

    chat: bool = False
    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    vision: bool = False
    embeddings: bool = False
    reasoning: bool = False
    code_specialization: bool = False
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
    model_config = ConfigDict(frozen=True)


# ============================================================
# END: Model Capabilities
# ============================================================


# ============================================================
# BEGIN: Model Hosting Mode
# ============================================================


class ModelHostingMode(StrEnum):
    """Where inference for a configured model deployment actually executes.

    Server-owned, declarative deployment metadata — never inferred from a
    provider id, provider name, protocol, or endpoint. It describes placement
    only; it is not a capability, permission, routing score, availability
    state, or resource-residency state.

    - ``LOCAL``: inference runs on the user's / local AVA-controlled machine.
    - ``COMPANY_HOSTED``: inference runs on company-operated/approved
      infrastructure reached through a company-controlled gateway.
    - ``EXTERNAL``: inference runs through an external third-party service.

    ``LOCAL`` does **not** imply a trusted model, a loaded/resident model, or
    any workspace, file, shell, network, or sandbox permission.
    """

    LOCAL = "local"
    COMPANY_HOSTED = "company_hosted"
    EXTERNAL = "external"


# ============================================================
# END: Model Hosting Mode
# ============================================================


# ============================================================
# BEGIN: Model Info
# ============================================================


class QualificationStatus(StrEnum):
    """Closed outcome vocabulary for a measured model qualification."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    NOT_TESTED = "not_tested"


class ModelQualificationInfo(BaseModel):
    """Public-safe measured evidence, never a capability or permission grant."""

    qualification_id: str
    status: QualificationStatus
    runtime_id: str | None = None
    task_class: str
    evidence_summary: str | None = None
    measured_at: datetime | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ModelInfo(BaseModel):
    """AVA-owned public-safe identity information for a model.

    Serves two consumers without a parallel vocabulary: provider discovery
    (``provider_name`` + provider-reported capabilities) and the read-only model
    catalog (``provider_id``, ``hosting_mode``, and ``enabled`` populated from a
    ``ModelProfile``). The provider-native model name is deliberately absent —
    it stays internal to deployment composition.
    """

    provider_name: str
    model_id: str
    display_name: str | None = None
    context_limit: int | None = None
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    provider_id: str | None = None
    hosting_mode: ModelHostingMode | None = None
    enabled: bool | None = None
    qualifications: list[ModelQualificationInfo] = Field(default_factory=list)
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Model Info
# ============================================================


# ============================================================
# BEGIN: Model Message
# ============================================================


class ModelMessage(BaseModel):
    """A single message exchanged with a model."""

    role: str
    content: str


# ============================================================
# END: Model Message
# ============================================================


# ============================================================
# BEGIN: Model Request
# ============================================================


class ModelRequest(BaseModel):
    """AVA-owned request contract for model generation.

    Deliberately minimal for Sprint 1. Tools, structured output, usage, and
    metadata will be added through additive contract changes.
    """

    messages: list[ModelMessage]
    temperature: float | None = None
    max_output_tokens: int | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Model Request
# ============================================================


# ============================================================
# BEGIN: Model Response
# ============================================================


class ModelResponse(BaseModel):
    """AVA-owned response contract for model generation."""

    content: str
    model_id: str
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Model Response
# ============================================================
