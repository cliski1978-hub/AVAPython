"""AVA-owned persistence port for configured provider connections."""

from abc import ABC, abstractmethod
from collections.abc import Collection

from ava.models.provider_connections import ProviderConnection


class ProviderConnectionRepository(ABC):
    """Store provider-connection snapshots behind an AVA-owned boundary."""

    @abstractmethod
    def create(self, connection: ProviderConnection) -> ProviderConnection:
        """Create ``connection`` or raise ``ValueError`` for a duplicate id."""
        raise NotImplementedError

    @abstractmethod
    def get(self, provider_connection_id: str) -> ProviderConnection | None:
        """Return the connection snapshot, or ``None`` when it is unknown."""
        raise NotImplementedError

    @abstractmethod
    def list(self) -> Collection[ProviderConnection]:
        """Return every connection in stable insertion order."""
        raise NotImplementedError

    @abstractmethod
    def update(self, connection: ProviderConnection) -> ProviderConnection | None:
        """Replace an existing connection while preserving provider association."""
        raise NotImplementedError
