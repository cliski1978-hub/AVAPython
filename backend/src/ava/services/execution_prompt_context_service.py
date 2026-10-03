"""AVA-owned assembly of root, resolved CORE, and Project instruction layers."""

import logging
from collections.abc import Collection

from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import (
    ExecutionCorePrompt,
    ExecutionPromptContextBuildError,
    ExecutionPromptLayers,
    RunContext,
)
from ava.repositories.core_prompt_assignment import CorePromptAssignmentMode
from ava.repositories.project_repository import ProjectRepository
from ava.services.effective_prompt_resolver import (
    EffectivePromptResolver,
    PromptResolutionContext,
    PromptResolutionError,
)

logger = logging.getLogger(__name__)

# This immutable, application-owned instruction is the root of the prompt
# hierarchy. CORE definitions and Project metadata can only add subordinate
# messages after it; neither can replace it.
AVA_ROOT_SYSTEM_PROMPT = "You are AVA, an AI assistant. Respond helpfully and accurately to the user's request."


class ExecutionPromptContextService:
    """Resolve current prompt configuration once at the beginning of a run."""

    def __init__(
        self,
        *,
        resolver: EffectivePromptResolver,
        projects: ProjectRepository,
    ) -> None:
        self._resolver = resolver
        self._projects = projects

    def build(
        self,
        context: RunContext | None,
        *,
        runtime_key: str,
        capabilities: Collection[CapabilityName],
    ) -> RunContext:
        """Return an execution context with one resolved set of instruction layers."""
        base = context if context is not None else RunContext()
        try:
            resolved = self._resolver.resolve(
                PromptResolutionContext(
                    conversation_id=base.conversation_id,
                    runtime_key=runtime_key,
                    capabilities=frozenset(item.value for item in capabilities),
                )
            )
            project_instructions: str | None = None
            if resolved.context.project_id is not None:
                project = self._projects.get(resolved.context.project_id)
                if project is None:
                    raise ExecutionPromptContextBuildError(
                        "project_not_found",
                        f"Conversation references missing Project: {resolved.context.project_id}",
                    )
                # Empty and whitespace-only values have no useful execution
                # content. Preserve every non-empty authored character unchanged.
                if project.instructions is not None and project.instructions.strip():
                    project_instructions = project.instructions
        except ExecutionPromptContextBuildError:
            raise
        except PromptResolutionError as exc:
            raise ExecutionPromptContextBuildError(exc.error_code, str(exc)) from exc
        except Exception as exc:
            raise ExecutionPromptContextBuildError(
                "execution_prompt_context_unavailable",
                "Could not read the current execution prompt context.",
            ) from exc

        core_prompts: list[ExecutionCorePrompt] = []
        for item in resolved.enabled_prompts:
            if item.winning_scope_type is None or item.winning_assignment_mode != CorePromptAssignmentMode.ENABLE:
                # The resolver's enabled collection guarantees this. Keep a
                # defensive failure here rather than emitting an untraceable
                # or disabled layer if that invariant ever changes.
                raise ExecutionPromptContextBuildError(
                    "effective_prompt_resolution_invalid",
                    f"Enabled CORE prompt has no winning ENABLE assignment: {item.core_prompt_id}",
                )
            core_prompts.append(
                ExecutionCorePrompt(
                    id=item.core_prompt_id,
                    name=item.name,
                    category=item.category,
                    prompt_text=item.prompt_text,
                    winning_scope_type=item.winning_scope_type,
                    winning_scope_id=item.winning_scope_id,
                )
            )

        layers = ExecutionPromptLayers(
            root_system_prompt=AVA_ROOT_SYSTEM_PROMPT,
            resolved_core_prompts=core_prompts,
            project_instructions=project_instructions,
        )
        logger.debug(
            "Resolved execution prompt context for conversation %s: core_prompt_ids=%s, "
            "project_instructions_present=%s",
            resolved.context.conversation_id,
            [item.id for item in core_prompts],
            project_instructions is not None,
        )
        return base.model_copy(update={"prompt_layers": layers})
