"""In-memory runtime-configuration repository implementation."""

from ava.repositories.runtime_configuration_repository import RuntimeConfigurationRepository
from ava.runtimes.configurations import RuntimeConfiguration


class RuntimeConfigurationStore(RuntimeConfigurationRepository):
    """In-memory runtime configurations with relationally compatible semantics."""

    def __init__(self) -> None:
        self._configurations: dict[str, RuntimeConfiguration] = {}

    def create(self, configuration: RuntimeConfiguration) -> RuntimeConfiguration:
        configuration_id = configuration.runtime_configuration_id
        if configuration_id in self._configurations:
            raise ValueError(f"Runtime configuration already exists: {configuration_id}")
        self._configurations[configuration_id] = configuration
        return configuration

    def get(self, runtime_configuration_id: str) -> RuntimeConfiguration | None:
        return self._configurations.get(runtime_configuration_id)

    def list(self) -> list[RuntimeConfiguration]:
        return list(self._configurations.values())

    def update(self, configuration: RuntimeConfiguration) -> RuntimeConfiguration | None:
        existing = self._configurations.get(configuration.runtime_configuration_id)
        if existing is None:
            return None
        if configuration.runtime_type != existing.runtime_type:
            raise ValueError("Runtime configuration runtime_type cannot change")
        self._configurations[configuration.runtime_configuration_id] = configuration
        return configuration
