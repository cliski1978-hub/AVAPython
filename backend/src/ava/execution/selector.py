from dataclasses import dataclass, field

from ava.contracts.execution import RunExecutionOverride
from ava.contracts.requests import RunRequest
from ava.execution.hosting import ModelHostingRequirement
from ava.execution.model_orchestrator import ModelOrchestrator, ModelSelectionRequest
from ava.execution.persisted_execution import (
    ExecutionConfigurationSource,
    PersistedExecutionConfiguration,
    PersistedExecutionConfigurationResolverPort,
)
from ava.execution.routing import AutomaticExecutionRoutingPolicy
from ava.models.bindings import ConfiguredModelBinding, ModelBindingResolver, model_binding_from_profile
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.runtimes.contracts import AgentRuntimePort
from ava.runtimes.registry import RuntimeRegistry
from ava.runtimes.resolver import RuntimeResolver


@dataclass(frozen=True)
class ResolvedExecution:
    """A resolved runtime, provider, and model profile/binding for one run.

    ``model_profile`` is the authoritative registry record (declared
    capabilities, hosting mode, enabled state); ``model_binding`` is its derived
    execution view carrying the stable AVA ``model_id`` (for run metadata) and
    the provider-native ``provider_model_name`` the runtime must target. The
    provider object is resolved by the profile's ``provider_id``; model identity
    never selects a provider on its own.

    ``source`` and the two configured ids record *where the selection came from*,
    not anything about how it executes. Phase 5.8 found four legacy default
    mechanisms plus persisted settings and left the precedence question open, so
    the mechanism that supplied a run's configuration has to be visible rather
    than inferred. The two ids are ``None`` for a bootstrap selection, which is
    how a configured-instance identity is distinguished from an adapter identity.
    """

    runtime: AgentRuntimePort = field(repr=False)
    model_provider: ModelProviderPort = field(repr=False)
    model_binding: ConfiguredModelBinding
    model_profile: ModelProfile
    source: ExecutionConfigurationSource = ExecutionConfigurationSource.BOOTSTRAP
    provider_connection_id: str | None = None
    runtime_configuration_id: str | None = None

    @classmethod
    def from_persisted_configuration(
        cls, configuration: PersistedExecutionConfiguration
    ) -> "ResolvedExecution":
        """Adapt a validated persisted selection onto the execution boundary.

        Persisted resolution returns the same four execution objects a bootstrap
        selection does, so nothing downstream can tell them apart. The mapping
        lives here — the only place that knows both shapes — which is what keeps
        the runtime, resource manager, and orchestrator free of any persisted
        configuration concept.
        """
        return cls(
            runtime=configuration.runtime,
            model_provider=configuration.model_provider,
            model_binding=configuration.model_binding,
            model_profile=configuration.model_profile,
            source=ExecutionConfigurationSource.PERSISTED,
            provider_connection_id=configuration.provider_connection_id,
            runtime_configuration_id=configuration.runtime_configuration_id,
        )


class ExecutionSelector:
    def __init__(
        self,
        *,
        runtime_resolver: RuntimeResolver,
        model_provider_resolver: ModelProviderResolver,
        model_binding_resolver: ModelBindingResolver,
        default_runtime_id: str,
        default_model_provider_id: str,
        runtime_registry: RuntimeRegistry | None = None,
        model_provider_registry: ModelProviderRegistry | None = None,
        eligible_runtime_ids: frozenset[str] | None = None,
        model_orchestrator: ModelOrchestrator | None = None,
        hosting_requirement: ModelHostingRequirement | None = None,
        persisted_configuration_resolver: PersistedExecutionConfigurationResolverPort | None = None,
    ) -> None:
        self._runtime = runtime_resolver
        self._provider = model_provider_resolver
        self._model_bindings = model_binding_resolver
        self._default_runtime_id = default_runtime_id
        self._default_provider_id = default_model_provider_id
        self._routing = (
            AutomaticExecutionRoutingPolicy(
                runtime_registry=runtime_registry,
                model_provider_registry=model_provider_registry,
                eligible_runtime_ids=eligible_runtime_ids,
            )
            if runtime_registry and model_provider_registry
            else None
        )
        self._model_orchestrator = model_orchestrator
        self._hosting_requirement = hosting_requirement
        self._persisted = persisted_configuration_resolver

    def resolve(self, override: RunExecutionOverride | None = None) -> ResolvedExecution:
        """Resolve the execution for one run.

        Authority: persisted application defaults first, bootstrap second. A
        resolver that returns a configuration wins outright, because the
        configured provider, model, and runtime are the operator's explicit
        choice and silently substituting a bootstrap default would run a
        different model than the one configured. When the resolver returns
        ``None`` — no defaults have ever been configured — the bootstrap path
        below runs exactly as before.

        The resolver is also the *only* new failure surface: it raises
        ``ExecutionConfigurationError`` (a ``ValueError``) for a persisted
        selection that no longer resolves, and that deliberately propagates
        instead of being caught here. A broken explicit configuration must fail
        the run, not silently degrade to bootstrap.

        Explicit legacy overrides still select from the bootstrap catalogs.
        Persisted defaults, when present, are validated first even in that case:
        an override must not conceal a broken saved configuration. Mapping legacy
        override fields to configured-instance ids is deferred to Phase 5.17.
        """
        if self._persisted is not None:
            persisted = self._persisted.resolve_persisted()
            if persisted is not None and _is_unset(override):
                return ResolvedExecution.from_persisted_configuration(persisted)
        if override and override.mode == "auto":
            if override.runtime_id or override.model_id or override.model_provider_id or self._routing is None:
                raise ValueError("Auto execution cannot include explicit ids")
            decision = self._routing.select(
                request=RunRequest(prompt="auto"),
                default_runtime_id=self._default_runtime_id,
                default_model_provider_id=self._default_provider_id,
            )
            profile = self._select_model(
                explicit_model_id=None,
                preferred_provider_id=decision.model_provider_id,
                runtime_id=decision.runtime_id,
            )
            return ResolvedExecution(
                self._runtime.resolve(decision.runtime_id),
                self._provider.resolve(decision.model_provider_id),
                model_binding_from_profile(profile),
                profile,
            )
        runtime_id = override.runtime_id if override and override.runtime_id is not None else self._default_runtime_id
        if override and override.model_id is not None:
            profile = self._select_model(
                explicit_model_id=override.model_id,
                preferred_provider_id=override.model_provider_id,
                runtime_id=runtime_id,
            )
        else:
            profile = self._select_model(
                explicit_model_id=None,
                preferred_provider_id=(override.model_provider_id if override else None),
                runtime_id=runtime_id,
            )
        return ResolvedExecution(
            runtime=self._runtime.resolve(runtime_id),
            model_provider=self._provider.resolve(profile.provider_id),
            model_binding=model_binding_from_profile(profile),
            model_profile=profile,
        )

    def _select_model(
        self,
        *,
        explicit_model_id: str | None,
        preferred_provider_id: str | None,
        runtime_id: str,
    ) -> ModelProfile:
        if self._model_orchestrator is None:
            if explicit_model_id is not None:
                profile = self._model_bindings.resolve_profile(explicit_model_id)
                if preferred_provider_id is not None and preferred_provider_id != profile.provider_id:
                    raise ValueError("model_id and model_provider_id must identify the same provider")
                return profile
            if preferred_provider_id is not None:
                return self._model_bindings.default_profile_for_provider(preferred_provider_id)
            return self._model_bindings.default_profile()
        decision = self._model_orchestrator.select(
            ModelSelectionRequest(
                explicit_model_id=explicit_model_id,
                preferred_provider_id=preferred_provider_id,
                runtime_id=runtime_id,
                hosting_requirement=self._hosting_requirement,
            )
        )
        return self._model_bindings.resolve_profile(decision.model_id)


def _is_unset(override: RunExecutionOverride | None) -> bool:
    """Whether an override asks for nothing in particular.

    An absent override, and an override that names no runtime, model, or
    provider, both mean "no explicit choice", so both take the persisted path.
    An empty override is a no-op: treating it as an explicit selection would
    make a run silently ignore persisted defaults because of a payload that did
    not ask to.

    ``mode == "auto"`` is never unset — it explicitly requests orchestration over
    the bootstrap catalog, which is a real choice with real behavior.
    """
    if override is None:
        return True
    if override.mode == "auto":
        return False
    return override.runtime_id is None and override.model_id is None and override.model_provider_id is None


# ruff: noqa: E501
