"""Settings service: manage AVA's persisted configuration (Phase 5.10).

One service covers the four persisted configuration domains because they are
validated against each other — a model configuration must name an existing
provider connection, and the defaults record must name three existing, enabled
records that agree with each other. Keeping those rules in one place is the
point; the repositories remain the authority for the write itself.

Scope boundary: this service only *manages configuration*. It resolves no
credential, constructs no provider, and is not consulted by run execution.
``RunService`` and the execution path stay independent of everything here until
Phase 5.16.

Two rules the service enforces on behalf of the HTTP layer:

* **Identity is server-owned.** ``provider_id`` (provider connection),
  ``provider_connection_id`` (model), and ``runtime_type`` (runtime) are
  immutable once a record exists. Update requests do not carry them, and the
  service rejects any attempt to change them rather than letting a client
  silently re-point configured identity at a different adapter or deployment.
* **A credential reference is a location, not a secret.** It is validated for
  syntax using the Phase 5.9 parser and persisted as-is. Whether the named
  secret resolves is never checked here: saving configuration and testing
  availability are separate concerns, and transient backend state must not
  decide whether configuration is valid.
"""

from __future__ import annotations

from ava.configuration.execution_defaults import ApplicationExecutionDefaults
from ava.contracts.settings import (
    ApplicationExecutionDefaultsResponse,
    ApplicationExecutionDefaultsState,
    CreateModelConfigurationRequest,
    CreateProviderConnectionRequest,
    CreateRuntimeConfigurationRequest,
    ModelConfigurationListResponse,
    ModelConfigurationResponse,
    ProviderConnectionListResponse,
    ProviderConnectionResponse,
    RuntimeConfigurationListResponse,
    RuntimeConfigurationResponse,
    SetApplicationExecutionDefaultsRequest,
    UpdateModelConfigurationRequest,
    UpdateProviderConnectionRequest,
    UpdateRuntimeConfigurationRequest,
)
from ava.models.credentials import CredentialReference, CredentialReferenceError
from ava.models.model_configurations import ModelConfiguration
from ava.models.provider_connections import ProviderConnection
from ava.repositories.execution_defaults_repository import ExecutionDefaultsRepository
from ava.repositories.model_configuration_repository import ModelConfigurationRepository
from ava.repositories.provider_connection_repository import ProviderConnectionRepository
from ava.repositories.runtime_configuration_repository import RuntimeConfigurationRepository
from ava.runtimes.configurations import RuntimeConfiguration

# Per domain, the field that is fixed after creation. The update contracts carry
# it as an optional echo rather than an editable value: omitting it preserves the
# association, resending the current value is accepted, and anything else is a
# conflict. `_require_unchanged` states that rule once for all three.
_PROVIDER_CONNECTION_FIXED = "provider_id"
_MODEL_FIXED = "provider_connection_id"
_RUNTIME_FIXED = "runtime_type"


def _require_unchanged(fixed_field: str, current: str, supplied: str | None) -> None:
    """Reject an attempt to change a field that is fixed after creation.

    ``None`` means the client omitted the field, which preserves the stored
    value. Supplying the current value is a no-op and stays valid, so a client
    that round-trips a full record is not punished for it.
    """
    if supplied is not None and supplied != current:
        raise ImmutableSettingsFieldError(f"{fixed_field} cannot change")


# ============================================================
# BEGIN: Errors
# ============================================================


class SettingsError(Exception):
    """Base for AVA-owned Settings failures. Messages never carry secrets."""


class DuplicateSettingsRecordError(SettingsError):
    """A record with the requested identity already exists."""


class UnknownSettingsRecordError(SettingsError):
    """No record exists with the requested identity."""


class ImmutableSettingsFieldError(SettingsError):
    """An update attempted to change a field that is fixed after creation."""


class InvalidSettingsError(SettingsError):
    """A value was rejected by the domain or a referenced record is unusable."""


# ============================================================
# END: Errors
# ============================================================


class SettingsService:
    """Read and write AVA's persisted configuration."""

    def __init__(
        self,
        *,
        provider_connections: ProviderConnectionRepository,
        models: ModelConfigurationRepository,
        runtimes: RuntimeConfigurationRepository,
        execution_defaults: ExecutionDefaultsRepository,
    ) -> None:
        self._provider_connections = provider_connections
        self._models = models
        self._runtimes = runtimes
        self._execution_defaults = execution_defaults

    # ========================================================
    # BEGIN: Provider Connections
    # ========================================================

    def list_provider_connections(self) -> ProviderConnectionListResponse:
        """Return every configured connection, disabled ones included."""
        return ProviderConnectionListResponse(
            provider_connections=[
                _connection_to_response(connection) for connection in self._provider_connections.list()
            ]
        )

    def get_provider_connection(self, provider_connection_id: str) -> ProviderConnectionResponse:
        connection = self._provider_connections.get(provider_connection_id)
        if connection is None:
            raise UnknownSettingsRecordError(f"Unknown provider connection: {provider_connection_id}")
        return _connection_to_response(connection)

    def create_provider_connection(self, body: CreateProviderConnectionRequest) -> ProviderConnectionResponse:
        """Persist a new connection after validating its credential reference."""
        if self._provider_connections.get(body.provider_connection_id) is not None:
            raise DuplicateSettingsRecordError(f"Provider connection already exists: {body.provider_connection_id}")
        credential_reference = _validated_credential_reference(body.credential_reference)
        try:
            connection = ProviderConnection(
                provider_connection_id=body.provider_connection_id,
                provider_id=body.provider_id,
                display_name=body.display_name,
                endpoint=body.endpoint,
                enabled=body.enabled,
                credential_reference=credential_reference,
            )
            return _connection_to_response(self._provider_connections.create(connection))
        except ValueError as exc:
            raise InvalidSettingsError(str(exc)) from exc

    def update_provider_connection(
        self, provider_connection_id: str, body: UpdateProviderConnectionRequest
    ) -> ProviderConnectionResponse:
        """Replace a connection's mutable fields, preserving its provider association."""
        current = self._provider_connections.get(provider_connection_id)
        if current is None:
            raise UnknownSettingsRecordError(f"Unknown provider connection: {provider_connection_id}")
        _require_unchanged(
            f"Provider connection {_PROVIDER_CONNECTION_FIXED}",
            current.provider_id,
            body.provider_id,
        )
        credential_reference = _validated_credential_reference(body.credential_reference)
        try:
            updated = ProviderConnection(
                provider_connection_id=provider_connection_id,
                provider_id=current.provider_id,
                display_name=body.display_name,
                endpoint=body.endpoint,
                enabled=body.enabled,
                credential_reference=credential_reference,
            )
            result = self._provider_connections.update(updated)
        except ValueError as exc:
            raise InvalidSettingsError(str(exc)) from exc
        if result is None:
            raise UnknownSettingsRecordError(f"Unknown provider connection: {provider_connection_id}")
        return _connection_to_response(result)

    # ========================================================
    # END: Provider Connections
    # ========================================================

    # ========================================================
    # BEGIN: Model Configurations
    # ========================================================

    def list_model_configurations(self) -> ModelConfigurationListResponse:
        """Return every configured model, disabled ones included."""
        return ModelConfigurationListResponse(models=[_model_to_response(model) for model in self._models.list()])

    def get_model_configuration(self, model_id: str) -> ModelConfigurationResponse:
        model = self._models.get(model_id)
        if model is None:
            raise UnknownSettingsRecordError(f"Unknown model configuration: {model_id}")
        return _model_to_response(model)

    def create_model_configuration(self, body: CreateModelConfigurationRequest) -> ModelConfigurationResponse:
        """Persist a new model configuration against an existing connection."""
        if self._models.get(body.model_id) is not None:
            raise DuplicateSettingsRecordError(f"Model configuration already exists: {body.model_id}")
        self._require_provider_connection(body.provider_connection_id)
        try:
            model = ModelConfiguration(
                model_id=body.model_id,
                provider_connection_id=body.provider_connection_id,
                provider_model_name=body.provider_model_name,
                display_name=body.display_name,
                hosting_mode=body.hosting_mode,
                capabilities=body.capabilities,
                enabled=body.enabled,
            )
            return _model_to_response(self._models.create(model))
        except ValueError as exc:
            raise InvalidSettingsError(str(exc)) from exc

    def update_model_configuration(
        self, model_id: str, body: UpdateModelConfigurationRequest
    ) -> ModelConfigurationResponse:
        """Replace a model's mutable fields, preserving its connection association."""
        current = self._models.get(model_id)
        if current is None:
            raise UnknownSettingsRecordError(f"Unknown model configuration: {model_id}")
        _require_unchanged(
            f"Model configuration {_MODEL_FIXED}",
            current.provider_connection_id,
            body.provider_connection_id,
        )
        try:
            updated = ModelConfiguration(
                model_id=model_id,
                provider_connection_id=current.provider_connection_id,
                provider_model_name=body.provider_model_name,
                display_name=body.display_name,
                hosting_mode=body.hosting_mode,
                capabilities=body.capabilities,
                enabled=body.enabled,
            )
            result = self._models.update(updated)
        except ValueError as exc:
            raise InvalidSettingsError(str(exc)) from exc
        if result is None:
            raise UnknownSettingsRecordError(f"Unknown model configuration: {model_id}")
        return _model_to_response(result)

    # ========================================================
    # END: Model Configurations
    # ========================================================

    # ========================================================
    # BEGIN: Runtime Configurations
    # ========================================================

    def list_runtime_configurations(self) -> RuntimeConfigurationListResponse:
        """Return every configured runtime, disabled ones included."""
        return RuntimeConfigurationListResponse(
            runtimes=[_runtime_to_response(runtime) for runtime in self._runtimes.list()]
        )

    def get_runtime_configuration(self, runtime_configuration_id: str) -> RuntimeConfigurationResponse:
        runtime = self._runtimes.get(runtime_configuration_id)
        if runtime is None:
            raise UnknownSettingsRecordError(f"Unknown runtime configuration: {runtime_configuration_id}")
        return _runtime_to_response(runtime)

    def create_runtime_configuration(self, body: CreateRuntimeConfigurationRequest) -> RuntimeConfigurationResponse:
        """Persist a new runtime configuration.

        ``runtime_type`` is not checked against installed runtimes and the
        registry is never touched: persisted configuration and runtime
        discovery are separate concerns.
        """
        if self._runtimes.get(body.runtime_configuration_id) is not None:
            raise DuplicateSettingsRecordError(f"Runtime configuration already exists: {body.runtime_configuration_id}")
        try:
            runtime = RuntimeConfiguration(
                runtime_configuration_id=body.runtime_configuration_id,
                runtime_type=body.runtime_type,
                display_name=body.display_name,
                enabled=body.enabled,
            )
            return _runtime_to_response(self._runtimes.create(runtime))
        except ValueError as exc:
            raise InvalidSettingsError(str(exc)) from exc

    def update_runtime_configuration(
        self, runtime_configuration_id: str, body: UpdateRuntimeConfigurationRequest
    ) -> RuntimeConfigurationResponse:
        """Replace a runtime's mutable fields, preserving its adapter type."""
        current = self._runtimes.get(runtime_configuration_id)
        if current is None:
            raise UnknownSettingsRecordError(f"Unknown runtime configuration: {runtime_configuration_id}")
        _require_unchanged(f"Runtime configuration {_RUNTIME_FIXED}", current.runtime_type, body.runtime_type)
        try:
            updated = RuntimeConfiguration(
                runtime_configuration_id=runtime_configuration_id,
                runtime_type=current.runtime_type,
                display_name=body.display_name,
                enabled=body.enabled,
            )
            result = self._runtimes.update(updated)
        except ValueError as exc:
            raise InvalidSettingsError(str(exc)) from exc
        if result is None:
            raise UnknownSettingsRecordError(f"Unknown runtime configuration: {runtime_configuration_id}")
        return _runtime_to_response(result)

    # ========================================================
    # END: Runtime Configurations
    # ========================================================

    # ========================================================
    # BEGIN: Application Execution Defaults
    # ========================================================

    def get_execution_defaults(self) -> ApplicationExecutionDefaultsState:
        """Return the current defaults, or an explicit unconfigured state."""
        defaults = self._execution_defaults.get()
        if defaults is None:
            return ApplicationExecutionDefaultsState(configured=False)
        return ApplicationExecutionDefaultsState(configured=True, defaults=_defaults_to_response(defaults))

    def set_execution_defaults(self, body: SetApplicationExecutionDefaultsRequest) -> ApplicationExecutionDefaultsState:
        """Replace the one defaults record, enforcing every Phase 5.8 rule.

        Existence, enabled state, and the model/connection association are
        validated by the repository, so those rules are not re-implemented here
        and cannot drift between the in-memory and relational stores.
        """
        try:
            saved = self._execution_defaults.set(
                ApplicationExecutionDefaults(
                    default_provider_connection_id=body.default_provider_connection_id,
                    default_model_id=body.default_model_id,
                    default_runtime_configuration_id=body.default_runtime_configuration_id,
                )
            )
        except ValueError as exc:
            raise InvalidSettingsError(str(exc)) from exc
        return ApplicationExecutionDefaultsState(configured=True, defaults=_defaults_to_response(saved))

    # ========================================================
    # END: Application Execution Defaults
    # ========================================================

    def _require_provider_connection(self, provider_connection_id: str) -> None:
        """Fail when a model names a connection that is not configured."""
        if self._provider_connections.get(provider_connection_id) is None:
            raise InvalidSettingsError(f"Unknown provider connection: {provider_connection_id}")


# ============================================================
# BEGIN: Mapping
# ============================================================


def _validated_credential_reference(reference: str | None) -> str | None:
    """Validate credential-reference syntax, returning the canonical text.

    Only syntax is checked. The reference must *parse*; the secret it names need
    not exist yet, so an operator can save configuration before provisioning the
    secret and a transient backend outage never invalidates stored settings.
    """
    if reference is None:
        return None
    try:
        return CredentialReference.parse(reference).text()
    except CredentialReferenceError as exc:
        raise InvalidSettingsError(f"Invalid credential reference: {exc}") from exc


def _connection_to_response(connection: ProviderConnection) -> ProviderConnectionResponse:
    return ProviderConnectionResponse(
        provider_connection_id=connection.provider_connection_id,
        provider_id=connection.provider_id,
        display_name=connection.display_name,
        endpoint=connection.endpoint,
        enabled=connection.enabled,
        credential_reference=connection.credential_reference,
    )


def _model_to_response(model: ModelConfiguration) -> ModelConfigurationResponse:
    return ModelConfigurationResponse(
        model_id=model.model_id,
        provider_connection_id=model.provider_connection_id,
        provider_model_name=model.provider_model_name,
        display_name=model.display_name,
        hosting_mode=model.hosting_mode,
        capabilities=model.capabilities,
        enabled=model.enabled,
    )


def _runtime_to_response(runtime: RuntimeConfiguration) -> RuntimeConfigurationResponse:
    return RuntimeConfigurationResponse(
        runtime_configuration_id=runtime.runtime_configuration_id,
        runtime_type=runtime.runtime_type,
        display_name=runtime.display_name,
        enabled=runtime.enabled,
    )


def _defaults_to_response(
    defaults: ApplicationExecutionDefaults,
) -> ApplicationExecutionDefaultsResponse:
    return ApplicationExecutionDefaultsResponse(
        default_provider_connection_id=defaults.default_provider_connection_id,
        default_model_id=defaults.default_model_id,
        default_runtime_configuration_id=defaults.default_runtime_configuration_id,
    )


# ============================================================
# END: Mapping
# ============================================================
