"""Native runtime execution with a caller-selected model provider."""

import asyncio
import logging
from collections.abc import Callable

from ava.contracts.conversations import RunContext, execution_context_messages
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


def _model_messages(context: RunContext | None, prompt: str) -> list[ModelMessage]:
    """Translate the AVA-constructed context into provider message shape.

    This is a pure role/text translation. The runtime does not choose, order,
    or drop messages: it renders exactly the sequence AVA handed it. When no
    durable context exists, the shared contract resolves the sequence to the
    run's single prompt, preserving the legacy single-turn behavior.
    """
    return [
        ModelMessage(role=message.role.value, content=message.content)
        for message in execution_context_messages(context, prompt)
    ]


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
        context: RunContext | None = None,
    ) -> RuntimeRunResult:
        """Translate the run's context and normalize outcomes without events.

        When a binding is supplied, the provider is asked for exactly the
        bound provider-native model name; otherwise the provider's bootstrap
        name is used. The runtime never chooses a model and never selects
        history: ``context`` is translated as given.
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
        model_request = ModelRequest(messages=_model_messages(context, request.prompt))
        try:
            task = asyncio.create_task(model_provider.generate(model_request, model_name=model_name))
            self._run_tasks[run_id] = task
            response = await task
            result = RuntimeRunResult(
                status=RunStatus.COMPLETED,
                content=response.content,
                runtime_request={"model_request": model_request.model_dump(mode="json"), "model_name": model_name},
                runtime_response=response.model_dump(mode="json"),
            )
        except asyncio.CancelledError:
            result = RuntimeRunResult(status=RunStatus.CANCELLED)
        except ModelProviderError as exc:
            # A classified provider failure keeps its code. Flattening it here
            # would make every provider problem indistinguishable at the public
            # boundary, which is exactly what the taxonomy exists to prevent.
            logger.warning("Model provider failure for run %s: %s", run_id, exc)
            result = RuntimeRunResult(
                status=RunStatus.FAILED,
                content=_FAILURE_CONTENT,
                failure_code=exc.safe_code,
                runtime_request={"model_request": model_request.model_dump(mode="json"), "model_name": model_name},
            )
        except Exception:
            logger.exception("Unexpected model provider failure for run %s", run_id)
            result = RuntimeRunResult(
                status=RunStatus.FAILED,
                content=_FAILURE_CONTENT,
                runtime_request={"model_request": model_request.model_dump(mode="json"), "model_name": model_name},
            )
        finally:
            self._run_tasks.pop(run_id, None)

        # Cancellation wins even if a provider suppresses CancelledError and
        # returns content or raises an ordinary error during its cleanup.
        if self._final_status.get(run_id) == RunStatus.CANCELLED:
            result = RuntimeRunResult(status=RunStatus.CANCELLED)
        self._final_status[run_id] = result.status
        return result

    async def execute_streaming(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
        on_content: Callable[[str], None],
        workspace: RuntimeWorkspaceBinding | None = None,
        model_binding: ConfiguredModelBinding | None = None,
        context: RunContext | None = None,
    ) -> RuntimeRunResult:
        """Consume provider deltas immediately and publish full content snapshots."""
        if not model_provider.get_capabilities().streaming:
            return await self.execute(
                run_id=run_id,
                request=request,
                model_provider=model_provider,
                workspace=workspace,
                model_binding=model_binding,
                context=context,
            )
        del workspace
        if run_id in self._run_tasks:
            return RuntimeRunResult(status=RunStatus.FAILED, content="Run is already active")
        self._final_status.pop(run_id, None)
        model_name = (
            model_binding.provider_model_name
            if model_binding is not None and model_binding.provider_model_name.strip()
            else None
        )
        model_request = ModelRequest(messages=_model_messages(context, request.prompt))

        async def consume() -> ModelResponse:
            """Iterate provider deltas, publishing the growing snapshot per delta.

            ``on_content`` receives the accumulated text, not the delta: every
            downstream consumer (durable message, run event, SSE frame) treats
            content as one replaceable snapshot, so appending here would
            duplicate prefixes on replay and on refresh.
            """
            snapshot = ""
            async for delta in model_provider.stream(model_request, model_name=model_name):
                snapshot += delta
                on_content(snapshot)
            return ModelResponse(content=snapshot, model_id=model_name or "")

        try:
            task = asyncio.create_task(consume())
            self._run_tasks[run_id] = task
            response = await task
            result = RuntimeRunResult(
                status=RunStatus.COMPLETED,
                content=response.content,
                runtime_request={"model_request": model_request.model_dump(mode="json"), "model_name": model_name},
                runtime_response=response.model_dump(mode="json"),
            )
        except asyncio.CancelledError:
            result = RuntimeRunResult(status=RunStatus.CANCELLED)
        except ModelProviderError as exc:
            logger.warning("Model provider streaming failure for run %s: %s", run_id, exc)
            result = RuntimeRunResult(
                status=RunStatus.FAILED,
                content=_FAILURE_CONTENT,
                failure_code=exc.safe_code,
                runtime_request={"model_request": model_request.model_dump(mode="json"), "model_name": model_name},
            )
        except Exception:
            logger.exception("Unexpected model provider streaming failure for run %s", run_id)
            result = RuntimeRunResult(
                status=RunStatus.FAILED,
                content=_FAILURE_CONTENT,
                runtime_request={"model_request": model_request.model_dump(mode="json"), "model_name": model_name},
            )
        finally:
            self._run_tasks.pop(run_id, None)
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
            status=self._final_status.get(run_id, RunStatus.RUNNING),
        )
