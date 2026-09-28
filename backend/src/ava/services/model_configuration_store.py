"""In-memory model-configuration repository implementation."""

from ava.models.model_configurations import ModelConfiguration
from ava.repositories.model_configuration_repository import ModelConfigurationRepository
from ava.repositories.provider_connection_repository import ProviderConnectionRepository


class ModelConfigurationStore(ModelConfigurationRepository):
    """Memory store with the same integrity and ordering semantics as SQLite."""

    def __init__(self, *, provider_connections: ProviderConnectionRepository) -> None:
        self._provider_connections = provider_connections
        self._configurations: dict[str, ModelConfiguration] = {}

    def create(self, configuration: ModelConfiguration) -> ModelConfiguration:
        if configuration.model_id in self._configurations:
            raise ValueError(f"Model configuration already exists: {configuration.model_id}")
        self._require_provider_connection(configuration.provider_connection_id)
        self._configurations[configuration.model_id] = configuration
        return configuration

    def get(self, model_id: str) -> ModelConfiguration | None:
        return self._configurations.get(model_id)

    def list(self) -> list[ModelConfiguration]:
        return list(self._configurations.values())

    def update(self, configuration: ModelConfiguration) -> ModelConfiguration | None:
        existing = self._configurations.get(configuration.model_id)
        if existing is None:
            return None
        if existing.provider_connection_id != configuration.provider_connection_id:
            raise ValueError("Model configuration provider_connection_id cannot change")
        self._configurations[configuration.model_id] = configuration
        return configuration

    def _require_provider_connection(self, provider_connection_id: str) -> None:
        if self._provider_connections.get(provider_connection_id) is None:
            raise ValueError(f"Unknown provider connection: {provider_connection_id}")
