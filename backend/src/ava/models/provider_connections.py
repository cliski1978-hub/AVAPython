"""AVA-owned configured provider-connection domain.

A provider is an adapter/type that implements ``ModelProviderPort``. A
``ProviderConnection`` is one configured deployment handled by that adapter.
The record is intentionally descriptive: it carries no SDK object, credential
value, model identity, runtime selection, or execution behavior.
"""

from dataclasses import dataclass


def _require_text(name: str, value: str | None) -> None:
    if value is None or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")


@dataclass(frozen=True)
class ProviderConnection:
    """One configured deployment handled by a provider adapter/type.

    ``provider_id`` identifies the provider implementation, while
    ``provider_connection_id`` identifies this configured deployment. Endpoint
    and credential-reference strings are deliberately opaque: transport and
    secret-backend semantics remain adapter/infrastructure concerns.
    """

    provider_connection_id: str
    provider_id: str
    display_name: str
    endpoint: str | None = None
    enabled: bool = True
    credential_reference: str | None = None

    def __post_init__(self) -> None:
        _require_text("provider_connection_id", self.provider_connection_id)
        _require_text("provider_id", self.provider_id)
        _require_text("display_name", self.display_name)
        if self.provider_connection_id == self.provider_id:
            raise ValueError("provider_connection_id must be distinct from provider_id")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")
        if self.endpoint is not None:
            _require_text("endpoint", self.endpoint)
        if self.credential_reference is not None:
            _require_text("credential_reference", self.credential_reference)
