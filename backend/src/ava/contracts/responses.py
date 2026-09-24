"""Contract definitions for AVA responses.

Framework-neutral response DTOs. Vendor SDK objects must never appear here.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from ava.contracts.capabilities import CapabilityName
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.models import ModelInfo, ModelProviderHealth
from ava.contracts.runtimes import RuntimeInfo
from ava.contracts.version import CONTRACT_VERSION
from ava.workspaces.contracts import WorkspaceInfo

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
    execution_selection: RunExecutionSelection | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class RuntimeDiscoveryItem(BaseModel):
    is_default: bool
    runtime_info: RuntimeInfo
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class RuntimeDiscoveryResponse(BaseModel):
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
    default_runtime_id: str
    runtimes: list[RuntimeDiscoveryItem]

class ExecutionProfile(BaseModel):
    id: str
    name: str
    description: str | None = None
    runtime_id: str
    model_provider_id: str

class ExecutionProfileDiscoveryResponse(BaseModel):
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
    default_profile_id: str
    profiles: list[ExecutionProfile]


# ============================================================
# END: Runs
# ============================================================


# ============================================================
# BEGIN: Model Provider Discovery
# ============================================================


class ModelProviderDiscoveryItem(BaseModel):
    """A single discovered model provider with model identity and health.

    Reuses the existing ``ModelInfo`` and ``ModelProviderHealth`` contracts so
    discovery never invents a parallel vocabulary: the model's identity,
    capabilities, and health status are exactly what the provider's adapter
    reports through the ``ModelProviderPort``.
    """

    provider_id: str
    is_default: bool
    model_info: ModelInfo
    health: ModelProviderHealth
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ModelProviderDiscoveryResponse(BaseModel):
    """Response contract for the /model-providers endpoint.

    ``default_provider_id`` truthfully reports the configured default provider
    identity, which may or may not appear in ``providers``: an unknown or
    unregistered default is represented as-is and never fabricates an entry.
    """

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
    default_provider_id: str
    providers: list[ModelProviderDiscoveryItem]


# ============================================================
# END: Model Provider Discovery
# ============================================================


# ============================================================
# BEGIN: Model Discovery
# ============================================================


class ModelDiscoveryResponse(BaseModel):
    """Response contract for the /models endpoint.

    A read-only catalog of configured AVA models keyed by the stable
    ``model_id``. It reuses ``ModelInfo`` (Step 40) so discovery never invents a
    parallel vocabulary. Only public-safe metadata is exposed: provider identity,
    hosting placement, declared capabilities, and the enabled flag. Provider
    connection data (provider-native model name, endpoint, credential) and any
    security/permission fields are never present.
    """

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
    models: list[ModelInfo]


# ============================================================
# END: Model Discovery
# ============================================================


# ============================================================
# BEGIN: Workspace Discovery
# ============================================================


class WorkspaceDiscoveryResponse(BaseModel):
    """Response contract for the /workspaces endpoint.

    Reuses ``WorkspaceInfo`` (AVA-owned public-safe metadata: workspace id,
    display name, and kind) as the discovery item so discovery never invents
    a parallel vocabulary. Internal policy results (``ResolvedWorkspace``) and
    runtime execution dependencies (``RuntimeWorkspaceBinding``) — including any
    host filesystem path — never appear in this contract.
    """

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
    workspaces: list[WorkspaceInfo]


# ============================================================
# END: Workspace Discovery
# ============================================================
