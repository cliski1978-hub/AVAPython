import logging
from dataclasses import dataclass, field, replace

from ava.contracts.execution import RunExecutionOverride
from ava.contracts.requests import RunRequest
from ava.execution.hosting import ModelHostingRequirement
from ava.execution.model_orchestrator import ModelOrchestrator, ModelSelectionRequest
from ava.execution.persisted_execution import (
    ExecutionConfigurationSource,
    PersistedExecutionConfiguration,
    PersistedExecutionConfigurationResolverPort,
    PersistedModelConfiguration,
)
from ava.execution.routing import AutomaticExecutionRoutingPolicy
from ava.execution.selection import (
    ExecutionSelectionSource,
    ProjectExecutionDefaultsResolverPort,
    ProjectExecutionPreference,
    ResolvedExecutionSelection,
)
from ava.models.bindings import ConfiguredModelBinding, ModelBindingResolver, model_binding_from_profile
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.runtimes.contracts import AgentRuntimePort
from ava.runtimes.registry import RuntimeRegistry
from ava.runtimes.resolver import RuntimeResolver, UnknownRuntimeError

logger = logging.getLogger(__name__)


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
    runtime_key: str
    source: ExecutionConfigurationSource = ExecutionConfigurationSource.BOOTSTRAP
    provider_connection_id: str | None = None
    runtime_configuration_id: str | None = None
    runtime_selection_source: ExecutionSelectionSource = ExecutionSelectionSource.BOOTSTRAP
    model_selection_source: ExecutionSelectionSource = ExecutionSelectionSource.BOOTSTRAP
    project_id: str | None = None

    @property
    def selection(self) -> ResolvedExecutionSelection:
        """Return effective identities and per-axis provenance for diagnostics."""
        return ResolvedExecutionSelection(
            runtime_key=self.runtime_key,
            runtime_source=self.runtime_selection_source,
            model_id=self.model_binding.model_id,
            model_source=self.model_selection_source,
            project_id=self.project_id,
        )

    @classmethod
    def from_persisted_configuration(cls, configuration: PersistedExecutionConfiguration) -> "ResolvedExecution":
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
            runtime_key=configuration.runtime_type,
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
        project_execution_defaults_resolver: ProjectExecutionDefaultsResolverPort | None = None,
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
        self._project_defaults = project_execution_defaults_resolver

    def resolve(
        self,
        override: RunExecutionOverride | None = None,
        *,
        conversation_id: str | None = None,
    ) -> ResolvedExecution:
        """Resolve run selection, with Project and application preferences per axis."""
        project = (
            self._project_defaults.resolve_for_conversation(conversation_id)
            if self._project_defaults is not None and conversation_id is not None
            else None
        )
        if override is not None and override.mode == "auto":
            # Auto is an explicit routing policy and retains its pre-Project
            # semantics; it does not silently become a Project preference.
            return replace(
                self._resolve_without_project_defaults(override),
                runtime_selection_source=ExecutionSelectionSource.EXPLICIT,
                model_selection_source=ExecutionSelectionSource.EXPLICIT,
                project_id=project.project_id if project is not None else None,
            )
        if project is not None and (project.runtime_key is not None or project.model_id is not None):
            return self._resolve_with_project_defaults(override, project)

        resolved = self._resolve_without_project_defaults(override)
        runtime_source = (
            ExecutionSelectionSource.EXPLICIT
            if override is not None and override.runtime_id is not None
            else (
                ExecutionSelectionSource.APPLICATION
                if resolved.source == ExecutionConfigurationSource.PERSISTED
                else ExecutionSelectionSource.BOOTSTRAP
            )
        )
        model_source = (
            ExecutionSelectionSource.EXPLICIT
            if override is not None and (override.model_id is not None or override.model_provider_id is not None)
            else (
                ExecutionSelectionSource.APPLICATION
                if resolved.source == ExecutionConfigurationSource.PERSISTED
                else ExecutionSelectionSource.BOOTSTRAP
            )
        )
        return replace(
            resolved,
            runtime_selection_source=runtime_source,
            model_selection_source=model_source,
            project_id=project.project_id if project is not None else None,
        )

    def _resolve_with_project_defaults(
        self,
        override: RunExecutionOverride | None,
        project: ProjectExecutionPreference,
    ) -> ResolvedExecution:
        """Resolve runtime and model independently across all preference tiers."""
        defaults = self._persisted.application_defaults() if self._persisted is not None else None

        # Runtime precedence: explicit → Project → application → bootstrap.
        runtime_configuration_id: str | None = None
        if override is not None and override.runtime_id is not None:
            runtime_key = override.runtime_id
            runtime = self._runtime.resolve(runtime_key)
            runtime_source = ExecutionSelectionSource.EXPLICIT
        else:
            project_runtime: AgentRuntimePort | None = None
            if project.runtime_key is not None:
                try:
                    project_runtime = self._runtime.resolve(project.runtime_key)
                except UnknownRuntimeError:
                    logger.info(
                        "Ignoring unavailable Project runtime preference for Project %s",
                        project.project_id,
                    )
            if project_runtime is not None:
                runtime_key = project.runtime_key or ""
                runtime = project_runtime
                runtime_source = ExecutionSelectionSource.PROJECT
            elif defaults is not None:
                if self._persisted is None:
                    raise RuntimeError("Application execution defaults resolver is unavailable")
                configured_runtime = self._persisted.resolve_application_runtime()
                if configured_runtime is None:
                    raise RuntimeError("Application runtime defaults unexpectedly disappeared")
                runtime_key = configured_runtime.runtime_key
                runtime = configured_runtime.runtime
                runtime_configuration_id = configured_runtime.runtime_configuration_id
                runtime_source = ExecutionSelectionSource.APPLICATION
            else:
                runtime_key = self._default_runtime_id
                runtime = self._runtime.resolve(runtime_key)
                runtime_source = ExecutionSelectionSource.BOOTSTRAP

        # Model precedence: explicit → Project → application → bootstrap.
        # The selected model carries its provider connection; no Project or
        # runtime selection is allowed to choose a provider independently.
        names_explicit_model = override is not None and (
            override.model_id is not None or override.model_provider_id is not None
        )
        configured_model: PersistedModelConfiguration | None = None
        model_source: ExecutionSelectionSource
        if names_explicit_model:
            if override is not None and override.model_id is not None and self._persisted is not None:
                configured_model = self._persisted.resolve_model_configuration(
                    override.model_id, runtime_type=runtime_key
                )
            if configured_model is not None:
                model_source = ExecutionSelectionSource.EXPLICIT
            else:
                profile = self._select_model(
                    explicit_model_id=override.model_id if override else None,
                    preferred_provider_id=override.model_provider_id if override else None,
                    runtime_id=runtime_key,
                )
                return ResolvedExecution(
                    runtime=runtime,
                    model_provider=self._provider.resolve(profile.provider_id),
                    model_binding=model_binding_from_profile(profile),
                    model_profile=profile,
                    runtime_key=runtime_key,
                    runtime_configuration_id=runtime_configuration_id,
                    runtime_selection_source=runtime_source,
                    model_selection_source=ExecutionSelectionSource.EXPLICIT,
                    project_id=project.project_id,
                )
        elif project.model_id is not None and self._persisted is not None:
            configured_model = self._persisted.resolve_model_configuration(
                project.model_id,
                runtime_type=runtime_key,
                skip_if_unavailable=True,
            )
            if configured_model is not None:
                model_source = ExecutionSelectionSource.PROJECT
            else:
                model_source = ExecutionSelectionSource.BOOTSTRAP
        else:
            model_source = ExecutionSelectionSource.BOOTSTRAP

        if configured_model is None:
            # A stale Project reference is skipped. In particular, do not
            # interpret a missing configured model id as a provider choice.
            if defaults is not None:
                if self._persisted is None:
                    raise RuntimeError("Application execution defaults resolver is unavailable")
                configured_model = self._persisted.resolve_model_configuration(
                    defaults.default_model_id,
                    runtime_type=runtime_key,
                    expected_provider_connection_id=defaults.default_provider_connection_id,
                    require_configured=True,
                )
                if configured_model is None:
                    raise RuntimeError("Application model defaults unexpectedly disappeared")
                model_source = ExecutionSelectionSource.APPLICATION
            else:
                profile = self._select_model(
                    explicit_model_id=None,
                    preferred_provider_id=None,
                    runtime_id=runtime_key,
                )
                return ResolvedExecution(
                    runtime=runtime,
                    model_provider=self._provider.resolve(profile.provider_id),
                    model_binding=model_binding_from_profile(profile),
                    model_profile=profile,
                    runtime_key=runtime_key,
                    runtime_configuration_id=runtime_configuration_id,
                    runtime_selection_source=runtime_source,
                    model_selection_source=ExecutionSelectionSource.BOOTSTRAP,
                    project_id=project.project_id,
                )

        if configured_model is None:
            # Explicit model provider-only selection is resolved above. This is
            # a defensive guard for malformed/incomplete resolver implementations.
            raise ValueError("Unable to resolve execution model")
        return ResolvedExecution(
            runtime=runtime,
            model_provider=configured_model.model_provider,
            model_binding=configured_model.model_binding,
            model_profile=configured_model.model_profile,
            runtime_key=runtime_key,
            source=ExecutionConfigurationSource.PERSISTED,
            provider_connection_id=configured_model.provider_connection_id,
            runtime_configuration_id=runtime_configuration_id,
            runtime_selection_source=runtime_source,
            model_selection_source=model_source,
            project_id=project.project_id,
        )

    def _resolve_without_project_defaults(self, override: RunExecutionOverride | None = None) -> ResolvedExecution:
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

        An explicit override is *partial*: it names only the axes the caller
        actually chose. When persisted defaults exist, every axis it leaves unset
        keeps the persisted application default, so choosing a runtime never
        silently swaps the operator's configured model, and choosing a model
        never silently swaps the configured runtime.

        Axes an override *does* name still resolve exactly as before: a named
        model or provider is an explicit legacy selection from the bootstrap
        catalogs, and a named runtime is a registry adapter key. Persisted
        defaults are validated first even then: an override must not conceal a
        broken saved configuration. Mapping legacy override fields to
        configured-instance ids is deferred to Phase 5.17.
        """
        persisted: PersistedExecutionConfiguration | None = None
        if self._persisted is not None:
            persisted = self._persisted.resolve_persisted()
            if persisted is not None and _is_unset(override):
                return ResolvedExecution.from_persisted_configuration(persisted)
        # An explicitly named configured model is resolved before anything else so
        # the answer never depends on whether application defaults happen to be
        # saved yet. A model added in Settings must be runnable on its own.
        configured = self._configured_model(override)
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
                decision.runtime_id,
            )
        if persisted is not None:
            return self._resolve_override_onto_persisted(override, persisted, configured)
        runtime_id = override.runtime_id if override and override.runtime_id is not None else self._default_runtime_id
        if configured is not None:
            return self._execution_from_configured_model(
                configured,
                override=override,
                runtime_id=runtime_id,
            )
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
            runtime_key=runtime_id,
        )

    def _resolve_override_onto_persisted(
        self,
        override: RunExecutionOverride | None,
        persisted: PersistedExecutionConfiguration,
        configured: PersistedModelConfiguration | None = None,
    ) -> ResolvedExecution:
        """Resolve one explicit selection on top of persisted application defaults.

        Each axis is decided independently: an axis the override names is
        resolved from the catalogs the override contract already defines, and an
        axis it leaves unset keeps the persisted default rather than falling back
        to a bootstrap default. That is what keeps ``Model: application default``
        meaning *the configured model* instead of a same-looking bootstrap model
        recorded under a different identity.

        A named runtime is a registry adapter key. When it names the same
        adapter the persisted configuration already uses, the configured
        instance is kept so the run stays attributed to it; otherwise the
        registry resolves the key and the run records no configured instance,
        because none backs that choice.
        """
        explicit_runtime_id = override.runtime_id if override is not None else None
        if explicit_runtime_id is None or explicit_runtime_id == persisted.runtime_type:
            runtime = persisted.runtime
            resolved_runtime_key = persisted.runtime_type
            runtime_configuration_id: str | None = persisted.runtime_configuration_id
        else:
            runtime = self._runtime.resolve(explicit_runtime_id)
            resolved_runtime_key = explicit_runtime_id
            runtime_configuration_id = None
        names_model = override is not None and (override.model_id is not None or override.model_provider_id is not None)
        if not names_model:
            return ResolvedExecution(
                runtime=runtime,
                model_provider=persisted.model_provider,
                model_binding=persisted.model_binding,
                model_profile=persisted.model_profile,
                runtime_key=resolved_runtime_key,
                source=ExecutionConfigurationSource.PERSISTED,
                provider_connection_id=persisted.provider_connection_id,
                runtime_configuration_id=runtime_configuration_id,
            )
        if configured is None:
            configured = self._configured_model(override)
        if configured is not None:
            return self._execution_from_configured_model(
                configured,
                override=override,
                runtime=runtime,
                runtime_key=resolved_runtime_key,
                runtime_configuration_id=runtime_configuration_id,
            )
        profile = self._select_model(
            explicit_model_id=override.model_id if override else None,
            preferred_provider_id=override.model_provider_id if override else None,
            runtime_id=explicit_runtime_id or persisted.runtime_type,
        )
        return ResolvedExecution(
            runtime=runtime,
            model_provider=self._provider.resolve(profile.provider_id),
            model_binding=model_binding_from_profile(profile),
            model_profile=profile,
            runtime_key=resolved_runtime_key,
            source=ExecutionConfigurationSource.BOOTSTRAP,
            runtime_configuration_id=runtime_configuration_id,
        )

    def _execution_from_configured_model(
        self,
        configured: PersistedModelConfiguration,
        *,
        override: RunExecutionOverride | None = None,
        runtime_id: str | None = None,
        runtime: AgentRuntimePort | None = None,
        runtime_key: str | None = None,
        runtime_configuration_id: str | None = None,
    ) -> ResolvedExecution:
        """Build a run from one explicitly chosen configured model.

        The two id spaces are checked against each other rather than trusted: a
        ``model_id`` from the configured catalog and a ``model_provider_id`` from
        the provider catalog describe the same selection, so disagreeing is a
        caller error and never silently resolved in favour of one of them.
        """
        if (
            override is not None
            and override.model_provider_id is not None
            and override.model_provider_id != configured.model_profile.provider_id
        ):
            raise ValueError("model_id and model_provider_id must identify the same provider")
        resolved_runtime = runtime if runtime is not None else self._runtime.resolve(runtime_id or "")
        resolved_runtime_key = runtime_key or runtime_id or resolved_runtime.get_runtime_info().runtime_id
        return ResolvedExecution(
            runtime=resolved_runtime,
            model_provider=configured.model_provider,
            model_binding=configured.model_binding,
            model_profile=configured.model_profile,
            runtime_key=resolved_runtime_key,
            source=ExecutionConfigurationSource.PERSISTED,
            provider_connection_id=configured.provider_connection_id,
            runtime_configuration_id=runtime_configuration_id,
        )

    def _configured_model(self, override: RunExecutionOverride | None) -> PersistedModelConfiguration | None:
        """Resolve an explicitly named ``model_id`` as a configured model.

        A configured ``model_id`` is AVA's stable, provider-neutral identity and
        takes precedence over the bootstrap catalog, so selecting a model added
        in Settings runs that exact record rather than a catalog entry that
        happens to share a name. ``None`` means the id names no configured model,
        which leaves the legacy bootstrap path below unchanged.
        """
        if self._persisted is None or override is None or override.model_id is None:
            return None
        return self._persisted.resolve_model_configuration(override.model_id)

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
