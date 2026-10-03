"""Read-only resolution of effective CORE prompts for an AVA context.

Resolution is deliberately separate from execution injection. It reads the
canonical conversation membership and applicable assignments, then returns
structured prompt snapshots with provenance.
"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from ava.contracts.capabilities import CapabilityName
from ava.repositories.conversation_repository import ConversationRepository
from ava.repositories.core_prompt import CorePromptCategory, CorePromptRecord
from ava.repositories.core_prompt_assignment import (
    CorePromptAssignmentMode,
    CorePromptAssignmentRecord,
    CorePromptScopeType,
)
from ava.repositories.core_prompt_assignment_repository import CorePromptAssignmentRepository
from ava.repositories.core_prompt_repository import CorePromptRepository


class PromptResolutionError(Exception):
    """A supplied resolution context refers to an invalid target."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


class EffectivePromptState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class PromptResolutionContext:
    """Caller-provided execution identities; project/folder come from Conversation."""

    conversation_id: str | None = None
    runtime_key: str | None = None
    capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ResolvedPromptContext:
    """Canonical context actually used to resolve assignments."""

    conversation_id: str | None
    project_id: str | None
    folder_id: str | None
    runtime_key: str | None
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedCorePrompt:
    core_prompt_id: str
    name: str
    category: CorePromptCategory
    prompt_text: str
    effective_state: EffectivePromptState
    definition_enabled: bool
    reason: str
    winning_scope_type: CorePromptScopeType | None
    winning_scope_id: str | None
    winning_assignment_mode: CorePromptAssignmentMode | None
    winning_assignment_id: str | None


@dataclass(frozen=True)
class EffectivePromptSet:
    context: ResolvedPromptContext
    enabled_prompts: tuple[ResolvedCorePrompt, ...]
    excluded_prompts: tuple[ResolvedCorePrompt, ...]


_SCOPE_PRECEDENCE: tuple[CorePromptScopeType, ...] = (
    CorePromptScopeType.GLOBAL,
    CorePromptScopeType.RUNTIME,
    CorePromptScopeType.CAPABILITY,
    CorePromptScopeType.PROJECT,
    CorePromptScopeType.FOLDER,
    CorePromptScopeType.CONVERSATION,
)
_SCOPE_RANK = {scope: rank for rank, scope in enumerate(_SCOPE_PRECEDENCE)}


class EffectivePromptResolver:
    """Resolve each enabled definition using nearest explicit scope assignment."""

    def __init__(
        self,
        *,
        prompts: CorePromptRepository,
        assignments: CorePromptAssignmentRepository,
        conversations: ConversationRepository,
        runtime_ids: Collection[str],
    ) -> None:
        self._prompts = prompts
        self._assignments = assignments
        self._conversations = conversations
        self._runtime_ids = frozenset(runtime_ids)

    def resolve(self, context: PromptResolutionContext) -> EffectivePromptSet:
        canonical = self._canonical_context(context)
        applicable: list[tuple[CorePromptScopeType, str | None, Collection[CorePromptAssignmentRecord]]] = [
            (CorePromptScopeType.GLOBAL, None, self._assignments.list_for_scope(CorePromptScopeType.GLOBAL, None))
        ]
        if canonical.runtime_key is not None:
            applicable.append(
                (
                    CorePromptScopeType.RUNTIME,
                    canonical.runtime_key,
                    self._assignments.list_for_scope(CorePromptScopeType.RUNTIME, canonical.runtime_key),
                )
            )
        for capability in canonical.capabilities:
            applicable.append(
                (
                    CorePromptScopeType.CAPABILITY,
                    capability,
                    self._assignments.list_for_scope(CorePromptScopeType.CAPABILITY, capability),
                )
            )
        if canonical.project_id is not None:
            applicable.append(
                (
                    CorePromptScopeType.PROJECT,
                    canonical.project_id,
                    self._assignments.list_for_scope(CorePromptScopeType.PROJECT, canonical.project_id),
                )
            )
        if canonical.folder_id is not None:
            applicable.append(
                (
                    CorePromptScopeType.FOLDER,
                    canonical.folder_id,
                    self._assignments.list_for_scope(CorePromptScopeType.FOLDER, canonical.folder_id),
                )
            )
        if canonical.conversation_id is not None:
            applicable.append(
                (
                    CorePromptScopeType.CONVERSATION,
                    canonical.conversation_id,
                    self._assignments.list_for_scope(CorePromptScopeType.CONVERSATION, canonical.conversation_id),
                )
            )

        assignments_by_prompt: dict[str, list[CorePromptAssignmentRecord]] = {}
        for _, _, records in applicable:
            for record in records:
                # Stale/deleted targets are ignored by only considering scopes explicitly loaded above.
                assignments_by_prompt.setdefault(record.core_prompt_id, []).append(record)

        resolved = [
            self._resolve_one(prompt, assignments_by_prompt.get(prompt.id, [])) for prompt in self._prompts.list()
        ]
        enabled = [item for item in resolved if item.effective_state == EffectivePromptState.ENABLED]
        excluded = [item for item in resolved if item.effective_state == EffectivePromptState.DISABLED]
        enabled.sort(key=self._ordering_key)
        excluded.sort(key=self._ordering_key)
        return EffectivePromptSet(canonical, tuple(enabled), tuple(excluded))

    def _canonical_context(self, context: PromptResolutionContext) -> ResolvedPromptContext:
        if context.runtime_key is not None and context.runtime_key not in self._runtime_ids:
            raise PromptResolutionError("runtime_not_found", f"Unknown runtime registry key: {context.runtime_key}")
        capabilities: set[str] = set()
        for value in context.capabilities:
            try:
                capabilities.add(CapabilityName(value).value)
            except ValueError as exc:
                raise PromptResolutionError("capability_not_found", f"Unknown capability name: {value}") from exc
        conversation_id = context.conversation_id
        project_id = folder_id = None
        if conversation_id is not None:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                raise PromptResolutionError("conversation_not_found", f"Unknown conversation: {conversation_id}")
            project_id, folder_id = conversation.project_id, conversation.folder_id
        return ResolvedPromptContext(
            conversation_id,
            project_id,
            folder_id,
            context.runtime_key,
            tuple(sorted(capabilities)),
        )

    @staticmethod
    def _resolve_one(prompt: CorePromptRecord, records: list[CorePromptAssignmentRecord]) -> ResolvedCorePrompt:
        by_scope: dict[CorePromptScopeType, list[CorePromptAssignmentRecord]] = {}
        for record in records:
            by_scope.setdefault(record.scope_type, []).append(record)
        winner: CorePromptAssignmentRecord | None = None
        for scope in reversed(_SCOPE_PRECEDENCE):
            matches = by_scope.get(scope, [])
            if not matches:
                continue
            # Multiple capability targets are one tier: any DISABLE wins;
            # otherwise choose canonical target order for stable provenance.
            matches.sort(key=lambda item: (item.scope_id or "", item.id))
            winner = next((item for item in matches if item.mode == CorePromptAssignmentMode.DISABLE), matches[0])
            break
        state = EffectivePromptState.DISABLED
        if not prompt.is_enabled:
            reason = "definition_disabled"
        elif winner is None:
            reason = "no_matching_assignment"
        elif winner.mode == CorePromptAssignmentMode.DISABLE:
            reason = "explicit_disable"
        else:
            state, reason = EffectivePromptState.ENABLED, "explicit_enable"
        return ResolvedCorePrompt(
            core_prompt_id=prompt.id,
            name=prompt.name,
            category=prompt.category,
            prompt_text=prompt.prompt_text,
            effective_state=state,
            definition_enabled=prompt.is_enabled,
            reason=reason,
            winning_scope_type=winner.scope_type if winner else None,
            winning_scope_id=winner.scope_id if winner else None,
            winning_assignment_mode=winner.mode if winner else None,
            winning_assignment_id=winner.id if winner else None,
        )

    @staticmethod
    def _ordering_key(prompt: ResolvedCorePrompt) -> tuple[object, ...]:
        return (
            _SCOPE_RANK.get(prompt.winning_scope_type, -1) if prompt.winning_scope_type is not None else -1,
            prompt.category.value,
            prompt.name.casefold(),
            prompt.name,
            prompt.core_prompt_id,
        )
