"""In-memory provider-connection repository implementation."""

from ava.models.provider_connections import ProviderConnection
from ava.repositories.provider_connection_repository import ProviderConnectionRepository


class ProviderConnectionStore(ProviderConnectionRepository):
    """In-memory provider connections with relationally compatible semantics."""

    def __init__(self) -> None:
        self._connections: dict[str, ProviderConnection] = {}

    def create(self, connection: ProviderConnection) -> ProviderConnection:
        connection_id = connection.provider_connection_id
        if connection_id in self._connections:
            raise ValueError(f"Provider connection already exists: {connection_id}")
        self._connections[connection_id] = connection
        return connection

    def get(self, provider_connection_id: str) -> ProviderConnection | None:
        return self._connections.get(provider_connection_id)

    def list(self) -> list[ProviderConnection]:
        return list(self._connections.values())

    def update(self, connection: ProviderConnection) -> ProviderConnection | None:
        existing = self._connections.get(connection.provider_connection_id)
        if existing is None:
            return None
        if connection.provider_id != existing.provider_id:
            raise ValueError("Provider connection provider_id cannot change")
        self._connections[connection.provider_connection_id] = connection
        return connection
