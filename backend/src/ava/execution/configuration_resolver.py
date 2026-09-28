"""Persisted execution configuration resolution (Phase 5.16).

This is the AVA-owned bridge from persisted settings into the existing execution
abstractions. It is the *only* place that fans out to the provider-connection,
model-configuration, runtime-configuration, and execution-defaults repositories,
and it is deliberately one place: callers must not manually assemble the four related records. The ports do not
provide a cross-repository transaction; these are read-time snapshots.

The audit that motivated this module found the production path to be:

    RunService
      -> AgentPort (NativeAgentAdapter)
        -> ExecutionSelector.resolve()
          -> RuntimeResolver.resolve(runtime_id)
          -> ModelProviderResolver.resolve(profile.provider_id)
          -> model_binding_from_profile(profile)
        -> ExecutionCompatibilityValidator
        -> ModelResourceManager.acquire(profile.model_id)
        -> AgentRuntimePort.execute(model_provider=..., model_binding=...)

Every one of those steps is correct and stays. This module changes exactly one
thing: where the *inputs* come from. ``ExecutionSelector`` keeps its bootstrap
defaults, and gains an optional resolver that supplies a fully validated
selection when persisted defaults exist.

The two identity mappings that matter, and which are easy to get backwards:

    runtime_configuration_id  -> persisted configured-instance identity
    runtime_type              -> RuntimeRegistry lookup key

The registry is keyed by adapter kind — composition registers ``"native"`` and
``"openhands"`` — so the *configuration id* is never passed to it. Symmetrically
``provider_connection_id`` is the configured deployment and
``ProviderConnection.provider_id`` is the adapter type the factory is asked for.

Read-time validation is not optional. ``set`` validated existence, enablement,
and the model/provider pairing *at write time*, and every one of those can
change afterwards. Trusting a previously-valid default would execute against a
record that no longer qualifies, so all three are rechecked here and any failure
raises. There is no substitution and no partial fallback: an explicitly
configured but broken setup must fail rather than quietly run on something else.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ava.configuration.execution_defaults import ApplicationExecutionDefaults
from ava.execution.hosting import ModelHostingRequirement
from ava.execution.model_orchestrator import ModelOrchestrator, ModelSelectionError, ModelSelectionRequest
from ava.execution.persisted_execution import (
    ConfiguredModelIneligibleError,
    ConfiguredReferenceDisabledError,
    ConfiguredReferenceMissingError,
    CredentialResolutionFailedError,
    ExecutionDefaultsNotConfiguredError,
    ModelProviderMismatchError,
    PersistedExecutionConfiguration,
    ProviderAdapterNotRegisteredError,
    ProviderConstructionFailedError,
    RuntimeAdapterNotRegisteredError,
)
from ava.models.bindings import model_binding_from_profile
from ava.models.contracts import ModelProviderPort
from ava.models.credentials import (
    CredentialError,
    CredentialResolver,
    SecretValue,
    resolve_connection_credential,
)
from ava.models.model_configurations import ModelConfiguration
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.provider_connections import ProviderConnection
from ava.models.provider_factory import ModelProviderFactory, UnknownProviderAdapterError
from ava.repositories.execution_defaults_repository import ExecutionDefaultsRepository
from ava.repositories.model_configuration_repository import ModelConfigurationRepository
from ava.repositories.provider_connection_repository import ProviderConnectionRepository
from ava.repositories.runtime_configuration_repository import RuntimeConfigurationRepository
from ava.runtimes.configurations import RuntimeConfiguration
from ava.runtimes.contracts import AgentRuntimePort
from ava.runtimes.resolver import RuntimeResolver, UnknownRuntimeError

logger = logging.getLogger(__name__)

#: The three configured domains, named for error reporting only.
_PROVIDER_CONNECTION = "provider connection"
_MODEL_CONFIGURATION = "model configuration"
_RUNTIME_CONFIGURATION = "runtime configuration"


@dataclass(frozen=True)
class ConfigurationRepositories:
    """The four persisted configuration repositories, as one injected bundle.

    Resolution needs all four at once and always reads them together, so they
    are passed as one value rather than as four constructor parameters. This is a
    plain bundle, not a service locator: it holds exactly the ports resolution
    uses, and reaching any other repository still requires passing it explicitly.
    """

    execution_defaults: ExecutionDefaultsRepository
    provider_connections: ProviderConnectionRepository
    model_configurations: ModelConfigurationRepository
    runtime_configurations: RuntimeConfigurationRepository


class ExecutionConfigurationResolver:
    """Resolve persisted application defaults into an executable configuration.

    Three responsibilities, in order:

    1. read the single defaults record and the three records it names;
    2. revalidate that selection at execution time (existence, enablement, and
       the model/provider pairing);
    3. map it onto existing execution abstractions — runtime registry lookup,
       provider adapter construction, and the standard model-binding
       derivation.

    Credentials are resolved here, per execution, and only when the connection
    declares a reference. The resolved secret is passed straight into provider
    construction and is not stored on the result, so nothing above this method
    can log or serialize it.
    """

    def __init__(
        self,
        repositories: ConfigurationRepositories,
        *,
        runtime_resolver: RuntimeResolver,
        provider_factory: ModelProviderFactory,
        credential_resolver: CredentialResolver,
        model_orchestrator: ModelOrchestrator,
        hosting_requirement: ModelHostingRequirement | None = None,
    ) -> None:
        self._repositories = repositories
        self._runtime_resolver = runtime_resolver
        self._provider_factory = provider_factory
        self._credential_resolver = credential_resolver
        self._model_orchestrator = model_orchestrator
        self._hosting_requirement = hosting_requirement

    def resolve_persisted(self) -> PersistedExecutionConfiguration | None:
        """Resolve persisted defaults, or return ``None`` when none exist.

        Returns ``None`` for exactly one situation: no defaults record has ever
        been configured. A repository failure, an invalid selection, a missing
        adapter, or a credential failure all raise, so an explicitly configured
        but broken setup is never mistaken for an unconfigured one.
        """
        defaults = self._repositories.execution_defaults.get()
        if defaults is None:
            logger.debug("No persisted execution defaults configured; using bootstrap configuration")
            return None
        return self._resolve(defaults)

    def resolve_required(self) -> PersistedExecutionConfiguration:
        """Resolve persisted defaults, failing when they are not configured.

        The strict counterpart to :meth:`resolve_persisted`, for callers that
        genuinely require persisted configuration instead of accepting a
        bootstrap fallback. Nothing in the current run path uses it; it exists
        so "require persisted configuration" is expressible without a caller
        inventing its own sentinel.
        """
        resolved = self.resolve_persisted()
        if resolved is None:
            raise ExecutionDefaultsNotConfiguredError
        return resolved

    def _resolve(self, defaults: ApplicationExecutionDefaults) -> PersistedExecutionConfiguration:
        connection = self._require_connection(defaults)
        model = self._require_model(defaults)
        runtime_configuration = self._require_runtime_configuration(defaults)
        self._require_relationship(model, connection)

        model_profile = _profile_for(model, connection)
        runtime = self._resolve_runtime(runtime_configuration)
        # Exact selection applies orchestration policy without substituting a
        # different model when the operator's saved default is ineligible.
        try:
            self._model_orchestrator.select(
                ModelSelectionRequest(
                    explicit_model_id=model_profile.model_id,
                    preferred_provider_id=connection.provider_id,
                    runtime_id=runtime_configuration.runtime_type,
                    hosting_requirement=self._hosting_requirement,
                ),
                registry=ModelRegistry((model_profile,)),
            )
        except ModelSelectionError:
            raise ConfiguredModelIneligibleError(model.model_id) from None
        credential = self._resolve_credential(connection)
        model_provider = self._create_provider(connection, model, credential)

        logger.debug(
            "Resolved persisted execution configuration: connection=%s model=%s runtime_configuration=%s",
            connection.provider_connection_id,
            model.model_id,
            runtime_configuration.runtime_configuration_id,
        )
        return PersistedExecutionConfiguration(
            runtime=runtime,
            model_provider=model_provider,
            model_binding=model_binding_from_profile(model_profile),
            model_profile=model_profile,
            runtime_configuration_id=runtime_configuration.runtime_configuration_id,
            runtime_type=runtime_configuration.runtime_type,
            provider_connection_id=connection.provider_connection_id,
        )

    # ============================================================
    # BEGIN: Read-time validation
    # ============================================================

    def _require_connection(self, defaults: ApplicationExecutionDefaults) -> ProviderConnection:
        connection = self._repositories.provider_connections.get(
            defaults.default_provider_connection_id
        )
        if connection is None:
            raise ConfiguredReferenceMissingError(
                _PROVIDER_CONNECTION, defaults.default_provider_connection_id
            )
        if not connection.enabled:
            raise ConfiguredReferenceDisabledError(
                _PROVIDER_CONNECTION, connection.provider_connection_id
            )
        return connection

    def _require_model(self, defaults: ApplicationExecutionDefaults) -> ModelConfiguration:
        model = self._repositories.model_configurations.get(defaults.default_model_id)
        if model is None:
            raise ConfiguredReferenceMissingError(_MODEL_CONFIGURATION, defaults.default_model_id)
        if not model.enabled:
            raise ConfiguredReferenceDisabledError(_MODEL_CONFIGURATION, model.model_id)
        return model

    def _require_runtime_configuration(
        self, defaults: ApplicationExecutionDefaults
    ) -> RuntimeConfiguration:
        runtime_configuration = self._repositories.runtime_configurations.get(
            defaults.default_runtime_configuration_id
        )
        if runtime_configuration is None:
            raise ConfiguredReferenceMissingError(
                _RUNTIME_CONFIGURATION, defaults.default_runtime_configuration_id
            )
        if not runtime_configuration.enabled:
            raise ConfiguredReferenceDisabledError(
                _RUNTIME_CONFIGURATION, runtime_configuration.runtime_configuration_id
            )
        return runtime_configuration

    def _require_relationship(
        self, model: ModelConfiguration, connection: ProviderConnection
    ) -> None:
        """Revalidate the model/provider pairing that ``set`` validated on write.

        Normal writes forbid re-pointing a model; read-time validation also
        protects against inconsistent restored or externally edited records.
        """
        if model.provider_connection_id != connection.provider_connection_id:
            raise ModelProviderMismatchError(model.model_id, connection.provider_connection_id)

    # ============================================================
    # END: Read-time validation
    # ============================================================

    # ============================================================
    # BEGIN: Execution abstraction mapping
    # ============================================================

    def _resolve_runtime(self, runtime_configuration: RuntimeConfiguration) -> AgentRuntimePort:
        """Resolve the configured runtime through its *adapter type*.

        The registry is keyed by adapter kind, so ``runtime_type`` is the lookup
        key and ``runtime_configuration_id`` is never passed to it. A
        registered-type miss is reported as
        :class:`RuntimeAdapterNotRegisteredError`, keeping "this runtime is not
        installed right now" distinct from "this runtime configuration does not
        exist" — and never falling back to another runtime.
        """
        try:
            return self._runtime_resolver.resolve(runtime_configuration.runtime_type)
        except UnknownRuntimeError as error:
            raise RuntimeAdapterNotRegisteredError(
                runtime_configuration.runtime_configuration_id,
                runtime_configuration.runtime_type,
            ) from error

    def _create_provider(
        self,
        connection: ProviderConnection,
        model: ModelConfiguration,
        credential: SecretValue | None,
    ) -> ModelProviderPort:
        """Construct the provider adapter for this connection and model.

        ``credential`` is a ``SecretValue`` or ``None``; it is revealed inside
        the factory and nowhere else, and it is never attached to the result.
        The endpoint is passed through as the opaque string it is stored as.
        """
        try:
            return self._provider_factory.create(
                provider_id=connection.provider_id,
                endpoint=connection.endpoint,
                model_name=model.provider_model_name,
                credential=credential,
            )
        except UnknownProviderAdapterError as error:
            raise ProviderAdapterNotRegisteredError(
                connection.provider_connection_id, connection.provider_id
            ) from error
        except Exception:
            # A constructor must not expose authentication material through a
            # vendor/transport exception or its chained traceback.
            raise ProviderConstructionFailedError(connection.provider_connection_id) from None

    def _resolve_credential(self, connection: ProviderConnection) -> SecretValue | None:
        """Resolve this connection's credential, if it declares one.

        Phase 5.9's rule, applied per execution rather than at startup. A
        credential-free connection never invokes the resolver at all, so a local
        unauthenticated provider needs no environment variable and no resolver
        round trip.

        Failures are wrapped so the run failure names the connection rather than
        restating credential-layer detail. Exception chaining is suppressed so even an incorrectly implemented
        secret backend cannot leak its diagnostic through the wrapper traceback.
        """
        try:
            return resolve_connection_credential(connection, self._credential_resolver)
        except CredentialError:
            raise CredentialResolutionFailedError(
                connection.provider_connection_id
            ) from None

    # ============================================================
    # END: Execution abstraction mapping
    # ============================================================


def _profile_for(
    model: ModelConfiguration, connection: ProviderConnection
) -> ModelProfile:
    """Derive the execution-time ``ModelProfile`` for a configured model.

    This is the transformation Phase 5.4 specified and deliberately did not
    perform: resolve the model's provider connection to its provider adapter,
    derive a profile, then derive the binding. Only the profile *view* is
    produced here — the persisted record is never mutated into a provider SDK
    object, and the model profile system is reused rather than duplicated.

    The one field that cannot come from the model record is ``provider_id``: a
    ``ModelConfiguration`` names a *connection*, and the profile's
    ``provider_id`` is the adapter identity that connection is served by. The
    connection is therefore read to supply it, which is also what keeps the
    profile's provider identity aligned with the constructed provider.

    The derived profile is a per-execution value, not a registry mutation: the
    startup ``ModelRegistry`` remains the bootstrap catalog, and reconciling the
    two catalogs is Phase 5.17's work.
    """
    return ModelProfile(
        model_id=model.model_id,
        display_name=model.display_name,
        provider_id=connection.provider_id,
        provider_model_name=model.provider_model_name,
        hosting_mode=model.hosting_mode,
        capabilities=model.capabilities,
        enabled=model.enabled,
    )
