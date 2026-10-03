"""AVA-owned repository port for reusable CORE prompt definitions."""

from abc import ABC, abstractmethod
from collections.abc import Collection
from datetime import datetime

from ava.repositories.core_prompt import CorePromptRecord


class CorePromptRepository(ABC):
    """Persistence operations for reusable prompt definitions."""

    @abstractmethod
    def create(self, prompt: CorePromptRecord) -> CorePromptRecord:
        """Persist a definition; duplicate IDs are rejected."""
        raise NotImplementedError

    @abstractmethod
    def get(self, core_prompt_id: str) -> CorePromptRecord | None:
        """Return a definition, or ``None`` when it does not exist."""
        raise NotImplementedError

    @abstractmethod
    def list(self) -> Collection[CorePromptRecord]:
        """Return definitions in deterministic category/name/creation/ID order."""
        raise NotImplementedError

    @abstractmethod
    def update(self, prompt: CorePromptRecord) -> CorePromptRecord | None:
        """Replace mutable definition fields, or return ``None`` when missing."""
        raise NotImplementedError

    @abstractmethod
    def set_enabled(self, core_prompt_id: str, is_enabled: bool, updated_at: datetime) -> CorePromptRecord | None:
        """Set enabled state and its timestamp, returning ``None`` if missing."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, core_prompt_id: str) -> bool:
        """Permanently delete a definition and report whether it existed."""
        raise NotImplementedError
