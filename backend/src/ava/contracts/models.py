"""AVA-owned model provider data contracts.

Framework-neutral, provider-neutral, JSON-compatible contracts for model
request/response and provider metadata. Provider adapters translate between
their SDK types and these AVA-owned contracts; provider SDK types must never
escape adapters.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

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
# BEGIN: Model Info
# ============================================================


class ModelInfo(BaseModel):
    """AVA-owned identity information for a provider's model."""

    provider_name: str
    model_id: str
    display_name: str | None = None
    context_limit: int | None = None
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