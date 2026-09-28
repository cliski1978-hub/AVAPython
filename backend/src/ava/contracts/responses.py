"""Contract definitions for AVA responses.

Framework-neutral response DTOs. Vendor SDK objects must never appear here.
"""

from datetime import datetime
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
    """The authoritative lifecycle status of an AVA run.

    This enum *is* the run lifecycle state machine's vocabulary, and it is the
    single source of the active/terminal classification every backend layer
    asks about. The allowed transitions between these values are policy and live
    with the transition authority (``ava.services.run_lifecycle_service``), not
    here: this type answers "is this state final?", never "may this state move?".

    ``WAITING_FOR_APPROVAL`` is declared and projected but has no production
    writer today; see ``docs/AVA_Phase_5_23_Run_Lifecycle_Normalization.md``.
    It is kept because it is part of the published vocabulary and an approvals
    flow is anticipated, not because a run can currently reach it.
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Whether this status is a final state no run may leave.

        Terminal means the run produced its outcome. It does not mean the run
        succeeded: ``failed`` and ``cancelled`` are terminal outcomes too.
        """
        return self in TERMINAL_RUN_STATUSES

    @property
    def is_active(self) -> bool:
        """Whether a run in this status is still in progress.

        The exact complement of :attr:`is_terminal`, so the two can never
        disagree and no caller has to keep its own copy of the list.
        """
        return self in ACTIVE_RUN_STATUSES


#: The one canonical definition of a finished run, shared by the run service,
#: the lifecycle authority, conversation reads, and lifecycle tests.
TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED}
)

#: The one canonical definition of an in-progress run. ``waiting_for_approval``
#: counts as active: an approval-gated run has started and still owes an
#: outcome.
ACTIVE_RUN_STATUSES: frozenset[RunStatus] = frozenset(RunStatus) - TERMINAL_RUN_STATUSES


class RunResponse(BaseModel):
    """Response contract describing the state of a run.

    ``cancellation_requested_at`` is durable *intent*: the moment a user asked
    for this run to stop. It is deliberately not a status and deliberately not
    proof of cancellation. A run reported as ``running`` with a request
    timestamp is a run whose cancellation has not settled yet — the request
    survived, the outcome is still open. Only ``status == cancelled`` means the
    run actually stopped.
    """

    run_id: str
    status: RunStatus
    conversation_id: str | None = None
    source_user_message_id: str | None = None
    assistant_message_id: str | None = None
    execution_selection: RunExecutionSelection | None = None
    cancellation_requested_at: datetime | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)

    @property
    def cancellation_requested(self) -> bool:
        """Whether a cancellation request was recorded for this run.

        Derived from the timestamp rather than stored beside it, so the two can
        never disagree and a client never has to decide which one is real.
        """
        return self.cancellation_requested_at is not None


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
