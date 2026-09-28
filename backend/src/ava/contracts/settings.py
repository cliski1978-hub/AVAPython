"""Wire contracts for the persisted Settings API (Phase 5.10).

These contracts expose AVA's *persisted configuration* — provider connections,
model configurations, runtime configurations, and the application execution
defaults — and are deliberately distinct from the discovery contracts in
``ava.contracts.responses``, which report what is currently available.

Two rules govern everything here:

1. **Configuration metadata only.** ``credential_reference`` is safe
   configuration metadata (it names a location, never a secret) and is exposed.
   Resolved secret material is not: no contract in this module has a field for
   an API key, token, password, or ``SecretValue``, and none may grow one.
2. **No framework or domain types leak.** These are plain Pydantic models.
   They never import ``ava.models``, a repository adapter, a runtime
   implementation, or a vendor SDK, so a client that only knows the contract can
   be generated and consumed without the backend.

Identity is always server-owned and always travels in the path. Update requests
therefore omit the identity field entirely, and the immutable association field
of each domain is never accepted on update.
"""

from pydantic import BaseModel, ConfigDict, Field

from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Provider Connections
# ============================================================


class ProviderConnectionResponse(BaseModel):
    """One configured provider connection as persisted.

    ``credential_reference`` is the opaque location AVA resolves through its
    credential resolver. The resolved secret is never part of this contract.
    """

    provider_connection_id: str
    provider_id: str
    display_name: str
    endpoint: str | None = None
    enabled: bool
    credential_reference: str | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ProviderConnectionListResponse(BaseModel):
    """Every configured provider connection, including disabled ones.

    Settings management needs the full inventory, so nothing is filtered.
    """

    provider_connections: list[ProviderConnectionResponse]
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class CreateProviderConnectionRequest(BaseModel):
    """Payload for ``POST /settings/providers``.

    ``endpoint`` and ``credential_reference`` are optional and nullable: a
    local unauthenticated provider legitimately has neither. A supplied
    ``credential_reference`` is validated for syntax only — whether the named
    secret actually resolves is a separate concern tested elsewhere, never a
    reason to refuse a save.
    """

    # Unknown fields are rejected rather than ignored: silently dropping a
    # misspelled or unsupported field is how a caller would come to believe a
    # secret field, a runtime adapter key, or an execution field was stored.
    model_config = ConfigDict(extra="forbid")

    provider_connection_id: str
    provider_id: str
    display_name: str
    endpoint: str | None = None
    enabled: bool = True
    credential_reference: str | None = None


class UpdateProviderConnectionRequest(BaseModel):
    """Payload for ``PUT /settings/providers/{provider_connection_id}``.

    Carries every mutable field, none optional: this is a full replacement, so
    clearing ``endpoint`` or ``credential_reference`` means sending an explicit
    ``null`` rather than omitting the key.

    ``provider_id`` is optional and *not* a way to reassign a connection. Omit
    it to leave the association untouched, or resend the current value. Any
    other value is rejected with a conflict, because the provider association is
    immutable once a connection exists — a connection is one deployment of one
    provider adapter, and re-pointing it would silently change what every model
    configured against it talks to.
    """

    # Unknown fields are rejected rather than ignored: silently dropping a
    # misspelled or unsupported field is how a caller would come to believe a
    # secret field, a runtime adapter key, or an execution field was stored.
    model_config = ConfigDict(extra="forbid")

    display_name: str
    endpoint: str | None
    enabled: bool
    credential_reference: str | None
    provider_id: str | None = None


# ============================================================
# END: Provider Connections
# ============================================================


# ============================================================
# BEGIN: Model Configurations
# ============================================================


class ModelConfigurationResponse(BaseModel):
    """One configured model as persisted.

    Declared static configuration only. Provider endpoint data stays on the
    connection, and provider-reported discovery metadata (health, context
    limits, qualifications) is not configuration and is not exposed here.
    """

    model_id: str
    provider_connection_id: str
    provider_model_name: str
    display_name: str
    hosting_mode: ModelHostingMode
    capabilities: ModelCapabilities
    enabled: bool
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ModelConfigurationListResponse(BaseModel):
    """Every configured model, including disabled ones."""

    models: list[ModelConfigurationResponse]
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class CreateModelConfigurationRequest(BaseModel):
    """Payload for ``POST /settings/models``.

    The provider connection must already exist; this endpoint never manufactures
    one. ``hosting_mode`` and ``capabilities`` map onto the existing AVA
    vocabulary rather than introducing new spellings.
    """

    # Unknown fields are rejected rather than ignored: silently dropping a
    # misspelled or unsupported field is how a caller would come to believe a
    # secret field, a runtime adapter key, or an execution field was stored.
    model_config = ConfigDict(extra="forbid")

    model_id: str
    provider_connection_id: str
    provider_model_name: str
    display_name: str
    hosting_mode: ModelHostingMode
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    enabled: bool = True


class UpdateModelConfigurationRequest(BaseModel):
    """Payload for ``PUT /settings/models/{model_id}``.

    ``provider_connection_id`` is optional and *not* a way to reassign a model.
    Omit it to leave the association untouched, or resend the current value. Any
    other value is rejected with a conflict, because the model/connection
    association is immutable once a model exists: a configured model must never
    be silently re-pointed at a different deployment, and the application
    defaults record encodes the same association.
    """

    # Unknown fields are rejected rather than ignored: silently dropping a
    # misspelled or unsupported field is how a caller would come to believe a
    # secret field, a runtime adapter key, or an execution field was stored.
    model_config = ConfigDict(extra="forbid")

    provider_model_name: str
    display_name: str
    hosting_mode: ModelHostingMode
    capabilities: ModelCapabilities
    enabled: bool
    provider_connection_id: str | None = None


# ============================================================
# END: Model Configurations
# ============================================================


# ============================================================
# BEGIN: Runtime Configurations
# ============================================================


class RuntimeConfigurationResponse(BaseModel):
    """One configured runtime instance as persisted.

    Configuration identity and adapter type only: no model, provider, registry
    object, ``AgentRuntimePort``, workspace, tool permission, or credential.
    """

    runtime_configuration_id: str
    runtime_type: str
    display_name: str
    enabled: bool
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class RuntimeConfigurationListResponse(BaseModel):
    """Every configured runtime, including disabled ones."""

    runtimes: list[RuntimeConfigurationResponse]
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class CreateRuntimeConfigurationRequest(BaseModel):
    """Payload for ``POST /settings/runtimes``.

    ``runtime_type`` is an opaque adapter/framework kind. It is not validated
    against installed runtimes: configuring a runtime must not depend on
    whether its implementation is present, and the registry is never mutated
    from here.
    """

    # Unknown fields are rejected rather than ignored: silently dropping a
    # misspelled or unsupported field is how a caller would come to believe a
    # secret field, a runtime adapter key, or an execution field was stored.
    model_config = ConfigDict(extra="forbid")

    runtime_configuration_id: str
    runtime_type: str
    display_name: str
    enabled: bool = True


class UpdateRuntimeConfigurationRequest(BaseModel):
    """Payload for ``PUT /settings/runtimes/{runtime_configuration_id}``.

    ``runtime_type`` is optional and *not* a way to retype a runtime. Omit it
    to leave the adapter kind untouched, or resend the current value. Any other
    value is rejected with a conflict: the adapter kind is immutable once a
    runtime configuration exists, so a ``native`` identity can never be
    silently re-pointed at ``openhands``.
    """

    # Unknown fields are rejected rather than ignored: silently dropping a
    # misspelled or unsupported field is how a caller would come to believe a
    # secret field, a runtime adapter key, or an execution field was stored.
    model_config = ConfigDict(extra="forbid")

    display_name: str
    enabled: bool
    runtime_type: str | None = None


# ============================================================
# END: Runtime Configurations
# ============================================================


# ============================================================
# BEGIN: Application Execution Defaults
# ============================================================


class ApplicationExecutionDefaultsResponse(BaseModel):
    """The application's single set of default execution references.

    Every field names a *configured* record. Adapter keys
    (``provider_id``, ``provider_model_name``, ``runtime_type``) and registry
    ids are deliberately absent: defaults reference configuration identity, not
    adapter identity.
    """

    default_provider_connection_id: str
    default_model_id: str
    default_runtime_configuration_id: str
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class ApplicationExecutionDefaultsState(BaseModel):
    """Current defaults plus an explicit configured flag.

    "Not configured yet" is normal application state, not an error, so
    ``GET /settings/defaults`` reports it as ``configured: false`` with a null
    ``defaults`` rather than a 404. A client can render a Settings screen
    without treating a missing resource as a failure.
    """

    configured: bool
    defaults: ApplicationExecutionDefaultsResponse | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class SetApplicationExecutionDefaultsRequest(BaseModel):
    """Payload for ``PUT /settings/defaults``.

    Full replacement of the one defaults record. All three references are
    required and must resolve to existing, enabled records, with the selected
    model belonging to the selected provider connection.
    """

    # Unknown fields are rejected rather than ignored: silently dropping a
    # misspelled or unsupported field is how a caller would come to believe a
    # secret field, a runtime adapter key, or an execution field was stored.
    model_config = ConfigDict(extra="forbid")

    default_provider_connection_id: str
    default_model_id: str
    default_runtime_configuration_id: str


# ============================================================
# END: Application Execution Defaults
# ============================================================
