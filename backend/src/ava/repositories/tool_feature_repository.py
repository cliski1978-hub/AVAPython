from abc import ABC, abstractmethod

from ava.contracts.tool_features import ToolFeatureConfiguration


class ToolFeatureConflictError(ValueError):
    """Expected configuration version no longer matches durable state."""


class ToolFeatureRepository(ABC):
    @abstractmethod
    def get(self) -> ToolFeatureConfiguration | None: ...

    @abstractmethod
    def compare_and_set(self, expected_version: int, configuration: ToolFeatureConfiguration) -> None:
        """Atomically replace only the expected version; absent state is version 0."""
        ...
