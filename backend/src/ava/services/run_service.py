"""Run service.

Coordinates a single agent run across the agent port. In this sprint the
service is intentionally thin: it generates the AVA-owned run identifier,
maps an AVA RunRequest to the configured agent adapter, and returns an AVA
RunResponse.
"""

from uuid import uuid4

from ava.agents.contracts import AgentPort
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse

# ============================================================
# BEGIN: Run Service
# ============================================================


class RunService:
    """Coordinates a single agent run across the agent port."""

    def __init__(self, agent: AgentPort) -> None:
        """Construct the run service with an agent adapter."""
        self._agent = agent

    async def start_run(self, request: RunRequest) -> RunResponse:
        """Start a run, generating the AVA-owned run identifier.

        Run identifiers are owned and created by AVA, never by the client or
        the agent adapter. No persistence is introduced in this sprint.
        """
        run_id = str(uuid4())
        return await self._agent.start_run(run_id=run_id, request=request)

    async def cancel_run(self, run_id: str) -> RunResponse:
        """Cancel a run against the configured agent adapter."""
        return await self._agent.cancel_run(run_id)


# ============================================================
# END: Run Service
# ============================================================