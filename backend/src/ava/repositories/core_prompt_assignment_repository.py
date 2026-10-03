"""Persistence port for explicit scoped CORE prompt assignments."""

from abc import ABC, abstractmethod
from collections.abc import Collection

from ava.repositories.core_prompt_assignment import (
    CorePromptAssignmentRecord,
    CorePromptScopeType,
)


class CorePromptAssignmentRepository(ABC):
    @abstractmethod
    def get_explicit(
        self, core_prompt_id: str, scope_type: CorePromptScopeType, scope_id: str | None
    ) -> CorePromptAssignmentRecord | None: ...

    @abstractmethod
    def list_for_prompt(self, core_prompt_id: str) -> Collection[CorePromptAssignmentRecord]: ...

    @abstractmethod
    def list_for_scope(
        self, scope_type: CorePromptScopeType, scope_id: str | None
    ) -> Collection[CorePromptAssignmentRecord]: ...

    @abstractmethod
    def upsert_explicit(self, assignment: CorePromptAssignmentRecord) -> CorePromptAssignmentRecord: ...

    @abstractmethod
    def delete_explicit(self, core_prompt_id: str, scope_type: CorePromptScopeType, scope_id: str | None) -> bool: ...

    @abstractmethod
    def delete_for_prompt(self, core_prompt_id: str) -> int: ...

    @abstractmethod
    def delete_for_scope(self, scope_type: CorePromptScopeType, scope_id: str) -> int: ...
