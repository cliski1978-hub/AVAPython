"""AVA native agent adapter delegating execution to an AgentRuntimePort."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from ava.agents.contracts import AgentPort, AgentRunResult
from ava.contracts.capabilities import CapabilityName
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.models import ModelHostingMode
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.execution.compatibility import ExecutionCompatibilityValidator
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
    ) -> None:
        self._executions: dict[str, ResolvedExecution] = {}
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

    def name(self) -> str:
        return "native"

    def get_capabilities(self) -> set[CapabilityName]:
        return {CapabilityName.RUNS, CapabilityName.CANCELLATION}

    async def start_run(self, run_id: str, request: RunRequest) -> AgentRunResult:
        try:
            execution = self._selector.resolve(request.execution)
            selection = self._selection(execution)
            self._executions[run_id] = execution
            if not self._validator.validate(
                request=request,
                runtime=execution.runtime,
                model_provider=execution.model_provider,
                hosting_mode=execution.model_binding.hosting_mode,
                hosting_requirement=self._hosting_requirement,
                model_capabilities=execution.model_profile.capabilities,
            ).compatible:
                return AgentRunResult(
                    status=RunStatus.FAILED, content="Selected execution configuration is not compatible"
                )
        except Exception:
            return AgentRunResult(status=RunStatus.FAILED, content="Requested execution unavailable")
        try:
            workspace: RuntimeWorkspaceBinding | None = self._resolve_workspace(request.workspace_id)
        except UnknownWorkspaceError:
            return AgentRunResult(status=RunStatus.FAILED, content="Requested workspace is unavailable")
        lease: ModelLease | None = None
        try:
            if self._resource_manager is not None:
                lease = await self._resource_manager.acquire(execution.model_profile.model_id)
            result = await execution.runtime.execute(
                run_id=run_id,
                request=request,
                model_provider=execution.model_provider,
                workspace=workspace,
                model_binding=execution.model_binding,
            )
            return AgentRunResult(status=result.status, content=result.content, execution_selection=selection)
        except asyncio.CancelledError:
            return AgentRunResult(status=RunStatus.CANCELLED, execution_selection=selection)
        except Exception:
            logger.exception("Unexpected runtime failure for run %s", run_id)
            return AgentRunResult(
                status=RunStatus.FAILED,
                content="Agent runtime failed",
                execution_selection=selection,
            )
        finally:
            if lease is not None:
                try:
                    await lease.release()
                except Exception:
                    logger.exception("Unable to release model resource lease for run %s", run_id)

    async def cancel_run(self, run_id: str) -> RunResponse:
        execution = self._executions.get(run_id)
        if execution is None:
            return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)
        result: RuntimeRunResult = await execution.runtime.cancel_run(run_id)
        return RunResponse(run_id=run_id, status=result.status)

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
