"""FastAPI application factory for the AVA backend.

This module is the composition/transport adapter. It is allowed to depend on
AVA Core and the configuration layer:

    FastAPI / API Layer → AVA Core

The forbidden direction is the reverse:

    AVA Core → FastAPI / API Layer
"""

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ava.api.routes.attachments import router as attachments_router
from ava.api.routes.capabilities import router as capabilities_router
from ava.api.routes.conversations import router as conversations_router
from ava.api.routes.documents import router as documents_router
from ava.api.routes.execution_profiles import router as execution_profiles_router
from ava.api.routes.health import router as health_router
from ava.api.routes.model_providers import router as model_providers_router
from ava.api.routes.models import router as models_router
from ava.api.routes.runs import router as runs_router
from ava.api.routes.runtimes import router as runtimes_router
from ava.api.routes.workspaces import router as workspaces_router
from ava.configuration.settings import Settings, get_settings
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.core.application import Application, ApplicationConfig
from ava.execution.hosting import ModelHostingRequirement
from ava.infrastructure.composition import (
    close_model_providers,
    create_agent_adapter,
    create_application_persistence,
    create_attachment_content_store,
    create_command_execution_policy,
    create_model_orchestrator,
    create_model_provider_registry,
    create_model_qualification_store,
    create_model_registry,
    create_model_resource_manager,
    create_runtime_registry,
    create_sandboxed_command_runner,
    create_workspace_registry,
    create_workspace_resolver,
)
from ava.models import ModelBindingResolver, ModelProviderResolver
from ava.runtimes import RuntimeResolver
from ava.services.attachment_service import AttachmentService
from ava.services.capability_service import CapabilityService
from ava.services.conversation_service import ConversationService
from ava.services.document_service import DocumentService
from ava.services.execution_profile_service import ExecutionProfileService
from ava.services.model_discovery_service import ModelDiscoveryService
from ava.services.model_provider_discovery_service import ModelProviderDiscoveryService
from ava.services.run_service import RunService
from ava.services.runtime_discovery_service import RuntimeDiscoveryService
from ava.services.workspace_discovery_service import WorkspaceDiscoveryService

# ============================================================
# BEGIN: Application Factory
# ============================================================


@asynccontextmanager
async def _app_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bound the application lifecycle: startup is a no-op, shutdown releases
    provider-owned HTTP resources and the composed persistence resource."""
    yield
    registry = app.state.model_provider_registry
    if registry is not None:
        await close_model_providers(registry)
    persistence = getattr(app.state, "persistence", None)
    if persistence is not None:
        persistence.dispose()


def create_app(
    application: Application | None = None,
    *,
    cors_origins: Sequence[str] | None = None,
    hosting_requirement: ModelHostingRequirement | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Composition flow:

        Environment → Settings → ApplicationConfig → Application → Services
        Environment → Settings → Composition → ModelProviderRegistry/Resolver
        Environment → Settings → Composition → ApplicationPersistence/Repository ports

    Provider construction stays out of the API layer: the agent adapter, the
    model provider registry, and the application persistence selection are
    all composed through the infrastructure composition module.

    Args:
        application: An AVA core application root. If omitted, one is
            composed from the environment-driven Settings.
        cors_origins: Allowed CORS origins for the transport adapter.
        hosting_requirement: Optional server-owned placement policy (Step 39).
            ``None`` (the default) leaves hosting unconstrained. Clients can
            never supply this through a run request.
        settings: Explicit ``Settings`` for the application. ``None`` (the
            default) resolves settings from the environment; tests inject
            settings directly to select persistence mode without mutating the
            environment.

    Returns:
        A configured FastAPI application instance.
    """
    settings = settings or get_settings()
    core_application = application or Application(
        config=ApplicationConfig(
            application_name=settings.application_name,
            environment=settings.environment,
            agent_provider=settings.agent_provider,
            agent_runtime=settings.agent_runtime,
            model_provider=settings.model_provider,
            model_name=settings.model_name,
        )
    )

    app = FastAPI(title="AVA", version="0.1.0", lifespan=_app_lifespan)

    app.state.application = core_application

    # The runner and policy are composition-owned infrastructure. They launch
    # nothing at startup, and are passed only to the controlled OpenHands tool.
    sandboxed_command_runner = create_sandboxed_command_runner()
    command_execution_policy = create_command_execution_policy(sandboxed_command_runner)
    app.state.sandboxed_command_runner = sandboxed_command_runner
    app.state.command_execution_policy = command_execution_policy

    runtime_registry = create_runtime_registry(
        command_policy=command_execution_policy if sandboxed_command_runner.available else None,
        command_runner=sandboxed_command_runner if sandboxed_command_runner.available else None,
    )
    app.state.runtime_registry = runtime_registry
    app.state.runtime_resolver = RuntimeResolver(runtime_registry)

    # The model provider registry and resolver are composed once at startup.
    # The API layer reaches the concrete provider only through composition;
    # startup never contacts a provider runtime. Shutdown closes provider-owned
    # HTTP clients through the lifespan handler.
    model_provider_registry = create_model_provider_registry(settings)
    app.state.model_provider_registry = model_provider_registry
    app.state.model_provider_resolver = ModelProviderResolver(model_provider_registry)

    # Stable model identities are composed from configuration into a read-only
    # ModelRegistry (Step 40, the single source of truth) and a thin
    # registry-backed ModelBindingResolver. The API layer never builds bindings;
    # the agent adapter receives the resolver. The default model identity is
    # validated here at startup (unknown/disabled defaults fail closed).
    model_registry = create_model_registry(settings)
    app.state.model_registry = model_registry
    model_binding_resolver = ModelBindingResolver(model_registry, default_model_id=settings.resolved_model_id)
    app.state.model_binding_resolver = model_binding_resolver
    qualification_store = create_model_qualification_store(model_registry)
    app.state.model_qualification_store = qualification_store
    model_orchestrator = create_model_orchestrator(
        model_registry, qualification_store, default_model_id=settings.resolved_model_id
    )
    app.state.model_orchestrator = model_orchestrator
    model_resource_manager = create_model_resource_manager(model_registry)
    app.state.model_resource_manager = model_resource_manager

    # The workspace registry/resolver are composed once at startup. The
    # registry starts empty and resolution performs no filesystem, shell, or
    # network activity, so startup remains network-free. The agent adapter
    # consumes only the resolver; runtimes receive only approved bindings.
    # Discovery shares the exact same registry instance so clients see exactly
    # the registrations resolution honors.
    workspace_registry = create_workspace_registry()
    workspace_resolver = create_workspace_resolver(workspace_registry)
    app.state.workspace_registry = workspace_registry
    app.state.workspace_resolver = workspace_resolver

    # The configured agent adapter is composed once at startup. The API layer
    # consumes it only through services, never directly.
    agent_port = create_agent_adapter(
        settings.agent_provider,
        runtime_resolver=app.state.runtime_resolver,
        runtime_id=settings.agent_runtime,
        model_provider_resolver=app.state.model_provider_resolver,
        model_provider_id=settings.model_provider,
        model_binding_resolver=model_binding_resolver,
        runtime_registry=runtime_registry,
        model_provider_registry=model_provider_registry,
        model_orchestrator=model_orchestrator,
        model_resource_manager=model_resource_manager,
        workspace_resolver=workspace_resolver,
        hosting_requirement=hosting_requirement,
    )
    app.state.agent_port = agent_port
    # The application persistence set is selected by the composition layer
    # from settings: ``AVA_PERSISTENCE=memory`` (the default) installs the
    # in-memory stores for every domain; ``AVA_PERSISTENCE=relational``
    # installs the durable SQLite adapters for every Phase 4 domain — run,
    # run-event, conversation, message, document, document revision, and
    # attachment — over one shared database. Services consume only repository
    # ports and never know which implementation backs them.
    application_persistence = create_application_persistence(settings)
    app.state.persistence = application_persistence
    # Physical attachment content (Step 4.14.D) is selected independently of
    # the metadata persistence provider: AVA_ATTACHMENT_STORAGE composes the
    # one shared content store that AttachmentService (Step 4.14.E) consumes.
    # It stays off application_persistence, which remains metadata/database-only.
    app.state.attachment_content_store = create_attachment_content_store(settings)
    # The attachment service (Step 4.14.E) is composed once over the shared
    # content store and the metadata repository, and consumes both purely
    # through ports. The routes consuming it (Step 4.14.F) resolve it at
    # request time and never construct one themselves.
    app.state.attachment_service = AttachmentService(
        attachment_repository=application_persistence.attachment_repository,
        attachment_content_store=app.state.attachment_content_store,
    )
    app.state.run_service = RunService(
        agent_port,
        run_repository=application_persistence.run_repository,
        run_event_repository=application_persistence.run_event_repository,
    )
    app.state.conversation_service = ConversationService(
        conversation_repository=application_persistence.conversation_repository,
        message_repository=application_persistence.message_repository,
    )
    app.state.document_service = DocumentService(
        document_repository=application_persistence.document_repository,
        document_revision_repository=application_persistence.document_revision_repository,
        document_write_coordinator=application_persistence.document_write_coordinator,
    )
    app.state.capability_service = CapabilityService(
        application=core_application.name(),
        agent=agent_port,
    )

    # The discovery service answers "what providers are available, and are
    # they healthy?" over the same registry, using the configured default
    # provider id. It stays provider-neutral and is exercised only when the
    # endpoint is called — never at startup.
    app.state.model_provider_discovery_service = ModelProviderDiscoveryService(
        registry=model_provider_registry,
        default_provider_id=settings.model_provider,
    )
    # Read-only model catalog discovery (registry-backed, no network).
    app.state.model_discovery_service = ModelDiscoveryService(
        registry=model_registry, qualification_store=qualification_store
    )
    app.state.runtime_discovery_service = RuntimeDiscoveryService(
        registry=runtime_registry, default_runtime_id=settings.agent_runtime
    )
    app.state.workspace_discovery_service = WorkspaceDiscoveryService(registry=workspace_registry)
    app.state.execution_profile_service = ExecutionProfileService(
        runtime_id=settings.agent_runtime, provider_id=settings.model_provider
    )
    app.include_router(execution_profiles_router)
    app.include_router(runtimes_router)
    app.include_router(workspaces_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins or DEFAULT_CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(Exception, handle_unhandled_exception)

    app.include_router(health_router)
    app.include_router(capabilities_router)
    app.include_router(conversations_router)
    app.include_router(documents_router)
    app.include_router(attachments_router)
    app.include_router(model_providers_router)
    app.include_router(models_router)
    app.include_router(runs_router)

    return app


async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Map unhandled internal failures to the AVA error contract.

    Kept intentionally small: in-flight activity is awaiting completion (no
    background work exists yet), so an unhandled exception is an internal
    error. Tracebacks and adapter internals must never reach the client.
    """
    logging.getLogger("ava.api").exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="internal_error",
            category=ErrorCategory.INTERNAL,
            message="An internal error occurred.",
            recoverable=False,
        ).model_dump(mode="json"),
    )


# ============================================================
# END: Application Factory
# ============================================================


DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "tauri://localhost",
]
