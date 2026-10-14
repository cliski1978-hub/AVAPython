"""Phase 5.73 execution selection and Project provenance coverage."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.agents.contracts import AgentPort, AgentRunResult
from ava.configuration.settings import Settings
from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.execution import RunExecutionOverride, RunExecutionSelection
from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.contracts.projects import UpdateProjectExecutionDefaultsRequest
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.execution.persisted_execution import (
    PersistedExecutionConfiguration,
    PersistedModelConfiguration,
    PersistedRuntimeConfiguration,
)
from ava.execution.selection import (
    ExecutionSelectionSource,
    ProjectExecutionDefaultsResolverPort,
    ProjectExecutionPreference,
    ResolvedExecutionSelection,
)
from ava.execution.selector import ExecutionSelector
from ava.infrastructure.composition import create_application_persistence, create_runtime_registry
from ava.models.bindings import ModelBindingResolver, model_binding_from_profile
from ava.models.contracts import ModelProviderPort
from ava.models.model_configurations import ModelConfiguration
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.provider_connections import ProviderConnection
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.repositories.message_repository import MessageRecord
from ava.repositories.project import ProjectExecutionDefaults, ProjectRecord
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.registry import RuntimeRegistry
from ava.runtimes.resolver import RuntimeResolver
from ava.services.context_construction_service import ContextConstructionService
from ava.services.project_execution_defaults_resolver import ProjectExecutionDefaultsResolver
from ava.services.project_execution_defaults_service import ProjectExecutionDefaultsService
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore

if TYPE_CHECKING:
    from ava.configuration.execution_defaults import ApplicationExecutionDefaults


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_selection_context_comes_from_canonical_conversation(
    provider: str, tmp_path: Path
) -> None:
    persistence = create_application_persistence(
        Settings(
            persistence_provider=provider,
            persistence_database_url=str(tmp_path / f"{provider}-selection.sqlite3"),
        )
    )
    now = datetime(2026, 10, 1, tzinfo=UTC)
    project = ProjectRecord(
        "project-p",
        "Project P",
        now,
        now,
        execution_defaults=ProjectExecutionDefaults("native", None),
        is_archived=True,
    )
    try:
        persistence.project_repository.create(project)
        persistence.conversation_repository.create("conversation-p", title="Project chat", project_id=project.id)
        persistence.conversation_repository.create("conversation-global", title="Global chat")
        resolver = ProjectExecutionDefaultsResolver(
            conversations=persistence.conversation_repository,
            projects=persistence.project_repository,
        )

        assert resolver.resolve_for_conversation("conversation-p") == ProjectExecutionPreference(
            project_id="project-p", runtime_key="native", model_id=None
        )
        assert resolver.resolve_for_conversation("conversation-global") is None
        assert resolver.resolve_for_conversation(None) is None

        changed = ProjectRecord(
            project.id,
            project.name,
            project.created_at,
            project.updated_at,
            is_archived=True,
            execution_defaults=ProjectExecutionDefaults("openhands", None),
        )
        persistence.project_repository.update(changed)
        assert resolver.resolve_for_conversation("conversation-p").runtime_key == "openhands"

        other = ProjectRecord("project-other", "Other", now, now)
        persistence.project_repository.create(other)
        persistence.conversation_repository.set_project("conversation-p", other.id)
        assert resolver.resolve_for_conversation("conversation-p").project_id == other.id
        persistence.conversation_repository.set_project("conversation-p", None)
        assert resolver.resolve_for_conversation("conversation-p") is None
        persistence.conversation_repository.set_project("conversation-p", project.id)
        assert persistence.project_repository.delete(project.id)
        assert resolver.resolve_for_conversation("conversation-p") is None
    finally:
        persistence.dispose()


def _profile(model_id: str, provider_id: str = "provider") -> ModelProfile:
    return ModelProfile(
        model_id=model_id,
        display_name=model_id,
        provider_id=provider_id,
        provider_model_name=f"native-{model_id}",
        hosting_mode=ModelHostingMode.LOCAL,
        capabilities=ModelCapabilities(chat=True),
    )


@dataclass
class _ProjectResolver:
    preference: ProjectExecutionPreference | None

    def resolve_for_conversation(self, conversation_id: str | None) -> ProjectExecutionPreference | None:
        assert conversation_id == "project-conversation"
        return self.preference


class _SelectionAgent(AgentPort):
    """Exercise run orchestration while reporting the selector's chosen model."""

    def __init__(self, selector: ExecutionSelector) -> None:
        self.selector = selector

    def name(self) -> str:
        return "selection-test"

    async def start_run(
        self, run_id: str, request: RunRequest, *, context=None, resolved_execution=None
    ) -> AgentRunResult:
        del run_id, context
        execution = resolved_execution or self.selector.resolve(
            request.execution,
            conversation_id=request.conversation_id,
        )
        selection = RunExecutionSelection(
            runtime_id=execution.runtime_key,
            model_provider_id=execution.model_binding.provider_id,
            model_id=execution.model_binding.model_id,
            runtime_source=execution.runtime_selection_source.value,
            model_source=execution.model_selection_source.value,
            project_id=execution.project_id,
        )
        return AgentRunResult(status=RunStatus.COMPLETED, content="ok", execution_selection=selection)

    async def cancel_run(self, run_id: str) -> RunResponse:
        return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)

    def get_capabilities(self) -> set[CapabilityName]:
        return set()


class _PersistedResolver:
    def __init__(self, defaults: ApplicationExecutionDefaults | None, profiles: dict[str, ModelProfile]) -> None:
        self.defaults = defaults
        self.profiles = profiles
        self.application_runtime = NativeRuntime()

    def application_defaults(self) -> ApplicationExecutionDefaults | None:
        return self.defaults

    def resolve_persisted(self) -> PersistedExecutionConfiguration | None:
        if self.defaults is None:
            return None
        profile = self.profiles[self.defaults.default_model_id]
        return PersistedExecutionConfiguration(
            runtime=self.application_runtime,
            model_provider=cast(ModelProviderPort, object()),
            model_binding=model_binding_from_profile(profile),
            model_profile=profile,
            runtime_configuration_id="runtime-app",
            runtime_type="app-runtime",
            provider_connection_id=self.defaults.default_provider_connection_id,
        )

    def resolve_application_runtime(self) -> PersistedRuntimeConfiguration | None:
        assert self.defaults is not None
        return PersistedRuntimeConfiguration(self.application_runtime, "app-runtime", "runtime-app")

    def resolve_model_configuration(
        self,
        model_id: str,
        *,
        runtime_type: str | None = None,
        skip_if_unavailable: bool = False,
        expected_provider_connection_id: str | None = None,
        require_configured: bool = False,
    ) -> PersistedModelConfiguration | None:
        profile = self.profiles.get(model_id)
        if profile is None:
            if require_configured:
                raise AssertionError("required test model is missing")
            return None
        return PersistedModelConfiguration(
            model_provider=cast(ModelProviderPort, object()),
            model_binding=model_binding_from_profile(profile),
            model_profile=profile,
            provider_connection_id=f"connection-{model_id}",
        )


def _selection(
    project_runtime: str | None,
    project_model: str | None,
    *,
    override: RunExecutionOverride | None = None,
    app: bool = True,
    project_member: bool = True,
    project_resolver: _ProjectResolver | None = None,
    models: tuple[str, ...] = ("project-model", "app-model", "explicit-model"),
) -> ResolvedExecutionSelection:
    selector, _ = _configured_selector(
        project_resolver=project_resolver
        or _ProjectResolver(
            ProjectExecutionPreference("project-1", project_runtime, project_model)
            if project_member
            else None
        ),
        app=app,
        models=models,
    )
    return selector.resolve(override, conversation_id="project-conversation").selection


def _configured_selector(
    *,
    project_resolver: ProjectExecutionDefaultsResolverPort,
    app: bool = True,
    models: tuple[str, ...] = ("project-model", "app-model", "explicit-model"),
) -> tuple[ExecutionSelector, dict[str, ModelProfile]]:
    from ava.configuration.execution_defaults import ApplicationExecutionDefaults

    profiles = {model_id: _profile(model_id) for model_id in models}
    defaults = (
        ApplicationExecutionDefaults("connection-app-model", "app-model", "runtime-app-config")
        if app
        else None
    )
    runtime_registry = RuntimeRegistry()
    for key in ("runtime-project", "runtime-app", "runtime-explicit", "native"):
        runtime_registry.register(key, NativeRuntime())
    provider_registry = ModelProviderRegistry()
    provider_registry.register("provider", cast(ModelProviderPort, object()))
    bindings = ModelBindingResolver(ModelRegistry(profiles.values()), default_model_id="app-model")
    selector = ExecutionSelector(
        runtime_resolver=RuntimeResolver(runtime_registry),
        model_provider_resolver=ModelProviderResolver(provider_registry),
        model_binding_resolver=bindings,
        default_runtime_id="native",
        default_model_provider_id="provider",
        persisted_configuration_resolver=_PersistedResolver(defaults, profiles),
        project_execution_defaults_resolver=project_resolver,
    )
    return selector, profiles


def test_existing_project_conversation_uses_current_default_and_persists_each_run(tmp_path: Path) -> None:
    """Project edits, moves, removals, and explicit choices affect only later runs."""
    persistence = create_application_persistence(
        Settings(
            persistence_provider="memory",
            persistence_database_url=str(tmp_path / "unused.sqlite3"),
        )
    )
    now = datetime(2026, 10, 1, tzinfo=UTC)
    project = ProjectRecord(
        "project-current-default",
        "Current default",
        now,
        now,
        execution_defaults=ProjectExecutionDefaults(None, "project-model"),
    )
    moved_project = ProjectRecord(
        "project-moved-default",
        "Moved default",
        now,
        now,
        execution_defaults=ProjectExecutionDefaults(None, "project-model"),
    )
    try:
        persistence.project_repository.create(project)
        persistence.project_repository.create(moved_project)
        persistence.provider_connection_repository.create(
            ProviderConnection("connection-selection", "provider", "Provider")
        )
        for model_id in ("project-model", "next-model", "app-model", "explicit-model"):
            persistence.model_configuration_repository.create(
                ModelConfiguration(
                    model_id=model_id,
                    provider_connection_id="connection-selection",
                    provider_model_name=f"provider-{model_id}",
                    display_name=model_id,
                    hosting_mode=ModelHostingMode.LOCAL,
                    capabilities=ModelCapabilities(chat=True),
                )
            )
        persistence.conversation_repository.create(
            "conversation-current-default", title="Existing chat", project_id=project.id
        )
        project_resolver = ProjectExecutionDefaultsResolver(
            conversations=persistence.conversation_repository,
            projects=persistence.project_repository,
        )
        selector, _ = _configured_selector(
            project_resolver=project_resolver,
            models=("project-model", "next-model", "app-model", "explicit-model"),
        )
        agent = _SelectionAgent(selector)
        run_repository = RunStore()
        event_repository = RunEventStore()
        context_service = ContextConstructionService(
            run_repository=run_repository,
            message_repository=persistence.message_repository,
            conversation_repository=persistence.conversation_repository,
        )
        run_service = RunService(
            agent,
            run_repository=run_repository,
            run_event_repository=event_repository,
            conversation_repository=persistence.conversation_repository,
            message_repository=persistence.message_repository,
            context_service=context_service,
        )

        prompt_index = 0

        def run(*, execution: RunExecutionOverride | None = None):
            nonlocal prompt_index
            prompt_index += 1
            source_user_message_id = f"source-user-{prompt_index}"
            created_at = datetime.now(UTC)
            persistence.message_repository.append(
                MessageRecord(
                    message_id=source_user_message_id,
                    conversation_id="conversation-current-default",
                    role=MessageRole.USER,
                    content="Resolve the current execution defaults.",
                    status=MessageStatus.COMPLETE,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            return asyncio.run(
                run_service.start_run(
                    RunRequest(
                        prompt="Resolve the current execution defaults.",
                        conversation_id="conversation-current-default",
                        source_user_message_id=source_user_message_id,
                        execution=execution,
                    )
                )
            )

        first = run()
        assert first.execution_selection is not None
        assert first.execution_selection.model_id == "project-model"
        assert first.execution_selection.model_source == ExecutionSelectionSource.PROJECT.value

        settings_service = ProjectExecutionDefaultsService(
            projects=persistence.project_repository,
            models=persistence.model_configuration_repository,
            runtimes=RuntimeResolver(create_runtime_registry()),
        )
        settings_service.update(
            project.id,
            UpdateProjectExecutionDefaultsRequest(model_id="next-model"),
        )

        next_run = run()
        assert next_run.execution_selection is not None
        assert next_run.execution_selection.model_id == "next-model"
        assert next_run.execution_selection.model_source == ExecutionSelectionSource.PROJECT.value

        explicit = run(execution=RunExecutionOverride(model_id="explicit-model"))
        assert explicit.execution_selection is not None
        assert explicit.execution_selection.model_id == "explicit-model"
        assert explicit.execution_selection.model_source == ExecutionSelectionSource.EXPLICIT.value

        after_override_removed = run()
        assert after_override_removed.execution_selection is not None
        assert after_override_removed.execution_selection.model_id == "next-model"
        assert after_override_removed.execution_selection.model_source == ExecutionSelectionSource.PROJECT.value

        persistence.conversation_repository.set_project("conversation-current-default", moved_project.id)
        moved = run()
        assert moved.execution_selection is not None
        assert moved.execution_selection.project_id == moved_project.id
        assert moved.execution_selection.model_id == "project-model"

        persistence.conversation_repository.set_project("conversation-current-default", project.id)
        assert persistence.project_repository.delete(project.id)
        unlinked = run()
        assert unlinked.execution_selection is not None
        assert unlinked.execution_selection.project_id is None
        assert unlinked.execution_selection.model_id == "app-model"
        assert unlinked.execution_selection.model_source == ExecutionSelectionSource.APPLICATION.value

        historical_first = run_service.get_run(first.run_id)
        historical_next = run_service.get_run(next_run.run_id)
        assert historical_first is not None and historical_first.execution_selection is not None
        assert historical_next is not None and historical_next.execution_selection is not None
        assert historical_first.execution_selection.model_id == "project-model"
        assert historical_next.execution_selection.model_id == "next-model"
    finally:
        persistence.dispose()


def test_project_and_explicit_axes_resolve_independently() -> None:
    selected = _selection(
        "runtime-project",
        "project-model",
        override=RunExecutionOverride(runtime_id="runtime-explicit"),
    )
    assert (selected.runtime_key, selected.runtime_source) == (
        "runtime-explicit",
        ExecutionSelectionSource.EXPLICIT,
    )
    assert (selected.model_id, selected.model_source) == ("project-model", ExecutionSelectionSource.PROJECT)

    selected = _selection(
        "runtime-project",
        "project-model",
        override=RunExecutionOverride(model_id="explicit-model"),
    )
    assert (selected.runtime_key, selected.runtime_source) == ("runtime-project", ExecutionSelectionSource.PROJECT)
    assert (selected.model_id, selected.model_source) == ("explicit-model", ExecutionSelectionSource.EXPLICIT)


def test_project_partial_defaults_fall_through_per_axis() -> None:
    selected = _selection("runtime-project", None)
    assert (selected.runtime_key, selected.runtime_source) == ("runtime-project", ExecutionSelectionSource.PROJECT)
    assert (selected.model_id, selected.model_source) == ("app-model", ExecutionSelectionSource.APPLICATION)

    selected = _selection(None, "project-model")
    assert (selected.runtime_key, selected.runtime_source) == ("app-runtime", ExecutionSelectionSource.APPLICATION)
    assert (selected.model_id, selected.model_source) == ("project-model", ExecutionSelectionSource.PROJECT)


def test_missing_project_model_falls_back_to_application_model() -> None:
    selected = _selection("runtime-project", "deleted-project-model", models=("app-model",))
    assert selected.runtime_source is ExecutionSelectionSource.PROJECT
    assert (selected.model_id, selected.model_source) == ("app-model", ExecutionSelectionSource.APPLICATION)


def test_stale_project_runtime_falls_back_to_application_runtime() -> None:
    selected = _selection("runtime-deleted", "project-model")
    assert (selected.runtime_key, selected.runtime_source) == ("app-runtime", ExecutionSelectionSource.APPLICATION)
    assert (selected.model_id, selected.model_source) == ("project-model", ExecutionSelectionSource.PROJECT)


def test_no_project_membership_uses_application_then_bootstrap() -> None:
    selected = _selection(None, None, project_member=False)
    assert (selected.runtime_key, selected.runtime_source) == ("app-runtime", ExecutionSelectionSource.APPLICATION)
    assert (selected.model_id, selected.model_source) == ("app-model", ExecutionSelectionSource.APPLICATION)

    selected = _selection(None, None, app=False, project_member=False)
    assert (selected.runtime_key, selected.runtime_source) == ("native", ExecutionSelectionSource.BOOTSTRAP)
    assert (selected.model_id, selected.model_source) == ("app-model", ExecutionSelectionSource.BOOTSTRAP)


def test_project_defaults_can_mix_with_bootstrap_fallback() -> None:
    selected = _selection("runtime-project", None, app=False, models=("app-model",))
    assert (selected.runtime_key, selected.runtime_source) == ("runtime-project", ExecutionSelectionSource.PROJECT)
    assert (selected.model_id, selected.model_source) == ("app-model", ExecutionSelectionSource.BOOTSTRAP)


def test_project_model_keeps_its_configured_provider_connection_and_native_name() -> None:
    from ava.configuration.execution_defaults import ApplicationExecutionDefaults

    profiles = {model_id: _profile(model_id) for model_id in ("project-model", "app-model")}
    defaults = ApplicationExecutionDefaults("connection-app-model", "app-model", "runtime-app-config")
    runtimes = RuntimeRegistry()
    runtimes.register("runtime-project", NativeRuntime())
    runtimes.register("app-runtime", NativeRuntime())
    providers = ModelProviderRegistry()
    providers.register("provider", cast(ModelProviderPort, object()))
    resolver = _PersistedResolver(defaults, profiles)
    selector = ExecutionSelector(
        runtime_resolver=RuntimeResolver(runtimes),
        model_provider_resolver=ModelProviderResolver(providers),
        model_binding_resolver=ModelBindingResolver(ModelRegistry(profiles.values()), default_model_id="app-model"),
        default_runtime_id="native",
        default_model_provider_id="provider",
        persisted_configuration_resolver=resolver,
        project_execution_defaults_resolver=_ProjectResolver(
            ProjectExecutionPreference("project-1", "runtime-project", "project-model")
        ),
    )
    execution = selector.resolve(conversation_id="project-conversation")
    assert execution.model_binding.model_id == "project-model"
    assert execution.model_binding.provider_model_name == "native-project-model"
    assert execution.provider_connection_id == "connection-project-model"


def test_native_run_metadata_keeps_project_model_provenance_when_configuration_is_persisted() -> None:
    selector, _ = _configured_selector(
        project_resolver=_ProjectResolver(
            ProjectExecutionPreference("project-metadata", None, "project-model")
        )
    )
    adapter = NativeAgentAdapter(execution_selector=selector)
    resolved = selector.resolve(conversation_id="project-conversation")

    selection = adapter._selection(resolved)

    assert selection is not None
    assert selection.model_id == "project-model"
    assert selection.model_source == ExecutionSelectionSource.PROJECT.value
    assert selection.project_id == "project-metadata"


def test_each_execution_uses_fresh_project_defaults_and_keeps_active_selection_snapshot() -> None:
    preference = _ProjectResolver(ProjectExecutionPreference("project-1", "runtime-project", "project-model"))
    active = _selection("runtime-project", "project-model", project_resolver=preference)

    preference.preference = ProjectExecutionPreference("project-1", "runtime-app", "app-model")
    retry = _selection("runtime-project", "project-model", project_resolver=preference)

    assert (active.runtime_key, active.model_id) == ("runtime-project", "project-model")
    assert (retry.runtime_key, retry.model_id) == ("runtime-app", "app-model")
    assert retry.runtime_source is ExecutionSelectionSource.PROJECT
    assert retry.model_source is ExecutionSelectionSource.PROJECT
