"""Contract definitions for AVA capability names.

Framework-neutral capability descriptors. Vendor SDK objects must never
appear here.

The presence of a capability name does not imply the capability is
implemented. Capacity discovery flips these to true as functionality lands.
"""

from enum import StrEnum

# ============================================================
# BEGIN: Capability Names
# ============================================================


class CapabilityName(StrEnum):
    """Known AVA capability names."""

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


# ============================================================
# END: Capability Names
# ============================================================