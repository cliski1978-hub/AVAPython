"""Capability service.

Reports which AVA capabilities currently exist. The application always
supports health; the remaining capabilities are derived truthfully from the
configured agent adapter's own capability report. This service is the single
source of truth for the /capabilities endpoint.
"""

from ava.agents.contracts import AgentPort
from ava.contracts.capabilities import CapabilityName
from ava.contracts.responses import CapabilitiesResponse

# ============================================================
# BEGIN: Capability Service
# ============================================================


class CapabilityService:
    """Provides the current AVA capability snapshot."""

    def __init__(self, *, application: str, agent: AgentPort) -> None:
        """Construct the capability service.

        Args:
            application: The application name reported in the response. The
                composition root supplies this from the configured
                Application root; the service maintains no separate default.
            agent: The configured agent adapter (an ``AgentPort``). Its
                truthful capability report feeds the public snapshot.
        """
        self._application = application
        self._agent = agent

    def get_capabilities(self) -> CapabilitiesResponse:
        """Return the current capability snapshot.

        Health is always reported as supported. Every other capability is
        reported exactly as the configured agent advertises it: nothing is
        hard-coded here, so capability truthfulness follows the agent.
        """
        capabilities: dict[CapabilityName, bool] = {
            capability: False for capability in CapabilityName
        }
        capabilities[CapabilityName.HEALTH] = True
        for capability in self._agent.get_capabilities():
            capabilities[capability] = True
        return CapabilitiesResponse(
            application=self._application,
            capabilities=capabilities,
        )


# ============================================================
# END: Capability Service
# ============================================================