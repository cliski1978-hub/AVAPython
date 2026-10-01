"""AVA native agent adapter delegating execution to an AgentRuntimePort."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ava.agents.contracts import AgentPort, AgentRunResult, ExecutionConfigurationError
from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import RunContext, execution_context_messages
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.failures import FailureCode
from ava.contracts.models import ModelHostingMode
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.execution.compatibility import ExecutionCompatibilityValidator
from ava.execution.context_window import ContextWindowExceededError, ContextWindowManager
from ava.execution.hosting import ModelHostingRequirement
from ava.execution.model_resources import ModelLease, ModelResourceManager
from ava.execution.selector import ExecutionSelector
from ava.models.bindings import model_binding_from_profile
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile
from ava.runtimes.contracts import AgentRuntimePort, RuntimeRunResult
from ava.workspaces import RuntimeWorkspaceBinding, UnknownWorkspaceError, WorkspaceResolver, bind_workspace

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from ava.execution.selector import ResolvedExecution

#: Sanitized run outcome for a request the selected model cannot accept. It
#: names the reason without exposing any conversation content or size details
#: that the public run response is not meant to carry.
_CONTEXT_WINDOW_CONTENT = "Request exceeds the selected model's context window"


class NativeAgentAdapter(AgentPort):
    """Thin AVA agent boundary over independently selected runtime/model ports.

    In addition to execution selection and compatibility validation, this
    adapter resolves an approved AVA workspace id through the injected
    ``WorkspaceResolver`` and hands the selected runtime an already-approved
    ``RuntimeWorkspaceBinding``. Runtimes never resolve workspace ids; an
    unknown or unrequested workspace is never granted or fallen back to.
    """

    def __init__(
        self,
        execution_selector: ExecutionSelector | AgentRuntimePort,
        model_provider: ModelProviderPort | None = None,
        compatibility_validator: ExecutionCompatibilityValidator | None = None,
        workspace_resolver: WorkspaceResolver | None = None,
        hosting_requirement: ModelHostingRequirement | None = None,
        model_resource_manager: ModelResourceManager | None = None,
        context_window_manager: ContextWindowManager | None = None,
    ) -> None:
        self._executions: dict[str, ResolvedExecution] = {}
        self._terminal_statuses: dict[str, RunStatus] = {}
        self._selector: Any
        if isinstance(execution_selector, AgentRuntimePort):
            if model_provider is None:
                raise ValueError("Native agent requires a model provider")
            self._selector = _FixedSelector(execution_selector, model_provider)
        else:
            self._selector = execution_selector
        self._validator = compatibility_validator or ExecutionCompatibilityValidator()
        self._workspace_resolver = workspace_resolver
        # Server-owned placement policy (Step 39). ``None`` means unconstrained;
        # clients never supply this through a run request.
        self._hosting_requirement = hosting_requirement
        self._resource_manager = model_resource_manager
        # The window policy is AVA-owned and runtime-neutral, so it always runs
        # here — above the runtime boundary, after model selection. A default
        # instance is the documented policy rather than a bypass switch: the
        # manager has no dependencies beyond its token estimator, and omitting
        # it must never mean "skip windowing".
        self._context_window = context_window_manager or ContextWindowManager()

    def name(self) -> str:
        return "native"

    def get_capabilities(self) -> set[CapabilityName]:
        return {CapabilityName.RUNS, CapabilityName.CANCELLATION}

    async def start_run(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None = None,
    ) -> AgentRunResult:
        return await self._start_run(run_id, request, context=context, on_content=None)

    async def start_run_streaming(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None = None,
        on_content: Callable[[str], None],
    ) -> AgentRunResult:
        """Forward normalized content snapshots from the selected runtime."""
        return await self._start_run(
            run_id, request, context=context, on_content=on_content
        )

    async def _start_run(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None,
        on_content: Callable[[str], None] | None,
    ) -> AgentRunResult:
        self._terminal_statuses.pop(run_id, None)
        try:
            execution = self._selector.resolve(request.execution)
            selection = self._selection(execution)
            if not self._validator.validate(
                request=request,
                runtime=execution.runtime,
                model_provider=execution.model_provider,
                hosting_mode=execution.model_binding.hosting_mode,
                hosting_requirement=self._hosting_requirement,
                model_capabilities=execution.model_profile.capabilities,
            ).compatible:
                return AgentRunResult(
                    status=RunStatus.FAILED,
                    content="Selected execution configuration is not compatible",
                    failure_code=FailureCode.CONFIGURATION_INVALID,
                )
        except ExecutionConfigurationError:
            # A failure to resolve persisted execution already carries a precise
            # reason that the run service maps to a public code. Swallowing it
            # here would discard every configuration classification and collapse
            # them into the generic code.
            raise
        except Exception:
            return AgentRunResult(status=RunStatus.FAILED, content="Requested execution unavailable")
        try:
            bounded = self._bound_context(context, request, execution)
        except ContextWindowExceededError:
            logger.info(
                "Run %s does not fit the selected model's context window", run_id
            )
            return AgentRunResult(
                status=RunStatus.FAILED,
                content=_CONTEXT_WINDOW_CONTENT,
                failure_code=FailureCode.CONTEXT_WINDOW_EXCEEDED,
            )
        try:
            workspace: RuntimeWorkspaceBinding | None = self._resolve_workspace(request.workspace_id)
        except UnknownWorkspaceError:
            return AgentRunResult(
                status=RunStatus.FAILED,
                content="Requested workspace is unavailable",
                failure_code=FailureCode.CONFIGURATION_INVALID,
            )
        lease: ModelLease | None = None
        terminal_status = RunStatus.FAILED
        self._executions[run_id] = execution
        try:
            if self._resource_manager is not None:
                lease = await self._resource_manager.acquire(
                    execution.model_profile.model_id, profile=execution.model_profile
                )
            if on_content is None or not execution.model_profile.capabilities.streaming:
                result = await execution.runtime.execute(
                    run_id=run_id,
                    request=request,
                    model_provider=execution.model_provider,
                    workspace=workspace,
                    model_binding=execution.model_binding,
                    context=bounded,
                )
            else:
                result = await execution.runtime.execute_streaming(
                    run_id=run_id,
                    request=request,
                    model_provider=execution.model_provider,
                    on_content=on_content,
                    workspace=workspace,
                    model_binding=execution.model_binding,
                    context=bounded,
                )
            terminal_status = result.status
            return AgentRunResult(
                status=result.status,
                content=result.content,
                execution_selection=selection,
                failure_code=result.failure_code,
            )
        except asyncio.CancelledError:
            terminal_status = RunStatus.CANCELLED
            return AgentRunResult(status=RunStatus.CANCELLED, execution_selection=selection)
        except Exception:
            logger.exception("Unexpected runtime failure for run %s", run_id)
            return AgentRunResult(
                status=RunStatus.FAILED,
                content="Agent runtime failed",
                execution_selection=selection,
            )
        finally:
            self._executions.pop(run_id, None)
            # Preserve terminal cancellation semantics without retaining the
            # per-run provider instance and its resolved credential.
            self._terminal_statuses[run_id] = terminal_status
            if lease is not None:
                try:
                    await lease.release()
                except Exception:
                    logger.exception("Unable to release model resource lease for run %s", run_id)

    async def cancel_run(self, run_id: str) -> RunResponse:
        execution = self._executions.get(run_id)
        if execution is None:
            return RunResponse(run_id=run_id, status=self._terminal_statuses.get(run_id, RunStatus.RUNNING))
        result: RuntimeRunResult = await execution.runtime.cancel_run(run_id)
        return RunResponse(run_id=run_id, status=result.status)

    def _bound_context(
        self,
        context: RunContext | None,
        request: RunRequest,
        execution: ResolvedExecution,
    ) -> RunContext | None:
        """Return the context the selected model can actually accept.

        The effective sequence is the one a runtime would execute: durable
        context when the run has any, otherwise the request's single prompt. AVA
        windows that sequence using the *selected* model's context window, so the
        budget follows model selection rather than the runtime type and never a
        client-supplied value.

        A run with a constructed context keeps its conversation and source
        message ids and receives bounded messages. An unlinked run keeps its
        prompt-only path: the prompt is still measured against the budget, but
        ``None`` is passed on so the runtime's legacy fallback is untouched.
        """
        messages = execution_context_messages(context, request.prompt)
        result = self._context_window.fit(
            messages,
            model_context_limit=self._context_limit(execution),
            model_id=execution.model_profile.model_id,
        )
        if context is None or not context.has_messages:
            return context
        return context.model_copy(update={"messages": result.messages})

    def _context_limit(self, execution: ResolvedExecution) -> int | None:
        """Read the selected model's total context window, if it reports one.

        The value is provider-reported discovery metadata for the model this run
        actually resolved to — never a persisted configuration field, never a
        frontend value, and never a global default. A provider that cannot report
        its metadata is treated as reporting no limit, which keeps execution
        working exactly as it did before context-window management existed
        instead of failing a run over a metadata read.
        """
        try:
            return execution.model_provider.get_model_info().context_limit
        except Exception:
            logger.exception(
                "Unable to read context window for model %s", execution.model_profile.model_id
            )
            return None

    def _selection(self, execution: ResolvedExecution) -> RunExecutionSelection | None:
        """Read identity metadata defensively; lifecycle must remain safe.

        The stable AVA ``model_id`` and provider identity come from the resolved
        binding; run metadata never reports the provider-native model name.
        """
        try:
            runtime_info = execution.runtime.get_runtime_info()
            binding = execution.model_binding
            return RunExecutionSelection(
                runtime_id=runtime_info.runtime_id,
                model_provider_id=binding.provider_id,
                model_id=binding.model_id,
                hosting_mode=binding.hosting_mode,
            )
        except Exception:
            logger.exception("Unable to collect execution selection metadata")
            return None

    def _resolve_workspace(self, workspace_id: str | None) -> RuntimeWorkspaceBinding | None:
        """Convert an opaque AVA workspace id into an already-approved binding.

        ``None`` preserves the existing no-workspace execution path. A missing
        configured resolver is treated like an unknown id: the run fails
        cleanly and no fallback workspace (cwd, home, repository root, or
        ``/``) is ever granted.
        """
        if workspace_id is None:
            return None
        if self._workspace_resolver is None:
            raise UnknownWorkspaceError(workspace_id)
        return bind_workspace(self._workspace_resolver.resolve(workspace_id))


class _FixedSelector:
    """Legacy fixed runtime/provider selector.

    Builds a synthetic ``ModelProfile`` from the injected provider so the legacy
    constructor path keeps working without a configured registry. The provider's
    reported ``model_id`` is used as both the stable identity and the
    provider-native name until explicit profiles are configured. The profile
    carries the provider's declared capabilities and the unconstrained ``LOCAL``
    hosting default.
    """

    def __init__(self, runtime: AgentRuntimePort, provider: ModelProviderPort) -> None:
        self._runtime, self._provider = runtime, provider

    def _profile(self) -> ModelProfile:
        provider_id = self._provider.name()
        try:
            info = self._provider.get_model_info()
            model_id = info.model_id
            display_name = info.display_name or info.model_id
            capabilities = info.capabilities
        except Exception:
            logger.exception("Unable to read fixed-provider model identity")
            model_id = provider_id
            display_name = provider_id
            capabilities = self._provider.get_capabilities()
        return ModelProfile(
            model_id=model_id,
            display_name=display_name,
            provider_id=provider_id,
            provider_model_name=model_id,
            hosting_mode=ModelHostingMode.LOCAL,
            capabilities=capabilities,
            enabled=True,
        )

    def resolve(self, _override: object = None) -> ResolvedExecution:
        from ava.execution.selector import ResolvedExecution

        profile = self._profile()
        return ResolvedExecution(self._runtime, self._provider, model_binding_from_profile(profile), profile)
