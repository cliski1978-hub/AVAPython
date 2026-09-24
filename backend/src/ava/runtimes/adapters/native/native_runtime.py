"""Native runtime execution with a caller-selected model provider."""

import asyncio
import logging

from ava.contracts.models import ModelMessage, ModelRequest, ModelResponse
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo
from ava.models.bindings import ConfiguredModelBinding
from ava.models.contracts import ModelProviderPort
from ava.models.errors import ModelProviderError
from ava.runtimes.contracts import AgentRuntimePort, RuntimeRunResult
from ava.workspaces.contracts import RuntimeWorkspaceBinding

logger = logging.getLogger(__name__)
_FAILURE_CONTENT = "Model provider request failed"


class NativeRuntime(AgentRuntimePort):
    """Execute with any supplied model port; retain only local task/status state.

    Provider selection and resource lifecycle remain caller-owned. This runtime
    is not yet used by the application's agent or composition.
    """

    def __init__(self) -> None:
        self._run_tasks: dict[str, asyncio.Task[ModelResponse]] = {}
        self._final_status: dict[str, RunStatus] = {}

    def get_runtime_info(self) -> RuntimeInfo:
        return RuntimeInfo(
            runtime_id="native",
            display_name="AVA Native Runtime",
            capabilities=RuntimeCapabilities(),
        )

    async def execute(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
    ) -> RuntimeRunResult:
        """Translate a prompt and normalize outcomes without emitting events.

        When a binding is supplied, the provider is asked for exactly the
        bound provider-native model name; otherwise the provider's bootstrap
        name is used. The runtime never chooses a model.
        """
        del workspace
        if run_id in self._run_tasks:
            return RuntimeRunResult(status=RunStatus.FAILED, content="Run is already active")
        # A completed id may be reused; its previous status must not cancel a
        # new execution. Active duplicates return before changing any state.
        self._final_status.pop(run_id, None)
        model_name = None
        if model_binding is not None and model_binding.provider_model_name.strip():
            model_name = model_binding.provider_model_name
        try:
            model_request = ModelRequest(
                messages=[ModelMessage(role="user", content=request.prompt)]
            )
            task = asyncio.create_task(
                model_provider.generate(model_request, model_name=model_name)
            )
            self._run_tasks[run_id] = task
            response = await task
            result = RuntimeRunResult(status=RunStatus.COMPLETED, content=response.content)
        except asyncio.CancelledError:
            result = RuntimeRunResult(status=RunStatus.CANCELLED)
        except ModelProviderError:
            result = RuntimeRunResult(status=RunStatus.FAILED, content=_FAILURE_CONTENT)
        except Exception:
            logger.exception("Unexpected model provider failure for run %s", run_id)
            result = RuntimeRunResult(status=RunStatus.FAILED, content=_FAILURE_CONTENT)
        finally:
            self._run_tasks.pop(run_id, None)

        # Cancellation wins even if a provider suppresses CancelledError and
        # returns content or raises an ordinary error during its cleanup.
        if self._final_status.get(run_id) == RunStatus.CANCELLED:
            result = RuntimeRunResult(status=RunStatus.CANCELLED)
        self._final_status[run_id] = result.status
        return result

    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        """Cancel active generation; finished and unknown runs are idempotent."""
        task = self._run_tasks.get(run_id)
        if task is not None:
            if self._final_status.get(run_id) != RunStatus.CANCELLED:
                self._final_status[run_id] = RunStatus.CANCELLED
                task.cancel()
            return RuntimeRunResult(status=RunStatus.CANCELLED)
        return RuntimeRunResult(
            status=self._final_status.get(run_id, RunStatus.CANCELLED),
        )
