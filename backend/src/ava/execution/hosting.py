"""Runtime-neutral model placement policy for a run.

Step 39 separates two ideas:

- a **model hosting mode** (``ModelHostingMode``) — where a configured model
  deployment actually runs; and
- a **hosting requirement** (``ModelHostingRequirement``) — which hosting modes
  a given execution is allowed to use.

Both are data/placement policy, not workspace security. They never grant file,
shell, network, or sandbox authority; Step 36 remains authoritative for those.
There is intentionally no routing or scoring here: the requirement is a hard
filter that produces "not allowed" or "no opinion", and nothing more.
"""

from dataclasses import dataclass
from enum import StrEnum

from ava.contracts.models import ModelHostingMode

# ============================================================
# BEGIN: Hosting Requirement
# ============================================================


@dataclass(frozen=True)
class ModelHostingRequirement:
    """The set of model hosting modes an execution is permitted to use.

    A hard, server-owned placement filter evaluated *before* provider
    invocation. It expresses data-location constraints (for example "this run
    may only use local inference"); it does not express workspace permissions,
    model quality, or routing preference.
    """

    allowed_modes: frozenset[ModelHostingMode]

    def __post_init__(self) -> None:
        if not self.allowed_modes:
            raise ValueError("allowed_modes must contain at least one hosting mode")

    @classmethod
    def local_only(cls) -> "ModelHostingRequirement":
        """Require inference to run on the local machine."""
        return cls(frozenset({ModelHostingMode.LOCAL}))

    def permits(self, hosting_mode: ModelHostingMode) -> bool:
        """Return whether ``hosting_mode`` is allowed by this requirement."""
        return hosting_mode in self.allowed_modes


# ============================================================
# END: Hosting Requirement
# ============================================================


# ============================================================
# BEGIN: Hosting Reason Codes
# ============================================================


class HostingReason(StrEnum):
    """Stable internal reason codes for hosting compatibility decisions.

    These are structured reasons for logs/tests, not a public error contract.
    The public run outcome stays the existing sanitized failure message.
    """

    MODE_NOT_ALLOWED = "hosting_mode_not_allowed"
    CLASSIFICATION_UNAVAILABLE = "hosting_classification_unavailable"


# ============================================================
# END: Hosting Reason Codes
# ============================================================
