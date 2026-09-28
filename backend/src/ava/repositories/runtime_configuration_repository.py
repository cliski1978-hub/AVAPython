"""AVA-owned persistence port for configured agent runtimes."""

from abc import ABC, abstractmethod
from collections.abc import Collection

from ava.runtimes.configurations import RuntimeConfiguration


class RuntimeConfigurationRepository(ABC):
    """Store runtime configurations keyed by stable AVA configuration identity.

    ``runtime_configuration_id`` is the identity of one configured runtime
    instance. It is deliberately distinct from both ``runtime_type`` (the
    adapter/framework kind) and the existing ``RuntimeRegistry`` lookup key
    for already-constructed ``AgentRuntimePort`` implementations. This port
    stores configuration records only: it performs no runtime resolution and
    holds no model, provider, provider-connection, workspace, tool, or
    credential state.
    """

    @abstractmethod
    def create(self, configuration: RuntimeConfiguration) -> RuntimeConfiguration:
        """Create ``configuration`` or raise ``ValueError`` for a duplicate id."""
        raise NotImplementedError

    @abstractmethod
    def get(self, runtime_configuration_id: str) -> RuntimeConfiguration | None:
        """Return the configuration snapshot, or ``None`` when it is unknown."""
        raise NotImplementedError

    @abstractmethod
    def list(self) -> Collection[RuntimeConfiguration]:
        """Return every configuration in stable insertion order."""
        raise NotImplementedError

    @abstractmethod
    def update(self, configuration: RuntimeConfiguration) -> RuntimeConfiguration | None:
        """Replace mutable configuration metadata for an existing instance."""
        raise NotImplementedError
