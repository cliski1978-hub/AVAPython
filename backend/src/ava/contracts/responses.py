"""Contract definitions for AVA responses.

Framework-neutral response DTOs. Vendor SDK objects must never appear here.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from ava.contracts.capabilities import CapabilityName
from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Health
# ============================================================


class HealthStatus(StrEnum):
    """Health status of the AVA application."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class HealthResponse(BaseModel):
    """Response contract for the /health endpoint."""

    status: HealthStatus
    application: str
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Health
# ============================================================


# ============================================================
# BEGIN: Capabilities
# ============================================================


class CapabilitiesResponse(BaseModel):
    """Response contract for the /capabilities endpoint.

    Reports only capabilities that currently exist. The presence of a
    capability name in this contract does not imply it is implemented.
    """

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
    application: str
    capabilities: dict[CapabilityName, bool]


# ============================================================
# END: Capabilities
# ============================================================


# ============================================================
# BEGIN: Runs
# ============================================================


class RunStatus(StrEnum):
    """Run status values for AVA runs."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RunResponse(BaseModel):
    """Response contract describing the state of a run."""

    run_id: str
    status: RunStatus
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Runs
# ============================================================