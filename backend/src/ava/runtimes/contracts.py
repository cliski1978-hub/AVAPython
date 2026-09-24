"""Framework-neutral runtime boundary, independent of agent implementations.

Agent runtime selection and model-provider selection are independent axes.
The selected model provider is an execution input, never resolved or owned
by the runtime. No production execution uses this boundary yet.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel

from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeInfo
from ava.models.bindings import ConfiguredModelBinding
from ava.models.contracts import ModelProviderPort
from ava.workspaces.contracts import RuntimeWorkspaceBinding


class RuntimeRunResult(BaseModel):
    """Internal runtime result, not an API response or an agent-layer DTO.

    Implementations normalize execution into COMPLETED, FAILED, or CANCELLED
    using the existing RunStatus vocabulary. Content is optional assistant
    text or a sanitized failure message, never framework or transport data.
    """

    status: RunStatus
    content: str | None = None


class AgentRuntimePort(ABC):
    """Interchangeable execution framework using AVA contracts only.

    RuntimeInfo carries runtime identity and RuntimeCapabilities, separate
    from model capabilities and application capabilities. A runtime instance
    may execute with different model providers on different calls. Provider
    configuration, selection, and resource lifecycle remain caller-owned.
    """

    @abstractmethod
    def get_runtime_info(self) -> RuntimeInfo:
        """Return AVA-owned runtime identity and capability metadata."""
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
    ) -> RuntimeRunResult:
        """Execute with the selected provider under an AVA-generated run id.

        The runtime neither selects a provider nor a model nor generates a
        replacement run id. ``model_binding`` carries the stable AVA ``model_id``
        and the provider-native ``provider_model_name`` the runtime must target;
        when omitted, a runtime falls back to the provider's bootstrap identity.
        Normalize completion, failure, and cancellation into AVA results;
        framework-specific handles and raw errors must not cross the boundary.
        """
        raise NotImplementedError

    @abstractmethod
    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        """Request cancellation using the same AVA run id passed to execute.

        Implementations keep task/session mappings internal. Cancellation is
        cooperative and should report CANCELLED when it takes effect, or the
        recorded terminal outcome when execution already finished. Repeated
        cancellation is idempotent; unknown ids are a cancelled no-op.
        """
        raise NotImplementedError
