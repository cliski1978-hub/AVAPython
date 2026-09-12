"""Client models for the AVA API."""

from enum import StrEnum

from pydantic import BaseModel


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
