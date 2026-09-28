"""AVA-owned persistence port for configured models."""

from abc import ABC, abstractmethod
from collections.abc import Collection

from ava.models.model_configurations import ModelConfiguration


class ModelConfigurationRepository(ABC):
    """Store model configurations keyed by stable AVA ``model_id``."""

    @abstractmethod
    def create(self, configuration: ModelConfiguration) -> ModelConfiguration:
        """Create a configuration or raise ``ValueError`` for invalid identity."""
        raise NotImplementedError

    @abstractmethod
    def get(self, model_id: str) -> ModelConfiguration | None:
        """Return a configuration snapshot, or ``None`` if it is unknown."""
        raise NotImplementedError

    @abstractmethod
    def list(self) -> Collection[ModelConfiguration]:
        """Return every configuration in stable insertion order."""
        raise NotImplementedError

    @abstractmethod
    def update(self, configuration: ModelConfiguration) -> ModelConfiguration | None:
        """Replace mutable configuration metadata for an existing model."""
        raise NotImplementedError
