"""In-memory application-execution-defaults repository implementation."""

from ava.configuration.execution_defaults import (
    ApplicationExecutionDefaults,
    validate_execution_defaults,
)
from ava.repositories.execution_defaults_repository import ExecutionDefaultsRepository
from ava.repositories.model_configuration_repository import ModelConfigurationRepository
from ava.repositories.provider_connection_repository import ProviderConnectionRepository
from ava.repositories.runtime_configuration_repository import RuntimeConfigurationRepository


class ExecutionDefaultsStore(ExecutionDefaultsRepository):
    """No defaults until set; validation semantics match the SQLite adapter."""

    def __init__(
        self,
        *,
        provider_connections: ProviderConnectionRepository,
        model_configurations: ModelConfigurationRepository,
        runtime_configurations: RuntimeConfigurationRepository,
    ) -> None:
        self._provider_connections = provider_connections
        self._model_configurations = model_configurations
        self._runtime_configurations = runtime_configurations
        self._defaults: ApplicationExecutionDefaults | None = None

    def get(self) -> ApplicationExecutionDefaults | None:
        return self._defaults

    def set(self, defaults: ApplicationExecutionDefaults) -> ApplicationExecutionDefaults:
        validate_execution_defaults(
            defaults=defaults,
            provider_connection=self._provider_connections.get(
                defaults.default_provider_connection_id
            ),
            model_configuration=self._model_configurations.get(defaults.default_model_id),
            runtime_configuration=self._runtime_configurations.get(
                defaults.default_runtime_configuration_id
            ),
        )
        self._defaults = defaults
        return defaults
