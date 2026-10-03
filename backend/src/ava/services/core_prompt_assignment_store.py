"""In-memory assignment adapter with deterministic SQLite parity."""

from dataclasses import replace

from ava.repositories.core_prompt_assignment import CorePromptAssignmentRecord, CorePromptScopeType
from ava.repositories.core_prompt_assignment_repository import CorePromptAssignmentRepository


class CorePromptAssignmentStore(CorePromptAssignmentRepository):
    def __init__(self) -> None:
        self._items: dict[tuple[str, CorePromptScopeType, str | None], CorePromptAssignmentRecord] = {}

    @staticmethod
    def _key(
        prompt: str, scope: CorePromptScopeType, scope_id: str | None
    ) -> tuple[str, CorePromptScopeType, str | None]:
        return prompt, scope, scope_id

    @staticmethod
    def _order(item: CorePromptAssignmentRecord) -> tuple[str, str, object, str]:
        return item.scope_type.value, item.scope_id or "", item.created_at, item.id

    def get_explicit(
        self, core_prompt_id: str, scope_type: CorePromptScopeType, scope_id: str | None
    ) -> CorePromptAssignmentRecord | None:
        return self._items.get(self._key(core_prompt_id, scope_type, scope_id))

    def list_for_prompt(self, core_prompt_id: str) -> list[CorePromptAssignmentRecord]:
        return sorted((a for a in self._items.values() if a.core_prompt_id == core_prompt_id), key=self._order)

    def list_for_scope(self, scope_type: CorePromptScopeType, scope_id: str | None) -> list[CorePromptAssignmentRecord]:
        return sorted(
            (a for a in self._items.values() if a.scope_type == scope_type and a.scope_id == scope_id), key=self._order
        )

    def upsert_explicit(self, assignment: CorePromptAssignmentRecord) -> CorePromptAssignmentRecord:
        key = self._key(assignment.core_prompt_id, assignment.scope_type, assignment.scope_id)
        old = self._items.get(key)
        if old is not None:
            assignment = replace(assignment, id=old.id, created_at=old.created_at)
        self._items[key] = assignment
        return assignment

    def delete_explicit(self, core_prompt_id: str, scope_type: CorePromptScopeType, scope_id: str | None) -> bool:
        return self._items.pop(self._key(core_prompt_id, scope_type, scope_id), None) is not None

    def delete_for_prompt(self, core_prompt_id: str) -> int:
        keys = [key for key in self._items if key[0] == core_prompt_id]
        for key in keys:
            del self._items[key]
        return len(keys)

    def delete_for_scope(self, scope_type: CorePromptScopeType, scope_id: str) -> int:
        keys = [key for key in self._items if key[1] == scope_type and key[2] == scope_id]
        for key in keys:
            del self._items[key]
        return len(keys)
