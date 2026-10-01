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
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
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
from ava.api.routes.settings import router as settings_router
from ava.api.routes.workspaces import router as workspaces_router
from ava.configuration.settings import Settings, get_settings
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.core.application import Application, ApplicationConfig
from ava.execution.hosting import ModelHostingRequirement
from ava.infrastructure.composition import (
    bootstrap_execution_configuration,
    close_configured_model_provider_factory,
    close_model_providers,
    create_agent_adapter,
    create_application_persistence,
    create_attachment_content_store,
    create_command_execution_policy,
    create_configured_model_provider_factory,
    create_credential_resolver,
    create_execution_configuration_resolver,
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
from ava.services.context_construction_service import ContextConstructionService
from ava.services.conversation_service import ConversationService
from ava.services.document_service import DocumentService
from ava.services.execution_profile_service import ExecutionProfileService
from ava.services.model_discovery_service import ModelDiscoveryService
from ava.services.model_provider_discovery_service import ModelProviderDiscoveryService
from ava.services.run_lifecycle_service import RunLifecycleService
from ava.services.run_recovery_service import RunRecoveryService
from ava.services.run_service import RunService
from ava.services.runtime_discovery_service import RuntimeDiscoveryService
from ava.services.settings_service import SettingsService
from ava.services.workspace_discovery_service import WorkspaceDiscoveryService

# ============================================================
# BEGIN: Application Factory
# ============================================================


@asynccontextmanager
async def _app_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Reconcile stranded runs before readiness, then release resources."""
    app.state.run_recovery_summary = app.state.run_recovery_service.recover_stranded_runs()
    yield
    registry = app.state.model_provider_registry
    if registry is not None:
        await close_model_providers(registry)
    # Adapters built for persisted connections share one injected HTTP client
    # that the adapters never close themselves, so the factory releases it.
    factory = getattr(app.state, "model_provider_factory", None)
    if factory is not None:
        await close_configured_model_provider_factory(factory)
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
    model_binding_resolver = ModelBindingResolver(
        model_registry, default_model_id=settings.resolved_model_id, allow_unconfigured=True
    )
    app.state.model_binding_resolver = model_binding_resolver
    qualification_store = create_model_qualification_store(model_registry)
    app.state.model_qualification_store = qualification_store
    model_orchestrator = create_model_orchestrator(
        model_registry, qualification_store, default_model_id=settings.resolved_model_id
    )
    app.state.model_orchestrator = model_orchestrator
    model_resource_manager = create_model_resource_manager(model_registry)
    app.state.model_resource_manager = model_resource_manager

    # The application persistence set is selected by the composition layer
    # from settings: ``AVA_PERSISTENCE=memory`` (the default) installs the
    # in-memory stores for every domain; ``AVA_PERSISTENCE=relational``
    # installs the durable SQLite adapters for every Phase 4 domain — run,
    # run-event, conversation, message, document, document revision, and
    # attachment — over one shared database. Services consume only repository
    # ports and never know which implementation backs them.
    #
    # Composed before the agent adapter because Phase 5.16 execution
    # configuration resolution reads the persisted configuration repositories
    # from this exact set, so a run resolves against the same repository
    # instances the Settings API writes to.
    application_persistence = create_application_persistence(settings)
    app.state.persistence = application_persistence
    app.state.configuration_bootstrap_status = bootstrap_execution_configuration(
        settings, application_persistence, runtime_registry
    )

    # Persisted execution configuration (Phase 5.16). The provider factory is
    # composed from the already-built registry, so the adapter types a
    # configured connection may name are exactly the installed ones, and the
    # resolver is the single component that reads all four configuration
    # repositories. The agent adapter receives only the resolution capability.
    configured_provider_factory = create_configured_model_provider_factory(settings, model_provider_registry)
    app.state.model_provider_factory = configured_provider_factory
    execution_configuration_resolver = create_execution_configuration_resolver(
        application_persistence,
        runtime_resolver=app.state.runtime_resolver,
        provider_factory=configured_provider_factory,
        credential_resolver=create_credential_resolver(),
        model_orchestrator=model_orchestrator,
        hosting_requirement=hosting_requirement,
    )
    app.state.execution_configuration_resolver = execution_configuration_resolver

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
        persisted_configuration_resolver=execution_configuration_resolver,
    )
    app.state.agent_port = agent_port
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
    # Execution context is assembled by one AVA-owned service over the same
    # durable persistence the run service writes to, so a conversation-linked
    # run's history is read from exactly the rows that produced it. The run
    # service only forwards the result; it never builds history itself.
    app.state.context_construction_service = ContextConstructionService(
        run_repository=application_persistence.run_repository,
        message_repository=application_persistence.message_repository,
        conversation_repository=application_persistence.conversation_repository,
    )
    app.state.run_lifecycle_service = RunLifecycleService(
        run_repository=application_persistence.run_repository,
        run_event_repository=application_persistence.run_event_repository,
    )
    app.state.run_service = RunService(
        agent_port,
        run_repository=application_persistence.run_repository,
        run_event_repository=application_persistence.run_event_repository,
        conversation_repository=application_persistence.conversation_repository,
        message_repository=application_persistence.message_repository,
        context_service=app.state.context_construction_service,
        lifecycle=app.state.run_lifecycle_service,
    )
    app.state.run_recovery_service = RunRecoveryService(
        run_repository=application_persistence.run_repository,
        lifecycle=app.state.run_lifecycle_service,
    )
    app.state.conversation_service = ConversationService(
        conversation_repository=application_persistence.conversation_repository,
        message_repository=application_persistence.message_repository,
        run_repository=application_persistence.run_repository,
        run_event_repository=application_persistence.run_event_repository,
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
    # Read-only model catalog discovery (registry + persisted configuration, no network).
    app.state.model_discovery_service = ModelDiscoveryService(
        registry=model_registry,
        qualification_store=qualification_store,
        model_configurations=application_persistence.model_configuration_repository,
        provider_connections=application_persistence.provider_connection_repository,
        execution_defaults=application_persistence.execution_defaults_repository,
    )
    app.state.runtime_discovery_service = RuntimeDiscoveryService(
        registry=runtime_registry, default_runtime_id=settings.agent_runtime
    )
    app.state.workspace_discovery_service = WorkspaceDiscoveryService(registry=workspace_registry)
    app.state.execution_profile_service = ExecutionProfileService(
        runtime_id=settings.agent_runtime, provider_id=settings.model_provider
    )
    # Settings management (Phase 5.10) is a separate boundary from discovery.
    # This service manages the persisted Phase 5 configuration domains only:
    # it resolves no credential, constructs no provider, and is not consulted by
    # run execution. RunService above stays independent of all of it.
    app.state.settings_service = SettingsService(
        provider_connections=application_persistence.provider_connection_repository,
        models=application_persistence.model_configuration_repository,
        runtimes=application_persistence.runtime_configuration_repository,
        execution_defaults=application_persistence.execution_defaults_repository,
    )
    app.include_router(execution_profiles_router)
    app.include_router(settings_router)
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
    # FastAPI echoes the rejected input back in its default 422 body. On the
    # Settings surface that is a credential-echo path: a client that mistakenly
    # posts a secret into a rejected field would have it reflected verbatim. The
    # Settings-only handler strips the echoed value while keeping the field
    # locations and messages, and every other endpoint keeps FastAPI's default
    # shape unchanged.
    app.add_exception_handler(RequestValidationError, handle_settings_validation_error)

    app.include_router(health_router)
    app.include_router(capabilities_router)
    app.include_router(conversations_router)
    app.include_router(documents_router)
    app.include_router(attachments_router)
    app.include_router(model_providers_router)
    app.include_router(models_router)
    app.include_router(runs_router)

    return app


async def handle_settings_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Strip FastAPI's echoed input from validation errors on ``/settings``.

    FastAPI's default 422 body includes ``input``, the exact value that failed
    validation. The Settings API is the one surface where a user may
    plausibly paste a secret into a field by mistake, so the value is removed
    for these paths and only the field locations and messages survive. Routes
    outside ``/settings`` keep FastAPI's default response unchanged, so no
    existing endpoint's contract moves.
    """
    if not isinstance(exc, RequestValidationError):
        return await handle_unhandled_exception(request, exc)
    if not request.url.path.startswith("/settings"):
        return await request_validation_exception_handler(request, exc)
    errors = [
        {key: value for key, value in error.items() if key != "input"}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(errors)},
    )


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
