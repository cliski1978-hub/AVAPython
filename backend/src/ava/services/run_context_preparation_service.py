"""Prepare AVA-owned prompt context before crossing the AgentPort boundary."""

from dataclasses import dataclass

from ava.agents.contracts import ExecutionConfigurationError, ExecutionPromptContextBuilderPort
from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import ExecutionPromptContextBuildError, RunContext
from ava.contracts.requests import RunRequest
from ava.contracts.run_inspection import ContextCompactionAccounting
from ava.execution.context_window import input_budget_for
from ava.execution.selector import ExecutionSelector, ResolvedExecution
from ava.services.context_compaction_service import ContextCompactionService


@dataclass(frozen=True)
class PreparedRunContext:
    """A prepared context paired with the exact execution selection for it."""

    context: RunContext | None
    execution: ResolvedExecution


class RunContextPreparationService:
    """Resolve prompt layers and compact durable history before agent dispatch.

    This service is AVA-owned and runtime-neutral. It resolves the same
    execution selection used by the agent adapter so compaction uses the
    selected model/provider while every runtime receives the prepared context.
    """

    def __init__(
        self,
        *,
        selector: ExecutionSelector,
        prompt_context_builder: ExecutionPromptContextBuilderPort,
        compaction: ContextCompactionService,
    ) -> None:
        self._selector = selector
        self._prompt_context_builder = prompt_context_builder
        self._compaction = compaction

    async def prepare(self, request: RunRequest, context: RunContext | None) -> PreparedRunContext:
        """Return the instruction-resolved, compacted context for one run."""
        execution = self._selector.resolve(request.execution, conversation_id=request.conversation_id)
        try:
            prepared = self._prompt_context_builder.build(
                context,
                runtime_key=execution.runtime_key,
                capabilities={CapabilityName.RUNS, CapabilityName.CANCELLATION},
            )
        except ExecutionPromptContextBuildError as exc:
            raise ExecutionConfigurationError("AVA could not resolve instructions for this run") from exc
        try:
            compacted = await self._compaction.prepare(
                prepared,
                request.prompt,
                provider=execution.model_provider,
                provider_model_name=execution.model_binding.provider_model_name,
                provider_id=execution.model_profile.provider_id,
                model_id=execution.model_profile.model_id,
                model_context_limit=self._context_limit(execution),
            )
            prepared_context = (
                compacted.context.model_copy(update={"compaction_accounting": compacted.accounting.model_dump()})
                if compacted.context is not None
                else None
            )
            return PreparedRunContext(prepared_context, execution)
        except Exception as exc:
            # Compaction has historically been best-effort. Preserve execution
            # with the resolved prompts/context if summary generation fails.
            failed_context = prepared.model_copy(
                update={
                    "compaction_accounting": ContextCompactionAccounting(
                        attempted=True, failed=True, failure_reason=type(exc).__name__
                    ).model_dump()
                }
            )
            return PreparedRunContext(failed_context, execution)

    def preview(self, request: RunRequest, context: RunContext | None) -> RunContext | None:
        """Prepare draft prompt layers and reuse a valid saved summary."""
        execution = self._selector.resolve(request.execution, conversation_id=request.conversation_id)
        prepared = self._prompt_context_builder.build(
            context,
            runtime_key=execution.runtime_key,
            capabilities={CapabilityName.RUNS, CapabilityName.CANCELLATION},
        )
        limit = self._context_limit(execution)
        compacted, before, recommended, active = self._compaction.preview(
            prepared,
            request.prompt,
            model_id=execution.model_profile.model_id,
            input_budget=input_budget_for(limit) if limit is not None else None,
        )
        if compacted is None:
            return None
        return compacted.model_copy(
            update={
                "compaction_accounting": {
                    "estimated_before_tokens": before,
                    "compaction_recommended": recommended,
                    "summary_version": active.version if active else None,
                    "summary_token_count": active.summary_token_count if active else 0,
                }
            }
        )

    @staticmethod
    def _context_limit(execution: ResolvedExecution) -> int | None:
        """Return the configured/provider-capped window for the chosen model."""
        try:
            provider_limit = execution.model_provider.get_model_info().context_limit
        except Exception:
            provider_limit = None
        configured_limit = execution.model_profile.context_window_tokens
        if configured_limit is None:
            return provider_limit
        if provider_limit is None or provider_limit <= 0:
            return configured_limit
        return min(configured_limit, provider_limit)
