"""AVA-owned application execution defaults.

These are *persisted* application configuration: the configured AVA records a
default run should use. They are a fifth, distinct concept alongside the four
default mechanisms AVA already has — see ``AVA_Phase_5_8`` documentation for the
full comparison. Nothing here reads or writes those mechanisms.

Identity rule: defaults reference *configured* identities only
(``default_provider_connection_id``, ``default_model_id``,
``default_runtime_configuration_id``). They never reference a provider adapter
id, a provider-native model name, a runtime type, or a ``RuntimeRegistry``
lookup key, because those describe adapters rather than configured records.
"""

from dataclasses import dataclass

from ava.models.model_configurations import ModelConfiguration
from ava.models.provider_connections import ProviderConnection
from ava.runtimes.configurations import RuntimeConfiguration


def _require_text(name: str, value: str | None) -> None:
    if value is None or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")


@dataclass(frozen=True)
class ApplicationExecutionDefaults:
    """The one application-wide set of default execution selections.

    A deployment has at most one such record. The three fields name configured
    records in the independently persisted provider-connection, model, and
    runtime-configuration domains; they deliberately carry no user, workspace,
    conversation, routing, or permission state.
    """

    default_provider_connection_id: str
    default_model_id: str
    default_runtime_configuration_id: str

    def __post_init__(self) -> None:
        _require_text("default_provider_connection_id", self.default_provider_connection_id)
        _require_text("default_model_id", self.default_model_id)
        _require_text("default_runtime_configuration_id", self.default_runtime_configuration_id)


def validate_execution_defaults(
    *,
    defaults: ApplicationExecutionDefaults,
    provider_connection: ProviderConnection | None,
    model_configuration: ModelConfiguration | None,
    runtime_configuration: RuntimeConfiguration | None,
) -> None:
    """Raise ``ValueError`` unless ``defaults`` names a compatible, enabled trio.

    Three rules, in order:

    1. every referenced configured record must exist
    2. every referenced record must be enabled
    3. the selected model must belong to the selected provider connection

    There is no fallback: a missing, disabled, or incompatible reference is an
    error the caller must see. This function is shared by every repository
    implementation so in-memory and relational semantics cannot drift. It takes
    already-resolved snapshots rather than repositories, keeping the domain
    free of persistence concerns.
    """
    if provider_connection is None:
        raise ValueError(f"Unknown provider connection: {defaults.default_provider_connection_id}")
    if model_configuration is None:
        raise ValueError(f"Unknown model configuration: {defaults.default_model_id}")
    if runtime_configuration is None:
        raise ValueError(
            f"Unknown runtime configuration: {defaults.default_runtime_configuration_id}"
        )
    if not provider_connection.enabled:
        raise ValueError(
            f"Provider connection is disabled: {provider_connection.provider_connection_id}"
        )
    if not model_configuration.enabled:
        raise ValueError(f"Model configuration is disabled: {model_configuration.model_id}")
    if not runtime_configuration.enabled:
        raise ValueError(
            f"Runtime configuration is disabled: {runtime_configuration.runtime_configuration_id}"
        )
    if model_configuration.provider_connection_id != provider_connection.provider_connection_id:
        raise ValueError(
            f"Model configuration {model_configuration.model_id} does not belong to provider "
            f"connection {provider_connection.provider_connection_id}"
        )
