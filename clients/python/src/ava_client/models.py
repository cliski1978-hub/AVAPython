"""Client models for the AVA API."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class HealthStatus(StrEnum):
    """Health status values returned by the AVA API."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class HealthResponse(BaseModel):
    """Response contract for the /health endpoint."""

    status: HealthStatus
    application: str
    contract_version: str


class CapabilityName(StrEnum):
    """Known capability names reported by the AVA API."""

    HEALTH = "health"
    RUNS = "runs"
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    STRUCTURED_OUTPUT = "structured_output"
    CANCELLATION = "cancellation"
    DOCUMENT_OPERATIONS = "document_operations"
    APPROVALS = "approvals"
    LOCAL_MODEL = "local_model"
    LOCAL_EXECUTION = "local_execution"


class CapabilitiesResponse(BaseModel):
    """Response contract for the /capabilities endpoint."""

    contract_version: str
    application: str
    capabilities: dict[CapabilityName, bool]


class ModelProviderHealthStatus(StrEnum):
    """Normalized model provider health status values returned by the AVA API."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    MODEL_NOT_LOADED = "model_not_loaded"
    AUTHENTICATION_FAILED = "authentication_failed"
    CONFIGURATION_INVALID = "configuration_invalid"


class ModelProviderHealth(BaseModel):
    """Structured health report for a model provider."""

    available: bool
    status: ModelProviderHealthStatus
    message: str | None = None
    contract_version: str


class ModelCapabilities(BaseModel):
    """Provider-neutral capabilities of a model."""

    chat: bool = False
    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    vision: bool = False
    embeddings: bool = False
    reasoning: bool = False
    code_specialization: bool = False
    contract_version: str


class ModelHostingMode(StrEnum):
    """Server-owned inference placement classification."""

    LOCAL = "local"
    COMPANY_HOSTED = "company_hosted"
    EXTERNAL = "external"


class QualificationStatus(StrEnum):
    """Measured qualification outcome values returned by the AVA API."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    NOT_TESTED = "not_tested"


class ModelQualificationInfo(BaseModel):
    """Public-safe measured qualification metadata for one model."""

    qualification_id: str
    status: QualificationStatus
    runtime_id: str | None = None
    task_class: str
    evidence_summary: str | None = None
    measured_at: datetime | None = None
    contract_version: str


class ModelInfo(BaseModel):
    """Public-safe AVA model metadata used by provider and catalog discovery."""

    provider_name: str
    model_id: str
    display_name: str | None = None
    context_limit: int | None = None
    capabilities: ModelCapabilities
    provider_id: str | None = None
    hosting_mode: ModelHostingMode | None = None
    enabled: bool | None = None
    qualifications: list[ModelQualificationInfo] = Field(default_factory=list)
    contract_version: str


class ModelDiscoveryResponse(BaseModel):
    """Response contract for the read-only ``/models`` catalog."""

    contract_version: str
    models: list[ModelInfo]


class ModelProviderDiscoveryItem(BaseModel):
    """A discovered model provider with model identity and health."""

    provider_id: str
    is_default: bool
    model_info: ModelInfo
    health: ModelProviderHealth
    contract_version: str


class ModelProviderDiscoveryResponse(BaseModel):
    """Response contract for the /model-providers endpoint."""

    contract_version: str
    default_provider_id: str
    providers: list[ModelProviderDiscoveryItem]


class WorkspaceKind(StrEnum):
    """Kind of an AVA workspace as reported by the /workspaces endpoint."""

    LOCAL = "local"
    EPHEMERAL = "ephemeral"


class WorkspaceInfo(BaseModel):
    """Safe public metadata for an AVA-approved workspace.

    Mirrors the backend ``WorkspaceInfo`` (id, display name, kind). Host
    filesystem paths and internal security details are never part of this
    contract.
    """

    workspace_id: str
    display_name: str
    kind: WorkspaceKind


class WorkspaceDiscoveryResponse(BaseModel):
    """Response contract for the /workspaces endpoint."""

    contract_version: str
    workspaces: list[WorkspaceInfo]


class RunExecutionSelection(BaseModel):
    """Stable execution identities returned with a run."""

    runtime_id: str | None = None
    model_provider_id: str | None = None
    model_id: str | None = None
    hosting_mode: str | None = None
    contract_version: str


class RunResponse(BaseModel):
    """Run lifecycle response."""

    run_id: str
    status: str
    contract_version: str
    execution_selection: RunExecutionSelection | None = None


class RunExecutionOverride(BaseModel):
    runtime_id: str | None = None
    model_id: str | None = None
    model_provider_id: str | None = None


class RunRequest(BaseModel):
    prompt: str
    execution: RunExecutionOverride | None = None
