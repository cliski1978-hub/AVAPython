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

from ava.api.principal import HttpPrincipalResolverPort, UnavailableHttpPrincipalResolver
from ava.api.routes.approvals import router as approvals_router
from ava.api.routes.attachments import router as attachments_router
from ava.api.routes.capabilities import router as capabilities_router
from ava.api.routes.conversation_folders import router as conversation_folders_router
from ava.api.routes.conversations import router as conversations_router
from ava.api.routes.core_prompts import router as core_prompts_router
from ava.api.routes.documents import router as documents_router
from ava.api.routes.execution_profiles import router as execution_profiles_router
from ava.api.routes.health import router as health_router
from ava.api.routes.model_providers import router as model_providers_router
from ava.api.routes.models import router as models_router
from ava.api.routes.projects import router as projects_router
from ava.api.routes.runs import router as runs_router
from ava.api.routes.runtimes import router as runtimes_router
from ava.api.routes.settings import router as settings_router
from ava.api.routes.tool_features import router as tool_features_router
from ava.api.routes.workspace_access import router as workspace_access_router
from ava.api.routes.workspaces import router as workspaces_router
from ava.configuration.settings import Settings, get_settings
from ava.contracts.approvals import ApprovalDecisionAuthorityPort
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.security_identity import (
    ConversationAccessPort,
    DenyPrincipalValidity,
    PrincipalValidityPort,
)
from ava.contracts.tool_features import ToolFeatureAdministrationPort
from ava.contracts.workspace_access import WorkspaceAdministrationPort
from ava.contracts.workspace_grants import WorkspaceGrantAdministrationPort
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
    create_conversation_hard_delete_coordinator,
    create_credential_resolver,
    create_execution_configuration_resolver,
    create_execution_selector,
    create_model_orchestrator,
    create_model_provider_registry,
    create_model_qualification_store,
    create_model_registry,
    create_model_resource_manager,
    create_project_file_content_store,
    create_runtime_registry,
    create_sandboxed_command_runner,
    create_tool_registry,
    create_workspace_access_lookup,
    create_workspace_registry,
    create_workspace_resolver,
)
from ava.infrastructure.workspace_admin_policy import (
    ConfiguredWorkspaceGrantAdministration,
    WorkspaceAdminApprovalDecisionAuthority,
)
from ava.models import ModelBindingResolver, ModelProviderResolver
from ava.runtimes import RuntimeResolver
from ava.services.approval_service import ApprovalService
from ava.services.attachment_extraction_service import AttachmentExtractionService
from ava.services.attachment_service import AttachmentService
from ava.services.capability_service import CapabilityService
from ava.services.context_compaction_service import ContextCompactionService
from ava.services.context_construction_service import ContextConstructionService
from ava.services.conversation_access_service import RepositoryConversationAccess
from ava.services.conversation_attachment_context_service import ConversationAttachmentContextService
from ava.services.conversation_folder_service import ConversationFolderService
from ava.services.conversation_service import ConversationService
from ava.services.core_prompt_assignment_service import CorePromptAssignmentService
from ava.services.core_prompt_service import CorePromptService
from ava.services.document_service import DocumentService
from ava.services.effective_prompt_resolver import EffectivePromptResolver
from ava.services.execution_profile_service import ExecutionProfileService
from ava.services.execution_prompt_context_service import ExecutionPromptContextService
from ava.services.model_discovery_service import ModelDiscoveryService
from ava.services.model_provider_discovery_service import ModelProviderDiscoveryService
from ava.services.project_execution_defaults_resolver import ProjectExecutionDefaultsResolver
from ava.services.project_execution_defaults_service import ProjectExecutionDefaultsService
from ava.services.project_file_service import ProjectFileService
from ava.services.project_service import ProjectService
from ava.services.run_access_service import RunAccessService
from ava.services.run_context_preparation_service import RunContextPreparationService
from ava.services.run_execution_authority_service import RunExecutionAuthorityService, RuntimeExecutionContextResolver
from ava.services.run_lifecycle_service import RunLifecycleService
from ava.services.run_recovery_service import RunRecoveryService
from ava.services.run_service import RunService
from ava.services.runtime_discovery_service import RuntimeDiscoveryService
from ava.services.runtime_tool_bridge import ToolExecutionRuntimeBridge
from ava.services.settings_service import SettingsService
from ava.services.tool_execution_service import ToolExecutionService
from ava.services.tool_feature_service import ToolFeatureService
from ava.services.tool_policy_service import ToolPolicyService
from ava.services.workspace_access_service import WorkspaceAccessService
from ava.services.workspace_discovery_service import WorkspaceDiscoveryService
from ava.services.workspace_grant_service import WorkspaceGrantService
from ava.tools.initial_tools import INITIAL_WORKSPACE_OPERATIONS

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
    feature_administration: ToolFeatureAdministrationPort | None = None,
    workspace_administration: WorkspaceAdministrationPort | None = None,
    http_principal_resolver: HttpPrincipalResolverPort | None = None,
    principal_validity: PrincipalValidityPort | None = None,
    conversation_access: ConversationAccessPort | None = None,
    workspace_grant_administration: WorkspaceGrantAdministrationPort | None = None,
    approval_decision_authority: ApprovalDecisionAuthorityPort | None = None,
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
        feature_administration: Trusted deployment-provided authority for
            feature Settings mutations. Default denies all mutations. An
            integration must authenticate the current caller or restrict the
            deployment against untrusted network access; client role flags,
            headers, UI visibility and mere loopback access are not authority.

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
    app.state.default_runtime_key = settings.agent_runtime
    app.state.attachment_max_size_bytes = settings.attachment_max_size_bytes
    app.state.http_principal_resolver = http_principal_resolver or UnavailableHttpPrincipalResolver()
    app.state.principal_validity = principal_validity or DenyPrincipalValidity()
    app.state.conversation_access = conversation_access

    app.state.application = core_application
    # Descriptive catalog only. No production handlers or tool API exist yet.
    app.state.tool_registry = create_tool_registry()

    # The runner and policy are composition-owned infrastructure. They launch
    # nothing at startup, and are passed only to the controlled OpenHands tool.
    sandboxed_command_runner = create_sandboxed_command_runner()
    command_execution_policy = create_command_execution_policy(sandboxed_command_runner)
    app.state.sandboxed_command_runner = sandboxed_command_runner
    app.state.command_execution_policy = command_execution_policy

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
    app.state.conversation_access = conversation_access or RepositoryConversationAccess(
        application_persistence.conversation_repository
    )
    app.state.run_access_service = RunAccessService(application_persistence.run_repository)
    configured_workspace_admin = (
        workspace_grant_administration or ConfiguredWorkspaceGrantAdministration.from_environment()
    )
    app.state.workspace_grant_administration = configured_workspace_admin
    app.state.workspace_grant_service = WorkspaceGrantService(
        grants=application_persistence.workspace_grant_repository,
        workspaces=application_persistence.workspace_access_repository,
        administration=configured_workspace_admin,
    )
    project_execution_defaults_resolver = ProjectExecutionDefaultsResolver(
        conversations=application_persistence.conversation_repository,
        projects=application_persistence.project_repository,
    )
    app.state.project_execution_defaults_resolver = project_execution_defaults_resolver
    # The workspace registry/resolver are composed once at startup. The
    # registry starts empty and resolution performs no filesystem, shell, or
    # network activity, so startup remains network-free. The agent adapter
    # consumes only the resolver; runtimes receive only approved bindings.
    # Discovery shares the exact same registry instance so clients see exactly
    # the registrations resolution honors.
    workspace_registry = create_workspace_registry()
    workspace_resolver = create_workspace_resolver(
        workspace_registry,
        create_workspace_access_lookup(application_persistence.workspace_access_repository),
    )
    app.state.workspace_registry = workspace_registry
    app.state.workspace_resolver = workspace_resolver

    # Normalized tool services are composed before runtimes so Native AVA gets
    # the same central execution boundary as every future runtime. The issuer
    # revalidates durable owner/grant/configuration state, while authentication
    # and session validity default-deny. There are still no production executors,
    # and memory reservations are not durable, so dispatch remains unavailable.
    app.state.tool_feature_service = ToolFeatureService(
        app.state.tool_registry,
        application_persistence.tool_feature_repository,
        feature_administration,
        on_configuration_changed=lambda: app.state.approval_service.invalidate_all_pending(),
    )
    app.state.tool_policy_service = ToolPolicyService(
        app.state.tool_registry,
        app.state.tool_feature_service,
        workspace_resolver,
        operations=INITIAL_WORKSPACE_OPERATIONS,
        command_policy=command_execution_policy,
    )
    execution_authority = (
        RunExecutionAuthorityService(
            runs=application_persistence.run_repository,
            workspaces=workspace_resolver,
            workspace_configurations=application_persistence.workspace_access_repository,
            grants=application_persistence.workspace_grant_repository,
            features=app.state.tool_feature_service,
            registry=app.state.tool_registry,
            policy=app.state.tool_policy_service,
            principal_validity=app.state.principal_validity,
        )
        if (
            http_principal_resolver is not None
            and not isinstance(http_principal_resolver, UnavailableHttpPrincipalResolver)
            and principal_validity is not None
            and not isinstance(principal_validity, DenyPrincipalValidity)
        )
        else None
    )
    app.state.execution_authority = execution_authority
    app.state.approval_service = ApprovalService(
        repository=application_persistence.approval_repository,
        runs=application_persistence.run_repository,
        policy=app.state.tool_policy_service,
        features=app.state.tool_feature_service,
        workspaces=workspace_resolver,
        execution_authority=execution_authority,
        registry=app.state.tool_registry,
        decision_authority=approval_decision_authority
        or WorkspaceAdminApprovalDecisionAuthority(configured_workspace_admin),
    )
    app.state.tool_execution_service = ToolExecutionService(
        runs=application_persistence.run_repository,
        registry=app.state.tool_registry,
        features=app.state.tool_feature_service,
        policy=app.state.tool_policy_service,
        authority=execution_authority,
        approvals=app.state.approval_service,
        executors={},
        reservations=application_persistence.invocation_reservation_repository,
        run_events=application_persistence.run_event_repository,
    )
    tool_bridge = ToolExecutionRuntimeBridge(
        execution_service=app.state.tool_execution_service,
        context_refs=RuntimeExecutionContextResolver(execution_authority) if execution_authority is not None else None,
        events=application_persistence.run_event_repository,
    )
    runtime_registry = create_runtime_registry(
        command_policy=command_execution_policy if sandboxed_command_runner.available else None,
        command_runner=sandboxed_command_runner if sandboxed_command_runner.available else None,
        tool_bridge=tool_bridge,
    )
    app.state.runtime_registry = runtime_registry
    app.state.runtime_resolver = RuntimeResolver(runtime_registry)
    app.state.configuration_bootstrap_status = bootstrap_execution_configuration(
        settings, application_persistence, runtime_registry
    )

    # Persisted execution configuration (Phase 5.16) resolves through the
    # same runtime registry that now carries the normalized tool bridge.
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

    effective_prompt_resolver = EffectivePromptResolver(
        prompts=application_persistence.core_prompt_repository,
        assignments=application_persistence.core_prompt_assignment_repository,
        conversations=application_persistence.conversation_repository,
        runtime_ids=runtime_registry.list(),
    )
    app.state.effective_prompt_resolver = effective_prompt_resolver
    app.state.execution_prompt_context_service = ExecutionPromptContextService(
        resolver=effective_prompt_resolver,
        projects=application_persistence.project_repository,
    )

    # The configured agent adapter is composed once at startup. The API layer
    # consumes it only through services, never directly.
    execution_selector = create_execution_selector(
        runtime_resolver=app.state.runtime_resolver,
        runtime_id=settings.agent_runtime,
        model_provider_resolver=app.state.model_provider_resolver,
        model_provider_id=settings.model_provider,
        model_binding_resolver=model_binding_resolver,
        runtime_registry=runtime_registry,
        model_provider_registry=model_provider_registry,
        model_orchestrator=model_orchestrator,
        hosting_requirement=hosting_requirement,
        persisted_configuration_resolver=execution_configuration_resolver,
        project_execution_defaults_resolver=project_execution_defaults_resolver,
    )
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
        project_execution_defaults_resolver=project_execution_defaults_resolver,
        execution_selector=execution_selector,
    )
    app.state.agent_port = agent_port
    # Physical attachment content (Step 4.14.D) is selected independently of
    # the metadata persistence provider: AVA_ATTACHMENT_STORAGE composes the
    # one shared content store that AttachmentService (Step 4.14.E) consumes.
    # It stays off application_persistence, which remains metadata/database-only.
    app.state.attachment_content_store = create_attachment_content_store(settings)
    app.state.project_file_content_store = create_project_file_content_store(settings)
    # The attachment service (Step 4.14.E) is composed once over the shared
    # content store and the metadata repository, and consumes both purely
    # through ports. The routes consuming it (Step 4.14.F) resolve it at
    # request time and never construct one themselves.
    app.state.attachment_service = AttachmentService(
        attachment_repository=application_persistence.attachment_repository,
        attachment_content_store=app.state.attachment_content_store,
    )
    app.state.attachment_extraction_service = AttachmentExtractionService(
        attachment_service=app.state.attachment_service,
        conversation_repository=application_persistence.conversation_repository,
        max_size_bytes=settings.attachment_max_size_bytes,
    )
    # Execution context is assembled by one AVA-owned service over the same
    # durable persistence the run service writes to, so a conversation-linked
    # run's history is read from exactly the rows that produced it. The run
    # service only forwards the result; it never builds history itself.
    app.state.context_construction_service = ContextConstructionService(
        run_repository=application_persistence.run_repository,
        message_repository=application_persistence.message_repository,
        conversation_repository=application_persistence.conversation_repository,
        attachment_context=ConversationAttachmentContextService(
            app.state.attachment_service,
            app.state.attachment_extraction_service,
        ),
    )
    app.state.run_context_preparation_service = RunContextPreparationService(
        selector=execution_selector,
        prompt_context_builder=app.state.execution_prompt_context_service,
        compaction=ContextCompactionService(application_persistence.context_summary_repository),
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
        context_preparation_service=app.state.run_context_preparation_service,
        lifecycle=app.state.run_lifecycle_service,
        approval_cancellation=lambda run_id: app.state.approval_service.cancel_for_run(run_id),
        invocation_reservations=application_persistence.invocation_reservation_repository,
        tool_name_resolver=lambda tool_id: (
            definition.name if (definition := app.state.tool_registry.get(tool_id)) is not None else None
        ),
    )
    app.state.run_recovery_service = RunRecoveryService(
        run_repository=application_persistence.run_repository,
        lifecycle=app.state.run_lifecycle_service,
    )
    hard_delete_coordinator = create_conversation_hard_delete_coordinator(application_persistence)
    app.state.conversation_service = ConversationService(
        conversation_repository=application_persistence.conversation_repository,
        message_repository=application_persistence.message_repository,
        run_repository=application_persistence.run_repository,
        run_event_repository=application_persistence.run_event_repository,
        hard_delete_coordinator=hard_delete_coordinator,
        attachment_content_store=app.state.attachment_content_store,
        project_repository=application_persistence.project_repository,
        folder_repository=application_persistence.conversation_folder_repository,
    )
    app.state.conversation_folder_service = ConversationFolderService(
        folder_repository=application_persistence.conversation_folder_repository,
        conversation_repository=application_persistence.conversation_repository,
    )
    app.state.project_file_service = ProjectFileService(
        projects=application_persistence.project_repository,
        files=application_persistence.project_file_repository,
        content=app.state.project_file_content_store,
    )
    app.state.project_service = ProjectService(
        project_repository=application_persistence.project_repository,
        project_file_service=app.state.project_file_service,
        delete_project_conversations=app.state.conversation_service.delete_project_conversations,
    )
    app.state.project_execution_defaults_service = ProjectExecutionDefaultsService(
        projects=application_persistence.project_repository,
        models=application_persistence.model_configuration_repository,
        runtimes=app.state.runtime_resolver,
    )
    app.state.core_prompt_service = CorePromptService(
        core_prompt_repository=application_persistence.core_prompt_repository
    )
    app.state.core_prompt_assignment_service = CorePromptAssignmentService(
        assignments=application_persistence.core_prompt_assignment_repository,
        prompts=application_persistence.core_prompt_repository,
        projects=application_persistence.project_repository,
        folders=application_persistence.conversation_folder_repository,
        conversations=application_persistence.conversation_repository,
        runtime_ids=runtime_registry.list(),
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
    app.state.workspace_access_service = WorkspaceAccessService(
        application_persistence.workspace_access_repository,
        workspace_administration,
        on_workspace_changed=lambda workspace_id: app.state.approval_service.invalidate_workspace(workspace_id),
    )
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
    app.include_router(tool_features_router)
    app.include_router(settings_router)
    app.include_router(runtimes_router)
    app.include_router(workspaces_router)
    app.include_router(workspace_access_router)
    app.include_router(approvals_router)

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
    app.include_router(conversation_folders_router)
    app.include_router(projects_router)
    app.include_router(core_prompts_router)
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
    errors = [{key: value for key, value in error.items() if key != "input"} for error in exc.errors()]
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
