"""Backend composition helpers.

Part of the composition/adaptation layer: selects concrete AVA adapters from
configuration-driven provider names (e.g. ``agent_provider = mock``). This
module may depend on adapter implementations and AVA-owned ports/contracts,
but never the reverse.

Core and services never import adapters directly; they program against the
ports. This module exists so provider choice stays a configuration decision,
as specified by Sprint 1.

Model-provider construction and lifecycle follow the same rule: the configured
provider is built here (never in the API factory, services, or core) and
registered into the AVA ``ModelProviderRegistry``.
"""

import logging
import platform
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.agents.contracts import AgentPort, ExecutionPromptContextBuilderPort
from ava.configuration.settings import Settings
from ava.contracts.models import ModelCapabilities
from ava.execution.command_policy import SandboxedCommandExecutionPolicy
from ava.execution.configuration_resolver import ConfigurationRepositories, ExecutionConfigurationResolver
from ava.execution.hosting import ModelHostingRequirement
from ava.execution.model_orchestrator import ModelOrchestrator
from ava.execution.model_resources import (
    DefaultResourceDescriptor,
    ModelResourceAdapterRegistry,
    ModelResourceDescriptor,
    ModelResourceManager,
    ProviderManagedResourceAdapter,
)
from ava.execution.selection import ProjectExecutionDefaultsResolverPort
from ava.execution.selector import ExecutionSelector
from ava.execution.tool_security import ToolAuthorizationPolicy
from ava.infrastructure.attachment_content_store import LocalAttachmentContentStore
from ava.infrastructure.configuration_bootstrap import BootstrapStatus, seed_execution_configuration
from ava.infrastructure.credentials import EnvironmentCredentialResolver
from ava.infrastructure.model_provider_factory import (
    BUILTIN_PROVIDER_IDS,
    ConfiguredModelProviderFactory,
    construct_compatible_provider,
    installed_provider_adapter_ids,
)
from ava.infrastructure.persistence import (
    SqliteDatabase,
    create_relational_conversation_hard_delete_coordinator,
    create_relational_repositories,
)
from ava.infrastructure.project_file_content_store import LocalProjectFileContentStore
from ava.infrastructure.sandbox import BubblewrapSandboxedCommandRunner
from ava.infrastructure.workspace_access_lookup import PersistentWorkspaceAccessLookup
from ava.models.bindings import ModelBindingResolver
from ava.models.credentials import CredentialResolver
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.provider_factory import ModelProviderFactory
from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider
from ava.models.qualifications import ModelQualification, ModelQualificationStore
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.repositories import (
    ApprovalRepository,
    AttachmentContentStore,
    AttachmentRepository,
    ContextSummaryRepository,
    ConversationFolderRepository,
    ConversationRepository,
    CorePromptAssignmentRepository,
    CorePromptRepository,
    DocumentRepository,
    DocumentRevisionRepository,
    ExecutionDefaultsRepository,
    InvocationReservationRepository,
    MessageRepository,
    ModelConfigurationRepository,
    ProjectFileContentPort,
    ProjectFileRepository,
    ProjectRepository,
    ProviderConnectionRepository,
    RunEventRepository,
    RunRepository,
    RuntimeConfigurationRepository,
)
from ava.repositories.conversation_hard_delete import ConversationHardDeleteCoordinator
from ava.repositories.invocation_reservation_repository import InMemoryInvocationReservationRepository
from ava.repositories.tool_feature_repository import ToolFeatureRepository
from ava.repositories.workspace_access_repository import WorkspaceAccessRepository
from ava.repositories.workspace_grant_repository import WorkspaceGrantRepository
from ava.runtimes import RuntimeRegistry
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.adapters.openhands.openhands_runtime import OpenHandsRuntime
from ava.runtimes.contracts import RuntimeToolBridgePort
from ava.runtimes.resolver import RuntimeResolver
from ava.services.approval_store import ApprovalStore
from ava.services.attachment_content_store import InMemoryAttachmentContentStore
from ava.services.attachment_store import InMemoryAttachmentRepository
from ava.services.context_summary_store import ContextSummaryStore
from ava.services.conversation_folder_store import ConversationFolderStore
from ava.services.conversation_hard_delete_coordinator import InMemoryConversationHardDeleteCoordinator
from ava.services.conversation_store import ConversationStore
from ava.services.core_prompt_assignment_store import CorePromptAssignmentStore
from ava.services.core_prompt_store import CorePromptStore
from ava.services.document_revision_store import InMemoryDocumentRevisionStore
from ava.services.document_store import DocumentStore
from ava.services.document_write_coordinator import (
    DocumentWriteCoordinator,
    InMemoryDocumentWriteCoordinator,
)
from ava.services.execution_defaults_store import ExecutionDefaultsStore
from ava.services.message_store import MessageStore
from ava.services.model_configuration_store import ModelConfigurationStore
from ava.services.project_file_content_store import InMemoryProjectFileContentStore
from ava.services.project_file_store import ProjectFileStore
from ava.services.project_store import ProjectStore
from ava.services.provider_connection_store import ProviderConnectionStore
from ava.services.run_event_store import RunEventStore
from ava.services.run_store import RunStore
from ava.services.runtime_configuration_store import RuntimeConfigurationStore
from ava.services.tool_feature_store import ToolFeatureStore
from ava.services.workspace_access_store import WorkspaceAccessStore
from ava.services.workspace_grant_store import WorkspaceGrantStore
from ava.tools import ToolRegistry
from ava.tools.initial_tools import initial_workspace_tools
from ava.tools.workspace_filesystem import WorkspaceFilesystemSecurityPort
from ava.tools.workspace_read import WorkspaceReadExecutor
from ava.workspaces import WorkspaceRegistry, WorkspaceResolver
from ava.workspaces.contracts import WorkspaceAccessLookupPort

logger = logging.getLogger(__name__)

#: Map of configured agent provider names to adapter constructors.
_AGENT_ADAPTER_FACTORIES: dict[str, Callable[[], AgentPort]] = {
    "mock": MockAgentAdapter,
}


def create_agent_adapter(
    provider: str,
    *,
    runtime_resolver: RuntimeResolver | None = None,
    runtime_id: str = "native",
    model_provider_resolver: ModelProviderResolver | None = None,
    model_provider_id: str = "local",
    model_binding_resolver: ModelBindingResolver | None = None,
    runtime_registry: RuntimeRegistry | None = None,
    model_provider_registry: ModelProviderRegistry | None = None,
    model_orchestrator: ModelOrchestrator | None = None,
    model_resource_manager: ModelResourceManager | None = None,
    workspace_resolver: WorkspaceResolver | None = None,
    hosting_requirement: ModelHostingRequirement | None = None,
    persisted_configuration_resolver: ExecutionConfigurationResolver | None = None,
    project_execution_defaults_resolver: ProjectExecutionDefaultsResolverPort | None = None,
    prompt_context_builder: ExecutionPromptContextBuilderPort | None = None,
    execution_selector: ExecutionSelector | None = None,
) -> AgentPort:
    """Construct the agent adapter for the configured provider name.

    Args:
        provider: The ``agent_provider`` value from configuration
            (e.g. ``"mock"`` or ``"native"``).
        model_provider_resolver: Composition-owned resolver; used only for native.
        model_provider_id: Configured model provider identity, resolved only for native.
        workspace_resolver: Composition-owned workspace resolver; used only for
            native. Runtimes never receive the resolver — only the approved
            binding produced during execution.
        hosting_requirement: Optional server-owned placement policy (Step 39).
            ``None`` (the default) leaves hosting unconstrained; clients never
            supply this through a run request.
        persisted_configuration_resolver: Optional resolver over persisted
            application defaults. When supplied, the native agent prefers
            persisted defaults over bootstrap configuration. The selector
            receives only the capability, never the repositories, so no
            configuration storage is named here.

    Returns:
        A concrete ``AgentPort`` implementation for the provider.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    if provider == "native":
        if runtime_resolver is None or model_provider_resolver is None or model_binding_resolver is None:
            raise ValueError("Native agent requires runtime, model, and binding resolvers")
        return NativeAgentAdapter(
            execution_selector=execution_selector
            or create_execution_selector(
                runtime_resolver=runtime_resolver,
                runtime_id=runtime_id,
                model_provider_resolver=model_provider_resolver,
                model_provider_id=model_provider_id,
                model_binding_resolver=model_binding_resolver,
                runtime_registry=runtime_registry,
                model_provider_registry=model_provider_registry,
                model_orchestrator=model_orchestrator,
                hosting_requirement=hosting_requirement,
                persisted_configuration_resolver=persisted_configuration_resolver,
                project_execution_defaults_resolver=project_execution_defaults_resolver,
            ),
            workspace_resolver=workspace_resolver,
            hosting_requirement=hosting_requirement,
            model_resource_manager=model_resource_manager,
            prompt_context_builder=prompt_context_builder,
        )
    factory = _AGENT_ADAPTER_FACTORIES.get(provider)
    if factory is None:
        raise ValueError(f"Unknown agent provider: {provider!r}")
    logger.debug("Selecting agent adapter for provider %r", provider)
    return factory()


def create_execution_selector(
    *,
    runtime_resolver: RuntimeResolver,
    runtime_id: str,
    model_provider_resolver: ModelProviderResolver,
    model_provider_id: str,
    model_binding_resolver: ModelBindingResolver,
    runtime_registry: RuntimeRegistry | None = None,
    model_provider_registry: ModelProviderRegistry | None = None,
    model_orchestrator: ModelOrchestrator | None = None,
    hosting_requirement: ModelHostingRequirement | None = None,
    persisted_configuration_resolver: ExecutionConfigurationResolver | None = None,
    project_execution_defaults_resolver: ProjectExecutionDefaultsResolverPort | None = None,
) -> ExecutionSelector:
    """Compose the one execution selector shared by preparation and dispatch."""
    return ExecutionSelector(
        runtime_resolver=runtime_resolver,
        model_provider_resolver=model_provider_resolver,
        model_binding_resolver=model_binding_resolver,
        default_runtime_id=runtime_id,
        default_model_provider_id=model_provider_id,
        runtime_registry=runtime_registry,
        model_provider_registry=model_provider_registry,
        eligible_runtime_ids=frozenset({"native"}),
        model_orchestrator=model_orchestrator,
        hosting_requirement=hosting_requirement,
        persisted_configuration_resolver=persisted_configuration_resolver,
        project_execution_defaults_resolver=project_execution_defaults_resolver,
    )


def create_model_provider_registry(settings: Settings) -> ModelProviderRegistry:
    """Construct the model provider registry with the configured real providers.

    Provider-specific construction lives in this composition/adaptation layer —
    never in the API factory, services, core, or configuration. Only real,
    constructed providers are registered; no placeholders.

    Currently a local OpenAI-compatible provider is constructed and registered
    under ``"local"`` when ``model_provider == "local"`` (the default). An
    unknown configured identity (e.g. ``"corporate"``) leaves the registry
    empty. Mock startup remains possible; native-agent composition resolves the
    identity and raises the existing ``UnknownModelProviderError``.

    Args:
        settings: The environment-driven application settings.

    Returns:
        A populated ``ModelProviderRegistry``.
    """
    registry = ModelProviderRegistry()
    if settings.model_provider == "local":
        registry.register("local", _create_local_model_provider(settings))
    return registry


def create_configured_model_profiles(settings: Settings) -> tuple[ModelProfile, ...]:
    """Build the configured model profiles from bootstrap configuration.

    Step 40's single source of truth. The legacy single-model configuration
    yields exactly one profile whose stable ``model_id`` is ``AVA_MODEL_ID`` (or
    a derived legacy id), mapping the configured provider to the configured
    provider-native model name and hosting mode (``AVA_MODEL_HOSTING_MODE``,
    defaulting to ``local``). Declared capabilities are conservative (``chat``).

    Additional profiles are supplied by composition (multi-model inventories
    are a later increment); no environment DSL is introduced here.

    Args:
        settings: The environment-driven application settings.

    Returns:
        An ordered tuple of configured ``ModelProfile``s.
    """
    return (
        ModelProfile(
            model_id=settings.resolved_model_id,
            display_name=settings.model_name,
            provider_id=settings.model_provider,
            provider_model_name=settings.model_name,
            hosting_mode=settings.model_hosting_mode,
            capabilities=ModelCapabilities(chat=True),
            enabled=True,
        ),
    )


def create_model_registry(
    settings: Settings,
    *,
    profiles: tuple[ModelProfile, ...] | None = None,
) -> ModelRegistry:
    """Construct the read-only model catalog from configuration.

    Args:
        settings: The environment-driven application settings (used to derive
            the bootstrap profile when ``profiles`` is omitted).
        profiles: Optional explicit profile inventory. When supplied it fully
            replaces the bootstrap-derived profiles (a deterministic
            composition seam for multi-model deployments and tests).

    Returns:
        A ``ModelRegistry`` indexing the configured profiles by stable identity.
    """
    if profiles is None and any(
        not value.strip()
        for value in (
            settings.resolved_model_id,
            settings.model_name,
            settings.model_provider,
        )
    ):
        # Keep Settings reachable when legacy execution is unconfigured.
        return ModelRegistry(())
    return ModelRegistry(profiles if profiles is not None else create_configured_model_profiles(settings))


def create_model_qualifications() -> tuple[ModelQualification, ...]:
    """Return curated production qualification metadata.

    The bootstrap model identity has no deterministic historical-artifact
    mapping, so production begins with no asserted qualification evidence.
    """
    return ()


def create_model_qualification_store(
    registry: ModelRegistry,
    *,
    qualifications: tuple[ModelQualification, ...] | None = None,
) -> ModelQualificationStore:
    """Compose the read-only qualification store for the configured catalog."""
    return ModelQualificationStore(
        registry, create_model_qualifications() if qualifications is None else qualifications
    )


def create_model_orchestrator(
    registry: ModelRegistry,
    qualification_store: ModelQualificationStore,
    *,
    default_model_id: str,
) -> ModelOrchestrator:
    """Compose deterministic selection policy over catalog metadata only."""
    return ModelOrchestrator(
        registry=registry,
        qualification_store=qualification_store,
        default_model_id=default_model_id,
    )


def create_model_resource_manager(registry: ModelRegistry) -> ModelResourceManager:
    """Compose provider-managed v1 resource leases for selected models.

    Resource estimates remain unknown until a provider-specific lifecycle adapter
    supplies them. This intentionally performs no startup preload or inference.

    A default descriptor stands in for models AVA did not catalog, which
    Phase 5.16 made selectable: a persisted ``ModelConfiguration`` names a
    configured model with no startup descriptor, and refusing to lease it would
    fail every persisted run — including remote models that need no AVA-local
    lifecycle at all. Leasing is downstream of selection, so the default only
    ever describes a model that was already chosen; it cannot introduce one, and
    it supplies no capabilities, hosting mode, or capacity estimates.
    """
    adapter_id = "provider-managed"
    return ModelResourceManager(
        registry=registry,
        descriptors=tuple(
            ModelResourceDescriptor(model_id=profile.model_id, resource_adapter_id=adapter_id)
            for profile in registry.list()
        ),
        adapters=ModelResourceAdapterRegistry({adapter_id: ProviderManagedResourceAdapter()}),
        default_descriptor=DefaultResourceDescriptor(resource_adapter_id=adapter_id),
    )


def create_runtime_registry(
    *,
    command_policy: SandboxedCommandExecutionPolicy | None = None,
    command_runner: BubblewrapSandboxedCommandRunner | None = None,
    tool_bridge: RuntimeToolBridgePort | None = None,
) -> RuntimeRegistry:
    """Construct the supported runtime instances for production composition."""
    registry = RuntimeRegistry()
    registry.register("native", NativeRuntime(tool_bridge=tool_bridge))
    registry.register(
        "openhands",
        OpenHandsRuntime(
            authorization_policy=ToolAuthorizationPolicy(), command_policy=command_policy, command_runner=command_runner
        ),
    )
    return registry


def create_tool_registry() -> ToolRegistry:
    """Construct AVA's explicit descriptive catalog; no handlers exist.

    Trusted future bootstrap code can register existing ToolDefinition values.
    No user configuration, SDK tool discovery or fake production tool is loaded.
    """
    registry = ToolRegistry()
    for definition in initial_workspace_tools():
        registry.register(definition)
    return registry


def create_workspace_read_executor() -> WorkspaceReadExecutor:
    """Select a secure host adapter from the backend execution host only."""
    filesystem: WorkspaceFilesystemSecurityPort
    if platform.system() == "Linux":
        from ava.infrastructure.workspace_filesystem.linux import LinuxWorkspaceFilesystemAdapter

        filesystem = LinuxWorkspaceFilesystemAdapter()
    elif platform.system() == "Windows":
        from ava.infrastructure.workspace_filesystem.windows import WindowsWorkspaceFilesystemAdapter

        filesystem = WindowsWorkspaceFilesystemAdapter()
    else:
        from ava.infrastructure.workspace_filesystem.unavailable import UnavailableWorkspaceFilesystemAdapter

        filesystem = UnavailableWorkspaceFilesystemAdapter()
    return WorkspaceReadExecutor(filesystem)


def create_workspace_registry() -> WorkspaceRegistry:
    """Construct the application-owned workspace registry.

    The registry starts empty: no workspace is provisioned or implicitly
    granted at startup, and constructing it performs no filesystem, shell, or
    network activity. The same registry is shared by the resolver and the
    discovery service so both observe the same approved registrations.
    """
    return WorkspaceRegistry()


def create_workspace_resolver(
    registry: WorkspaceRegistry | None = None,
    access_lookup: WorkspaceAccessLookupPort | None = None,
) -> WorkspaceResolver:
    """Construct an application-owned workspace resolver.

    The legacy registry starts empty: no workspace is provisioned or implicitly
    granted at startup, and constructing the resolver performs no filesystem,
    shell, or network activity. A separate durable configuration lookup may be
    injected for normalized-tool preflight; it does not issue caller authority
    or widen legacy runtime selection. Unknown ids fail cleanly with
    ``UnknownWorkspaceError``. An explicit registry is shared with discovery.
    """
    return WorkspaceResolver(registry or WorkspaceRegistry(), access_lookup)


def create_workspace_access_lookup(repository: WorkspaceAccessRepository) -> WorkspaceAccessLookupPort:
    """Compose current Workspace configuration behind its core lookup port."""
    return PersistentWorkspaceAccessLookup(repository)


def create_sandboxed_command_runner() -> BubblewrapSandboxedCommandRunner:
    """Compose the local Bubblewrap runner without launching a sandbox at startup."""
    return BubblewrapSandboxedCommandRunner()


def create_command_execution_policy(
    runner: BubblewrapSandboxedCommandRunner,
) -> SandboxedCommandExecutionPolicy:
    """Create a policy that authorizes commands only for an available runner."""
    return SandboxedCommandExecutionPolicy(runner_available=runner.available)


def _create_local_model_provider(settings: Settings) -> OpenAICompatibleModelProvider:
    """Construct the local OpenAI-compatible provider from settings.

    The local provider speaks the OpenAI-compatible chat-completions protocol
    to a local runtime (e.g. Ollama ``/v1``). It gets no API key and carries
    the default conservative capabilities; model and endpoint both come from
    ``Settings``.
    """
    return construct_compatible_provider(
        endpoint=settings.local_model_base_url,
        model_name=settings.model_name,
        provider_id="local",
    )


async def close_model_providers(registry: ModelProviderRegistry) -> None:
    """Close provider-owned HTTP resources during application shutdown.

    Adapter-specific lifecycle: only providers that expose an async
    ``aclose()`` (the OpenAI-compatible adapter owns its HTTP client) are
    closed here. Providers configured with an injected client are never closed
    by composition. Services and the model port never know about client
    cleanup; this exists so application shutdown is deterministic and free of
    leaked connections.

    Args:
        registry: The application's model provider registry.
    """
    for provider_id in registry.list():
        provider = registry.get(provider_id)
        if provider is None:
            continue
        aclose: Callable[[], Awaitable[None]] | None = cast(
            "Callable[[], Awaitable[None]] | None",
            getattr(provider, "aclose", None),
        )
        if aclose is None:
            continue
        logger.debug("Closing model provider %r", provider_id)
        await aclose()


# ============================================================
# BEGIN: Application Persistence Selection
# ============================================================


@dataclass(frozen=True)
class ApplicationPersistence:
    """The repository set selected for the application from settings.

    Repositories are opaque ports: nothing outside composition inspects their
    concrete implementation. Relational mode shares one owned
    ``SqliteDatabase`` across all relational adapters (run, run-event,
    conversation, message, document, document revision, attachment, Project,
    CORE prompt, Project-file metadata, tool features, Workspace access, and
    approvals); binary Project-file content stays
    behind its independent content port. In both
    modes the ``document_write_coordinator`` and the document adapters share
    the same store/repository instances so a write is never observed through a
    different object identity. ``dispose()`` closes the owned database exactly
    once on application shutdown (a no-op in memory mode).
    """

    run_repository: RunRepository
    run_event_repository: RunEventRepository
    conversation_repository: ConversationRepository
    conversation_folder_repository: ConversationFolderRepository
    message_repository: MessageRepository
    context_summary_repository: ContextSummaryRepository
    model_configuration_repository: ModelConfigurationRepository
    provider_connection_repository: ProviderConnectionRepository
    runtime_configuration_repository: RuntimeConfigurationRepository
    document_repository: DocumentRepository
    document_revision_repository: DocumentRevisionRepository
    attachment_repository: AttachmentRepository
    document_write_coordinator: DocumentWriteCoordinator
    execution_defaults_repository: ExecutionDefaultsRepository
    tool_feature_repository: ToolFeatureRepository
    workspace_access_repository: WorkspaceAccessRepository
    workspace_grant_repository: WorkspaceGrantRepository
    approval_repository: ApprovalRepository
    invocation_reservation_repository: InvocationReservationRepository
    project_repository: ProjectRepository
    core_prompt_repository: CorePromptRepository
    core_prompt_assignment_repository: CorePromptAssignmentRepository
    project_file_repository: ProjectFileRepository
    database: SqliteDatabase | None = None

    def dispose(self) -> None:
        """Release any owned relational resource (a no-op in memory mode)."""
        if self.database is not None:
            self.database.dispose()


def create_conversation_hard_delete_coordinator(
    persistence: ApplicationPersistence,
) -> ConversationHardDeleteCoordinator:
    """Compose the hard-delete adapter for the selected persistence set.

    The API factory consumes only the AVA-owned coordinator port. Concrete
    relational and in-memory implementations stay behind this composition
    boundary, alongside the other persistence selection decisions.
    """
    if persistence.database is not None:
        return create_relational_conversation_hard_delete_coordinator(persistence.database)
    return InMemoryConversationHardDeleteCoordinator(
        conversations=cast(ConversationStore, persistence.conversation_repository),
        messages=cast(MessageStore, persistence.message_repository),
        runs=cast(RunStore, persistence.run_repository),
        run_events=cast(RunEventStore, persistence.run_event_repository),
        attachments=cast(InMemoryAttachmentRepository, persistence.attachment_repository),
        assignments=persistence.core_prompt_assignment_repository,
        context_summaries=cast(ContextSummaryStore, persistence.context_summary_repository),
    )


def create_application_persistence(
    settings: Settings,
    *,
    run_migrations: bool = True,
) -> ApplicationPersistence:
    """Select the application persistence implementations from settings.

    ``AVA_PERSISTENCE=memory`` (the default) selects in-memory metadata stores
    for every domain. ``AVA_PERSISTENCE=relational`` selects durable adapters
    for run, run-event, conversation, message, document, document revision,
    attachment, Project, CORE prompts, and Project files, all sharing one
    ``SqliteDatabase``
    backed by ``persistence_database_url``. The relational path runs the migration system
    before repositories are usable (pass ``run_migrations=False`` only when
    the caller owns migration execution).

    The selection is closed over composition: an unknown provider is a
    configuration error and fails construction — the application never falls
    back to an unconfigured implementation.
    """
    provider = settings.persistence_provider
    if provider == "memory":
        documents = DocumentStore()
        revisions = InMemoryDocumentRevisionStore()
        conversations = ConversationStore()
        provider_connections = ProviderConnectionStore()
        model_configurations = ModelConfigurationStore(provider_connections=provider_connections)
        runtime_configurations = RuntimeConfigurationStore()
        core_prompt_assignments = CorePromptAssignmentStore()
        project_files = ProjectFileStore()
        return ApplicationPersistence(
            approval_repository=ApprovalStore(),
            invocation_reservation_repository=InMemoryInvocationReservationRepository(),
            tool_feature_repository=ToolFeatureStore(),
            workspace_access_repository=WorkspaceAccessStore(),
            workspace_grant_repository=WorkspaceGrantStore(),
            run_repository=RunStore(),
            run_event_repository=RunEventStore(),
            conversation_repository=conversations,
            conversation_folder_repository=ConversationFolderStore(conversations, core_prompt_assignments),
            message_repository=MessageStore(),
            context_summary_repository=ContextSummaryStore(),
            provider_connection_repository=provider_connections,
            model_configuration_repository=model_configurations,
            runtime_configuration_repository=runtime_configurations,
            execution_defaults_repository=ExecutionDefaultsStore(
                provider_connections=provider_connections,
                model_configurations=model_configurations,
                runtime_configurations=runtime_configurations,
            ),
            document_repository=documents,
            document_revision_repository=revisions,
            attachment_repository=InMemoryAttachmentRepository(),
            project_repository=ProjectStore(conversations, core_prompt_assignments, project_files),
            project_file_repository=project_files,
            core_prompt_repository=CorePromptStore(core_prompt_assignments),
            core_prompt_assignment_repository=core_prompt_assignments,
            document_write_coordinator=InMemoryDocumentWriteCoordinator(
                documents=documents,
                revisions=revisions,
            ),
        )
    if provider == "relational":
        bundle = create_relational_repositories(
            settings.persistence_database_url,
            run_migrations=run_migrations,
        )
        return ApplicationPersistence(
            approval_repository=bundle.approval_repository,
            invocation_reservation_repository=bundle.invocation_reservation_repository,
            tool_feature_repository=bundle.tool_feature_repository,
            workspace_access_repository=bundle.workspace_access_repository,
            workspace_grant_repository=bundle.workspace_grant_repository,
            run_repository=bundle.run_repository,
            run_event_repository=bundle.run_event_repository,
            conversation_repository=bundle.conversation_repository,
            conversation_folder_repository=bundle.conversation_folder_repository,
            message_repository=bundle.message_repository,
            context_summary_repository=bundle.context_summary_repository,
            provider_connection_repository=bundle.provider_connection_repository,
            model_configuration_repository=bundle.model_configuration_repository,
            runtime_configuration_repository=bundle.runtime_configuration_repository,
            execution_defaults_repository=bundle.execution_defaults_repository,
            document_repository=bundle.document_repository,
            document_revision_repository=bundle.document_revision_repository,
            attachment_repository=bundle.attachment_repository,
            project_repository=bundle.project_repository,
            project_file_repository=bundle.project_file_repository,
            core_prompt_repository=bundle.core_prompt_repository,
            core_prompt_assignment_repository=bundle.core_prompt_assignment_repository,
            document_write_coordinator=bundle.document_write_coordinator,
            database=bundle.database,
        )
    raise ValueError(f"Unknown persistence provider {provider!r}; expected 'memory' or 'relational'.")


# ============================================================
# END: Application Persistence Selection
# ============================================================


# ============================================================
# ============================================================
# BEGIN: Persisted Execution Configuration
# ============================================================


def create_credential_resolver(
    environment: Mapping[str, str] | None = None,
) -> CredentialResolver:
    """Select the secret backend that resolves persisted credential references.

    ``env:NAME`` is the only scheme Phase 5.9 defines, so the environment
    backend is the only implementation and the choice is closed: an unsupported
    scheme is reported by the resolver as a typed error, never served by a
    different backend.

    Args:
        environment: Optional variable mapping to resolve against, defaulting to
            the process environment. Injectable so a test or a later
            process-scoped snapshot never has to mutate the real environment.

    Returns:
        The application's credential resolver.
    """
    return EnvironmentCredentialResolver(environment)


def create_configured_model_provider_factory(
    settings: Settings,
    model_provider_registry: ModelProviderRegistry,
) -> ModelProviderFactory:
    """Compose the factory that builds adapters for configured connections.

    Built-in constructor support remains installed even when the legacy
    default provider differs. Compatible registry aliases are included, while
    unrelated provider protocols are never reinterpreted as OpenAI-compatible.

    The factory is created once and lives for the application, so every adapter
    it builds shares one HTTP connection pool. ``close_configured_model_provider_factory``
    releases that pool at shutdown.
    """
    return ConfiguredModelProviderFactory(
        installed_provider_ids=BUILTIN_PROVIDER_IDS | installed_provider_adapter_ids(model_provider_registry),
        default_endpoint=settings.local_model_base_url,
    )


async def close_configured_model_provider_factory(factory: ModelProviderFactory) -> None:
    """Release the connection pool shared by configured-connection adapters.

    Adapters built for persisted connections share one injected HTTP client that
    the adapters themselves never close, so the factory is where that client is
    released. Safe to call more than once, and a no-op for a factory that owns no
    client.
    """
    aclose: Callable[[], Awaitable[None]] | None = cast(
        "Callable[[], Awaitable[None]] | None",
        getattr(factory, "aclose", None),
    )
    if aclose is None:
        return
    await aclose()


def create_execution_configuration_resolver(
    persistence: ApplicationPersistence,
    *,
    runtime_resolver: RuntimeResolver,
    provider_factory: ModelProviderFactory,
    credential_resolver: CredentialResolver,
    model_orchestrator: ModelOrchestrator,
    hosting_requirement: ModelHostingRequirement | None = None,
) -> ExecutionConfigurationResolver:
    """Compose persisted execution configuration resolution.

    The four configuration repositories are bundled from the already-selected
    persistence set rather than constructed here, so resolution reads the same
    repository instances the Settings API writes to. The resolver is the only
    component that sees all four; the agent adapter and the run service receive
    only the resolution capability.
    """
    return ExecutionConfigurationResolver(
        ConfigurationRepositories(
            execution_defaults=persistence.execution_defaults_repository,
            provider_connections=persistence.provider_connection_repository,
            model_configurations=persistence.model_configuration_repository,
            runtime_configurations=persistence.runtime_configuration_repository,
        ),
        runtime_resolver=runtime_resolver,
        provider_factory=provider_factory,
        credential_resolver=credential_resolver,
        model_orchestrator=model_orchestrator,
        hosting_requirement=hosting_requirement,
    )


# ============================================================
# END: Persisted Execution Configuration
# ============================================================


# ============================================================
# BEGIN: Attachment Content Selection
# ============================================================


def create_attachment_content_store(settings: Settings) -> AttachmentContentStore:
    """Select the physical attachment content store from settings.

    ``AVA_ATTACHMENT_STORAGE=memory`` (the default) composes the in-memory
    content adapter; ``AVA_ATTACHMENT_STORAGE=local`` composes the
    local-filesystem adapter over the explicitly configured
    ``AVA_ATTACHMENT_STORAGE_ROOT`` (created if missing). Selection is fully
    independent of ``AVA_PERSISTENCE``: metadata persistence and physical
    content storage stay orthogonal, so every ``memory | relational`` x
    ``memory | local`` combination is valid.

    The seam is the single construction point for the application's shared
    content store: the API factory composes it once at startup (Step 4.14.D
    wiring) and ``AttachmentService`` (Step 4.14.E) consumes the same
    instance. An unknown mode is a configuration error and is never
    silently downgraded to memory.
    """
    mode = settings.attachment_storage
    if mode == "memory":
        return InMemoryAttachmentContentStore()
    if mode == "local":
        return LocalAttachmentContentStore(Path(settings.attachment_storage_root))
    raise ValueError(f"Unknown attachment storage provider {mode!r}; expected 'memory' or 'local'.")


def create_project_file_content_store(settings: Settings) -> ProjectFileContentPort:
    """Select independent Project-file content storage."""
    if settings.project_file_storage == "memory":
        return InMemoryProjectFileContentStore()
    if settings.project_file_storage == "local":
        return LocalProjectFileContentStore(Path(settings.project_file_storage_root))
    raise ValueError(f"Unknown Project file storage provider {settings.project_file_storage!r}.")


# ============================================================
# END: Attachment Content Selection
# ============================================================


def bootstrap_execution_configuration(
    settings: Settings,
    persistence: ApplicationPersistence,
    runtime_registry: RuntimeRegistry,
) -> BootstrapStatus:
    """Materialize legacy settings once, using the application's own stores."""
    return seed_execution_configuration(
        settings,
        ConfigurationRepositories(
            execution_defaults=persistence.execution_defaults_repository,
            provider_connections=persistence.provider_connection_repository,
            model_configurations=persistence.model_configuration_repository,
            runtime_configurations=persistence.runtime_configuration_repository,
        ),
        transaction=persistence.database.transaction if persistence.database is not None else None,
        runtime_registry=runtime_registry,
    )
