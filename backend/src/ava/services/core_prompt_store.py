"""In-memory repository adapter for CORE prompt definitions."""

from dataclasses import replace
from datetime import datetime

from ava.repositories.core_prompt import CorePromptRecord
from ava.repositories.core_prompt_assignment_repository import CorePromptAssignmentRepository
from ava.repositories.core_prompt_repository import CorePromptRepository


class CorePromptStore(CorePromptRepository):
    """Memory implementation preserving complete prompt snapshots exactly."""

    def __init__(self, assignments: CorePromptAssignmentRepository | None = None) -> None:
        self._prompts: dict[str, CorePromptRecord] = {}
        self._assignments = assignments

    def create(self, prompt: CorePromptRecord) -> CorePromptRecord:
        if prompt.id in self._prompts:
            raise ValueError(f"CORE prompt {prompt.id!r} already exists")
        self._prompts[prompt.id] = prompt
        return prompt

    def get(self, core_prompt_id: str) -> CorePromptRecord | None:
        return self._prompts.get(core_prompt_id)

    def list(self) -> list[CorePromptRecord]:
        return sorted(
            self._prompts.values(),
            key=lambda item: (item.category.value, item.name.casefold(), item.created_at, item.id),
        )

    def update(self, prompt: CorePromptRecord) -> CorePromptRecord | None:
        current = self._prompts.get(prompt.id)
        if current is None:
            return None
        updated = replace(
            prompt,
            id=current.id,
            created_at=current.created_at,
            is_enabled=current.is_enabled,
        )
        self._prompts[prompt.id] = updated
        return updated

    def set_enabled(self, core_prompt_id: str, is_enabled: bool, updated_at: datetime) -> CorePromptRecord | None:
        current = self.get(core_prompt_id)
        if current is None:
            return None
        if current.is_enabled == is_enabled:
            return current
        updated = replace(current, is_enabled=is_enabled, updated_at=updated_at)
        self._prompts[core_prompt_id] = updated
        return updated

    def delete(self, core_prompt_id: str) -> bool:
        if core_prompt_id not in self._prompts:
            return False
        if self._assignments is not None:
            self._assignments.delete_for_prompt(core_prompt_id)
        del self._prompts[core_prompt_id]
        return True
