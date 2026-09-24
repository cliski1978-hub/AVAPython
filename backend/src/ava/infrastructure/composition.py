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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.agents.contracts import AgentPort
from ava.configuration.settings import Settings
from ava.contracts.models import ModelCapabilities
from ava.execution.command_policy import SandboxedCommandExecutionPolicy
from ava.execution.hosting import ModelHostingRequirement
from ava.execution.model_orchestrator import ModelOrchestrator
from ava.execution.model_resources import (
    ModelResourceAdapterRegistry,
    ModelResourceDescriptor,
    ModelResourceManager,
    ProviderManagedResourceAdapter,
)
from ava.execution.selector import ExecutionSelector
from ava.execution.tool_security import ToolAuthorizationPolicy
from ava.infrastructure.attachment_content_store import LocalAttachmentContentStore
from ava.infrastructure.persistence import SqliteDatabase, create_relational_repositories
from ava.infrastructure.sandbox import BubblewrapSandboxedCommandRunner
from ava.models.bindings import ModelBindingResolver
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider
from ava.models.qualifications import ModelQualification, ModelQualificationStore
from ava.models.registry import ModelProviderRegistry
from ava.models.resolver import ModelProviderResolver
from ava.repositories import (
    AttachmentContentStore,
    AttachmentRepository,
    ConversationRepository,
    DocumentRepository,
    DocumentRevisionRepository,
    MessageRepository,
    RunEventRepository,
    RunRepository,
)
from ava.runtimes import RuntimeRegistry
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.adapters.openhands.openhands_runtime import OpenHandsRuntime
from ava.runtimes.resolver import RuntimeResolver
from ava.services.attachment_content_store import InMemoryAttachmentContentStore
from ava.services.attachment_store import InMemoryAttachmentRepository
from ava.services.conversation_store import ConversationStore
from ava.services.document_revision_store import InMemoryDocumentRevisionStore
from ava.services.document_store import DocumentStore
from ava.services.document_write_coordinator import (
    DocumentWriteCoordinator,
    InMemoryDocumentWriteCoordinator,
)
from ava.services.message_store import MessageStore
from ava.services.run_event_store import RunEventStore
from ava.services.run_store import RunStore
from ava.workspaces import WorkspaceRegistry, WorkspaceResolver

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

    Returns:
        A concrete ``AgentPort`` implementation for the provider.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    if provider == "native":
        if runtime_resolver is None or model_provider_resolver is None or model_binding_resolver is None:
            raise ValueError("Native agent requires runtime, model, and binding resolvers")
        return NativeAgentAdapter(
            execution_selector=ExecutionSelector(
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
            ),
            workspace_resolver=workspace_resolver,
            hosting_requirement=hosting_requirement,
            model_resource_manager=model_resource_manager,
        )
    factory = _AGENT_ADAPTER_FACTORIES.get(provider)
    if factory is None:
        raise ValueError(f"Unknown agent provider: {provider!r}")
    logger.debug("Selecting agent adapter for provider %r", provider)
    return factory()


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
    """Compose provider-managed v1 resource leases for configured models.

    Resource estimates remain unknown until a provider-specific lifecycle adapter
    supplies them. This intentionally performs no startup preload or inference.
    """
    adapter_id = "provider-managed"
    return ModelResourceManager(
        registry=registry,
        descriptors=tuple(
            ModelResourceDescriptor(model_id=profile.model_id, resource_adapter_id=adapter_id)
            for profile in registry.list()
        ),
        adapters=ModelResourceAdapterRegistry({adapter_id: ProviderManagedResourceAdapter()}),
    )


def create_runtime_registry(
    *,
    command_policy: SandboxedCommandExecutionPolicy | None = None,
    command_runner: BubblewrapSandboxedCommandRunner | None = None,
) -> RuntimeRegistry:
    """Construct the supported runtime instances for production composition."""
    registry = RuntimeRegistry()
    registry.register("native", NativeRuntime())
    registry.register(
        "openhands",
        OpenHandsRuntime(
            authorization_policy=ToolAuthorizationPolicy(), command_policy=command_policy, command_runner=command_runner
        ),
    )
    return registry


def create_workspace_registry() -> WorkspaceRegistry:
    """Construct the application-owned workspace registry.

    The registry starts empty: no workspace is provisioned or implicitly
    granted at startup, and constructing it performs no filesystem, shell, or
    network activity. The same registry is shared by the resolver and the
    discovery service so both observe the same approved registrations.
    """
    return WorkspaceRegistry()


def create_workspace_resolver(registry: WorkspaceRegistry | None = None) -> WorkspaceResolver:
    """Construct an application-owned workspace resolver.

    The registry starts empty: no workspace is provisioned or implicitly
    granted at startup, and constructing the resolver performs no filesystem,
    shell, or network activity. Workspaces are registered by provisioning
    lifecycle code before any run references them; an unregistered id fails
    cleanly during execution with ``UnknownWorkspaceError``. When an explicit
    registry is supplied it is shared (so discovery sees the same
    registrations); otherwise a fresh empty one is created.
    """
    return WorkspaceResolver(registry or WorkspaceRegistry())


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
    return OpenAICompatibleModelProvider(
        base_url=settings.local_model_base_url,
        model_name=settings.model_name,
        provider_name="local",
        api_key=None,
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
    conversation, message, document, document revision, attachment); in both
    modes the ``document_write_coordinator`` and the document adapters share
    the same store/repository instances so a write is never observed through a
    different object identity. ``dispose()`` closes the owned database exactly
    once on application shutdown (a no-op in memory mode).
    """

    run_repository: RunRepository
    run_event_repository: RunEventRepository
    conversation_repository: ConversationRepository
    message_repository: MessageRepository
    document_repository: DocumentRepository
    document_revision_repository: DocumentRevisionRepository
    attachment_repository: AttachmentRepository
    document_write_coordinator: DocumentWriteCoordinator
    database: SqliteDatabase | None = None

    def dispose(self) -> None:
        """Release any owned relational resource (a no-op in memory mode)."""
        if self.database is not None:
            self.database.dispose()


def create_application_persistence(
    settings: Settings,
    *,
    run_migrations: bool = True,
) -> ApplicationPersistence:
    """Select the application persistence implementations from settings.

    ``AVA_PERSISTENCE=memory`` (the default) selects the in-memory stores for
    every domain. ``AVA_PERSISTENCE=relational`` selects the durable
    relational adapters for every Phase 4 domain — run, run-event,
    conversation, message, document, document revision, and attachment — all
    sharing one ``SqliteDatabase``
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
        return ApplicationPersistence(
            run_repository=RunStore(),
            run_event_repository=RunEventStore(),
            conversation_repository=ConversationStore(),
            message_repository=MessageStore(),
            document_repository=documents,
            document_revision_repository=revisions,
            attachment_repository=InMemoryAttachmentRepository(),
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
            run_repository=bundle.run_repository,
            run_event_repository=bundle.run_event_repository,
            conversation_repository=bundle.conversation_repository,
            message_repository=bundle.message_repository,
            document_repository=bundle.document_repository,
            document_revision_repository=bundle.document_revision_repository,
            attachment_repository=bundle.attachment_repository,
            document_write_coordinator=bundle.document_write_coordinator,
            database=bundle.database,
        )
    raise ValueError(
        f"Unknown persistence provider {provider!r}; expected 'memory' or 'relational'."
    )


# ============================================================
# END: Application Persistence Selection
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
    raise ValueError(
        f"Unknown attachment storage provider {mode!r}; expected 'memory' or 'local'."
    )


# ============================================================
# END: Attachment Content Selection
# ============================================================
