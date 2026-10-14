"""AVA native agent adapter delegating execution to an AgentRuntimePort."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ava.agents.contracts import (
    AgentPort,
    AgentRunResult,
    ExecutionConfigurationError,
    ExecutionPromptContextBuilderPort,
)
from ava.contracts.attachment_context import AttachmentContextStatus
from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import (
    ExecutionPromptContextBuildError,
    RunContext,
    draft_preview_context_messages,
    execution_context_messages,
)
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.failures import FailureCode
from ava.contracts.models import ModelHostingMode
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.contracts.run_inspection import ContextCompactionAccounting, ContextWindowAccounting, RunInspectionSnapshot
from ava.execution.compatibility import ExecutionCompatibilityValidator
from ava.execution.context_window import (
    ContextWindowExceededError,
    ContextWindowManager,
    ContextWindowResult,
)
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
        prompt_context_builder: ExecutionPromptContextBuilderPort | None = None,
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
        self._prompt_context_builder = prompt_context_builder
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
        resolved_execution: ResolvedExecution | None = None,
    ) -> AgentRunResult:
        return await self._start_run(
            run_id, request, context=context, on_content=None, resolved_execution=resolved_execution
        )

    async def start_run_streaming(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None = None,
        on_content: Callable[[str], None],
        on_inspection: Callable[[RunInspectionSnapshot], None] | None = None,
        resolved_execution: ResolvedExecution | None = None,
    ) -> AgentRunResult:
        """Forward normalized content snapshots from the selected runtime."""
        return await self._start_run(
            run_id,
            request,
            context=context,
            on_content=on_content,
            on_inspection=on_inspection,
            resolved_execution=resolved_execution,
        )

    async def _start_run(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None,
        on_content: Callable[[str], None] | None,
        on_inspection: Callable[[RunInspectionSnapshot], None] | None = None,
        resolved_execution: ResolvedExecution | None = None,
    ) -> AgentRunResult:
        self._terminal_statuses.pop(run_id, None)
        try:
            execution = resolved_execution or self._selector.resolve(
                request.execution, conversation_id=request.conversation_id
            )
            selection = self._selection(execution)
            compatible = self._validator.validate(
                request=request,
                runtime=execution.runtime,
                model_provider=execution.model_provider,
                hosting_mode=execution.model_binding.hosting_mode,
                hosting_requirement=self._hosting_requirement,
                model_capabilities=execution.model_profile.capabilities,
            ).compatible
        except ExecutionConfigurationError:
            # A failure to resolve persisted execution already carries a precise
            # reason that the run service maps to a public code. Swallowing it
            # here would discard every configuration classification and collapse
            # them into the generic code.
            raise
        except Exception as exc:
            # Runtime/model profile ids are resolved before any adapter runs.
            # Resolver failures such as an unknown runtime or no eligible model
            # are plain ValueErrors today, not ExecutionConfigurationErrors;
            # treating them as an agent failure used to lose both the selected
            # execution identity and the actionable configuration classification.
            raise ExecutionConfigurationError("Selected execution configuration could not be resolved") from exc
        if not compatible:
            return AgentRunResult(
                status=RunStatus.FAILED,
                content="Selected execution configuration is not compatible",
                execution_selection=selection,
                failure_code=FailureCode.CONFIGURATION_INVALID,
            )
        if self._prompt_context_builder is not None:
            try:
                context = self._prompt_context_builder.build(
                    context,
                    runtime_key=execution.runtime_key,
                    capabilities=self.get_capabilities(),
                )
            except ExecutionPromptContextBuildError as exc:
                logger.warning(
                    "Unable to resolve execution prompt context for run %s (%s)",
                    run_id,
                    exc.error_code,
                )
                return AgentRunResult(
                    status=RunStatus.FAILED,
                    content="AVA could not resolve the instructions for this run",
                    execution_selection=selection,
                    failure_code=FailureCode.CONFIGURATION_INVALID,
                )
        lease: ModelLease | None = None
        if self._resource_manager is not None:
            try:
                lease = await self._resource_manager.acquire(
                    execution.model_profile.model_id, profile=execution.model_profile
                )
            except Exception:
                logger.exception("Unable to acquire the selected model for run %s", run_id)
                return AgentRunResult(
                    status=RunStatus.FAILED,
                    content="Selected model is unavailable",
                    execution_selection=selection,
                    failure_code=FailureCode.CONFIGURATION_INVALID,
                )
        compaction = ContextCompactionAccounting.model_validate(
            context.compaction_accounting if context and context.compaction_accounting else {}
        )
        try:
            bounded, budget = self._bound_context(context, request, execution)
        except ContextWindowExceededError as exc:
            logger.info("Run %s does not fit the selected model's context window", run_id)
            if lease is not None:
                await lease.release()
            limit = self._context_limit(execution)
            inspection = RunInspectionSnapshot(
                attachments=[
                    item.model_copy(
                        update={
                            "status": AttachmentContextStatus.EXCLUDED_CONTEXT_LIMIT,
                            "included": False,
                            "text": None,
                        }
                    )
                    if item.status is AttachmentContextStatus.EXTRACTED
                    else item
                    for item in (context.attachments if context else [])
                ],
                execution_resolution={
                    "model_id": execution.model_profile.model_id,
                    "project_id": execution.project_id,
                },
                context_window=ContextWindowAccounting(
                    context_window_tokens=limit,
                    input_budget_tokens=exc.available_budget,
                    estimated_input_tokens=exc.estimated_size,
                    output_reserve_tokens=(limit - exc.available_budget) if limit is not None else 0,
                    count_accuracy="estimated",
                    can_fit=False,
                    required_input_tokens=exc.estimated_size,
                    model_id=execution.model_profile.model_id,
                ),
                context_compaction=compaction,
            )
            return AgentRunResult(
                status=RunStatus.FAILED,
                content=_CONTEXT_WINDOW_CONTENT,
                execution_selection=selection,
                failure_code=FailureCode.CONTEXT_WINDOW_EXCEEDED,
                inspection_snapshot=inspection,
            )
        inspection = RunInspectionSnapshot(
            execution_resolution={
                "runtime_id": selection.runtime_id if selection else None,
                "model_provider_id": selection.model_provider_id if selection else None,
                "model_id": selection.model_id if selection else None,
                "hosting_mode": selection.hosting_mode.value if selection and selection.hosting_mode else None,
                "workspace_id": request.workspace_id,
                "runtime_source": (
                    execution.source.value
                    if execution.source.value == "persisted"
                    else execution.runtime_selection_source.value
                ),
                "model_source": (
                    execution.source.value
                    if execution.source.value == "persisted"
                    else execution.model_selection_source.value
                ),
                "provider_connection_id": execution.provider_connection_id,
                "runtime_configuration_id": execution.runtime_configuration_id,
                "project_id": execution.project_id,
            },
            prompt_layers=bounded.prompt_layers if bounded is not None else None,
            normalized_request=execution_context_messages(bounded, request.prompt),
            attachments=bounded.attachments if bounded is not None else [],
            context_window=ContextWindowAccounting(
                context_window_tokens=budget.context_limit,
                input_budget_tokens=budget.input_budget,
                estimated_input_tokens=budget.estimated_input_tokens,
                output_reserve_tokens=(
                    budget.context_limit - budget.input_budget
                    if budget.context_limit is not None and budget.input_budget is not None
                    else 0
                ),
                dropped_message_count=budget.dropped_message_count,
                dropped_turn_count=budget.dropped_turn_count,
                count_accuracy="estimated",
                model_id=execution.model_profile.model_id,
                attachment_context_tokens=sum(item.token_count for item in bounded.attachments if item.included)
                if bounded is not None
                else 0,
            ),
            context_compaction=compaction.model_copy(
                update={
                    "estimated_after_tokens": budget.estimated_input_tokens,
                    "recent_message_ids": [
                        message.message_id
                        for message in (bounded.messages if bounded is not None else [])
                        if message.message_id
                    ],
                }
            ),
        )
        if on_inspection is not None:
            on_inspection(inspection)
        try:
            workspace: RuntimeWorkspaceBinding | None = self._resolve_workspace(request.workspace_id)
        except UnknownWorkspaceError:
            if lease is not None:
                await lease.release()
            return AgentRunResult(
                status=RunStatus.FAILED,
                content="Requested workspace is unavailable",
                failure_code=FailureCode.CONFIGURATION_INVALID,
            )
        terminal_status = RunStatus.FAILED
        self._executions[run_id] = execution
        try:
            if on_content is None or not execution.model_profile.capabilities.streaming:
                result = await execution.runtime.execute(
                    run_id=run_id,
                    request=request,
                    model_provider=execution.model_provider,
                    workspace=workspace,
                    model_binding=execution.model_binding,
                    model_capabilities=execution.model_profile.capabilities,
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
                    model_capabilities=execution.model_profile.capabilities,
                    context=bounded,
                )
            terminal_status = result.status
            inspection = inspection.model_copy(
                update={
                    "runtime_request": result.runtime_request,
                    "runtime_response": result.runtime_response,
                    "normalized_response": {
                        "status": result.status.value,
                        "content": result.content,
                        "failure_code": result.failure_code,
                    },
                }
            )
            if on_inspection is not None:
                on_inspection(inspection)
            return AgentRunResult(
                status=result.status,
                content=result.content,
                execution_selection=selection,
                failure_code=result.failure_code,
                inspection_snapshot=inspection,
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
    ) -> tuple[RunContext | None, ContextWindowResult]:
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
        base_context = context.model_copy(update={"attachments": []}) if context is not None else None
        messages = execution_context_messages(base_context, request.prompt)
        context_limit = self._context_limit(execution)
        result, attachments = self._context_window.fit_with_attachments(
            messages,
            context.attachments if context is not None else [],
            model_context_limit=context_limit,
            model_id=execution.model_profile.model_id,
        )
        if context is None:
            return context, result
        if not context.has_messages:
            # The current user prompt is supplied by the runtime fallback and
            # is never copied into the durable-history field. All leading
            # instruction layers are mandatory and remain on the context.
            return context.model_copy(update={"attachments": attachments}), result
        layer_count = 0
        if context.prompt_layers is not None:
            layer_count = (
                1
                + len(context.prompt_layers.resolved_core_prompts)
                + int(bool(context.prompt_layers.project_instructions))
            )
        layer_count += int(bool(context.conversation_summary))
        included_count = sum(item.included for item in attachments)
        history = result.messages[layer_count:]
        if included_count:
            history = [*history[: -(included_count + 1)], history[-1]]
        return context.model_copy(update={"messages": history, "attachments": attachments}), result

    def _context_limit(self, execution: ResolvedExecution) -> int | None:
        """Read the selected model's total context window, if it reports one.

        The configured per-model value is constrained by provider-reported
        metadata for the model this run actually resolved to. Neither value can
        be supplied by a run request. A provider metadata read failure falls
        back to the configured value, or to no limit when neither source has one.
        """
        try:
            provider_limit = execution.model_provider.get_model_info().context_limit
        except Exception:
            logger.exception("Unable to read context window for model %s", execution.model_profile.model_id)
            provider_limit = None
        configured_limit = execution.model_profile.context_window_tokens
        if configured_limit is None:
            return provider_limit
        if provider_limit is None or provider_limit <= 0:
            return configured_limit
        return min(configured_limit, provider_limit)

    def preview_context_window(
        self, request: RunRequest, *, context: RunContext | None = None
    ) -> ContextWindowAccounting:
        """Resolve and budget a draft exactly as execution would, without dispatch."""
        execution = self._selector.resolve(request.execution, conversation_id=request.conversation_id)
        prepared = context
        if self._prompt_context_builder is not None:
            prepared = self._prompt_context_builder.build(
                prepared,
                runtime_key=execution.runtime_key,
                capabilities=self.get_capabilities(),
            )
        limit = self._context_limit(execution)
        compaction_preview = (prepared.compaction_accounting or {}) if prepared is not None else {}
        estimated_before_compaction = compaction_preview.get("estimated_before_tokens")
        compaction_recommended = compaction_preview.get("compaction_recommended", False)
        active_summary_version = compaction_preview.get("summary_version")
        active_summary_token_count = compaction_preview.get("summary_token_count", 0)
        base_prepared = prepared.model_copy(update={"attachments": []}) if prepared is not None else None
        messages = draft_preview_context_messages(base_prepared, request.prompt)
        try:
            result, attachments = self._context_window.fit_with_attachments(
                messages,
                prepared.attachments if prepared is not None else [],
                model_context_limit=limit,
                model_id=execution.model_profile.model_id,
            )
            return ContextWindowAccounting(
                context_window_tokens=result.context_limit,
                input_budget_tokens=result.input_budget,
                estimated_input_tokens=result.estimated_input_tokens,
                output_reserve_tokens=(result.context_limit - result.input_budget)
                if result.context_limit is not None and result.input_budget is not None
                else 0,
                dropped_message_count=result.dropped_message_count,
                dropped_turn_count=result.dropped_turn_count,
                count_accuracy="estimated",
                can_fit=True,
                required_input_tokens=result.estimated_input_tokens,
                model_id=execution.model_profile.model_id,
                estimated_before_compaction_tokens=(
                    estimated_before_compaction if isinstance(estimated_before_compaction, int) else None
                ),
                compaction_recommended=bool(compaction_recommended),
                active_summary_version=(active_summary_version if isinstance(active_summary_version, int) else None),
                active_summary_token_count=(
                    active_summary_token_count if isinstance(active_summary_token_count, int) else 0
                ),
                attachment_context_tokens=sum(item.token_count for item in attachments if item.included),
                attachments=attachments,
            )
        except ContextWindowExceededError as exc:
            return ContextWindowAccounting(
                context_window_tokens=limit,
                input_budget_tokens=exc.available_budget,
                estimated_input_tokens=exc.estimated_size,
                output_reserve_tokens=(limit - exc.available_budget) if limit is not None else 0,
                count_accuracy="estimated",
                can_fit=False,
                required_input_tokens=exc.estimated_size,
                model_id=execution.model_profile.model_id,
                estimated_before_compaction_tokens=(
                    estimated_before_compaction if isinstance(estimated_before_compaction, int) else None
                ),
                compaction_recommended=bool(compaction_recommended),
                active_summary_version=(active_summary_version if isinstance(active_summary_version, int) else None),
                active_summary_token_count=(
                    active_summary_token_count if isinstance(active_summary_token_count, int) else 0
                ),
            )

    def _selection(self, execution: ResolvedExecution) -> RunExecutionSelection | None:
        """Read identity metadata defensively; lifecycle must remain safe.

        The stable AVA ``model_id`` and provider identity come from the resolved
        binding; the effective registry runtime key comes from selection, and
        run metadata never reports the provider-native model name.
        """
        try:
            binding = execution.model_binding
            return RunExecutionSelection(
                runtime_id=execution.runtime_key,
                model_provider_id=binding.provider_id,
                model_id=binding.model_id,
                hosting_mode=binding.hosting_mode,
                # Configuration persistence describes how a selection was
                # materialized, while these fields describe which precedence
                # tier supplied each axis. Preserve the selector's provenance
                # so Project defaults remain distinguishable from application
                # defaults in stored run history and the inspector.
                runtime_source=execution.runtime_selection_source.value,
                model_source=execution.model_selection_source.value,
                provider_connection_id=execution.provider_connection_id,
                runtime_configuration_id=execution.runtime_configuration_id,
                project_id=execution.project_id,
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

    def resolve(self, _override: object = None, *, conversation_id: str | None = None) -> ResolvedExecution:
        from ava.execution.selector import ResolvedExecution

        profile = self._profile()
        return ResolvedExecution(
            self._runtime,
            self._provider,
            model_binding_from_profile(profile),
            profile,
            self._runtime.get_runtime_info().runtime_id,
        )
