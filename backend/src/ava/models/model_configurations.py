"""AVA-owned configured-model domain for later durable settings work.

``ModelConfiguration`` describes one AVA model identity available through one
configured provider connection. It is deliberately distinct from the current
execution-time ``ModelProfile``: this record has a provider-connection
association, while a future composition step will derive a profile and then a
``ConfiguredModelBinding`` after resolving the connection's provider adapter.
"""

from dataclasses import dataclass, field

from ava.contracts.models import ModelCapabilities, ModelHostingMode


def _require_text(name: str, value: str | None) -> None:
    if value is None or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")


@dataclass(frozen=True)
class ModelConfiguration:
    """One configured model exposed through a provider connection.

    ``model_id`` is AVA's stable, provider-neutral identity.
    ``provider_connection_id`` identifies the configured deployment that
    exposes it; endpoint and credential data remain on that connection.
    ``provider_model_name`` is the opaque provider-facing target name.

    Capabilities and the optional AVA context window are declared configuration
    metadata. Provider-reported ``ModelInfo.context_limit`` remains an
    authoritative hard ceiling when available.
    """

    model_id: str
    provider_connection_id: str
    provider_model_name: str
    display_name: str
    hosting_mode: ModelHostingMode
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    enabled: bool = True
    context_window_tokens: int | None = None

    def __post_init__(self) -> None:
        _require_text("model_id", self.model_id)
        _require_text("provider_connection_id", self.provider_connection_id)
        _require_text("provider_model_name", self.provider_model_name)
        _require_text("display_name", self.display_name)
        if self.model_id == self.provider_connection_id:
            raise ValueError("model_id must be distinct from provider_connection_id")
        if self.model_id == self.provider_model_name:
            raise ValueError("model_id must be distinct from provider_model_name")
        if self.provider_connection_id == self.provider_model_name:
            raise ValueError("provider_connection_id must be distinct from provider_model_name")
        if not isinstance(self.hosting_mode, ModelHostingMode):
            raise ValueError("hosting_mode must be a ModelHostingMode")
        if not isinstance(self.capabilities, ModelCapabilities):
            raise ValueError("capabilities must be a ModelCapabilities")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")
        if self.context_window_tokens is not None and (
            not isinstance(self.context_window_tokens, int)
            or isinstance(self.context_window_tokens, bool)
            or self.context_window_tokens <= 0
        ):
            raise ValueError("context_window_tokens must be a positive integer or None")
