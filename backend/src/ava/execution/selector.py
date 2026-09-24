from dataclasses import dataclass

from ava.contracts.execution import RunExecutionOverride
from ava.contracts.requests import RunRequest
from ava.execution.hosting import ModelHostingRequirement
from ava.execution.model_orchestrator import ModelOrchestrator, ModelSelectionRequest
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
    """

    runtime: AgentRuntimePort
    model_provider: ModelProviderPort
    model_binding: ConfiguredModelBinding
    model_profile: ModelProfile


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

    def resolve(self, override: RunExecutionOverride | None = None) -> ResolvedExecution:
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


# ruff: noqa: E501
