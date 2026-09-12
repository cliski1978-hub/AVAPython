"""Capability service.

Reports which AVA capabilities currently exist. Only implemented capability
names are reported as true. This service is the single source of truth for
the /capabilities endpoint.
"""

from ava.contracts.capabilities import CapabilityName
from ava.contracts.responses import CapabilitiesResponse

# ============================================================
# BEGIN: Capability Service
# ============================================================


class CapabilityService:
    """Provides the current AVA capability snapshot."""

    def __init__(self, *, application: str) -> None:
        """Construct the capability service.

        Args:
            application: The application name reported in the response. The
                composition root supplies this from the configured
                Application root; the service maintains no separate default.
        """
        self._application = application

    def get_capabilities(self) -> CapabilitiesResponse:
        """Return the current capability snapshot.

        Every known capability name is reported, with only implemented
        capabilities set to true. Adding a capability name to the contract
        does not flip it to true here.
        """
        capabilities: dict[CapabilityName, bool] = {
            capability: False for capability in CapabilityName
        }
        capabilities[CapabilityName.HEALTH] = True
        return CapabilitiesResponse(
            application=self._application,
            capabilities=capabilities,
        )


# ============================================================
# END: Capability Service
# ============================================================