"""AVA-owned configured-runtime domain for later settings persistence.

The current ``RuntimeRegistry`` maps opaque registry keys to constructed
``AgentRuntimePort`` instances. Those keys currently identify adapter choices,
not independently configured runtime instances, so ``RuntimeConfiguration``
uses a separate stable configuration identity.
"""

from dataclasses import dataclass


def _require_text(name: str, value: str | None) -> None:
    if value is None or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")


@dataclass(frozen=True)
class RuntimeConfiguration:
    """One selectable configured instance of an AVA runtime type.

    ``runtime_configuration_id`` is AVA's stable configuration identity;
    ``runtime_type`` identifies the adapter/framework kind. The record contains
    no model, provider, provider-connection, workspace, tool, or credential
    data. Current Native and OpenHands constructors require only
    composition-owned policy objects, so no runtime-specific configuration bag
    is justified yet.
    """

    runtime_configuration_id: str
    runtime_type: str
    display_name: str
    enabled: bool = True

    def __post_init__(self) -> None:
        _require_text("runtime_configuration_id", self.runtime_configuration_id)
        _require_text("runtime_type", self.runtime_type)
        _require_text("display_name", self.display_name)
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")
