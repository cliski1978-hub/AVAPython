"""AVA-owned agent runtime data contracts.

Framework-neutral, provider-neutral, JSON-compatible contracts describing the
normalized capabilities of an agent runtime (AVA Native, OpenHands, LangGraph,
AWS AgentCore, ...). The contract never references a specific runtime;
adapters translate between their framework and these AVA-owned contracts.

Runtime capabilities are kept separate from model capabilities (see
``ava.contracts.models.ModelCapabilities``): a runtime may support tools even
when the selected model does not support tool calling. Compatibility
validation between the two is a later Phase 3 step.
"""

from pydantic import BaseModel, Field

from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Runtime Capabilities
# ============================================================


class RuntimeCapabilities(BaseModel):
    """Normalized capabilities of an agent runtime.

    A typed boolean record, not a set of framework feature names. Defaults are
    deliberately conservative: a capability is only ``True`` when the runtime
    is known to provide it. Capabilities are independent of one another;
    e.g. ``tools`` never implies ``shell`` or ``filesystem``.
    """

    tools: bool = False
    multi_agent: bool = False
    shell: bool = False
    filesystem: bool = False
    browser: bool = False
    code_execution: bool = False
    checkpointing: bool = False
    persistence: bool = False
    human_approval: bool = False
    parallel_execution: bool = False
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Runtime Capabilities
# ============================================================


# ============================================================
# BEGIN: Runtime Info
# ============================================================


class RuntimeInfo(BaseModel):
    """AVA-owned identity information for an agent runtime.

    Associating runtime identity with its capabilities. Health, provider
    configuration, installed versions, model information, routing rules, and
    registry information belong to later Phase 3 steps and are intentionally
    absent here.
    """

    runtime_id: str
    display_name: str | None = None
    capabilities: RuntimeCapabilities = Field(default_factory=RuntimeCapabilities)
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Runtime Info
# ============================================================