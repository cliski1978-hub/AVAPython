"""Composition seam for the relational persistence adapters (Step 4.6).

Application composition (``ava.infrastructure.composition``) selects this
relational composition for every durable domain — **run, run-event,
conversation, message, document, document revision, attachment, Project,
CORE prompts, tool features, Workspace access, and durable approvals** — when
``AVA_PERSISTENCE=relational``. Those ports feed their services over one
shared ``SqliteDatabase``; the configured default stays the in-memory stores.

Since Step 4.7, the composition bootstrap runs the migration system before
constructing repositories: schema evolution is owned by migrations, and the
factory only wires the database lifecycle + adapters.
"""

from dataclasses import dataclass

from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories import (
    RelationalApprovalRepository,
    RelationalAttachmentRepository,
    RelationalContextSummaryRepository,
    RelationalConversationFolderRepository,
    RelationalConversationRepository,
    RelationalCorePromptAssignmentRepository,
    RelationalCorePromptRepository,
    RelationalDocumentRepository,
    RelationalDocumentRevisionRepository,
    RelationalDocumentWriteCoordinator,
    RelationalExecutionDefaultsRepository,
    RelationalMessageRepository,
    RelationalModelConfigurationRepository,
    RelationalProjectFileRepository,
    RelationalProjectRepository,
    RelationalProviderConnectionRepository,
    RelationalRunEventRepository,
    RelationalRunRepository,
    RelationalRuntimeConfigurationRepository,
)
from ava.infrastructure.persistence.repositories.conversation_hard_delete_coordinator import (
    RelationalConversationHardDeleteCoordinator,
)
from ava.infrastructure.persistence.repositories.tool_feature_repository import RelationalToolFeatureRepository
from ava.infrastructure.persistence.repositories.workspace_access_repository import RelationalWorkspaceAccessRepository
from ava.repositories import (
    ApprovalRepository,
    AttachmentRepository,
    ContextSummaryRepository,
    ConversationFolderRepository,
    ConversationRepository,
    CorePromptAssignmentRepository,
    CorePromptRepository,
    DocumentRepository,
    DocumentRevisionRepository,
    ExecutionDefaultsRepository,
    MessageRepository,
    ModelConfigurationRepository,
    ProjectFileRepository,
    ProjectRepository,
    ProviderConnectionRepository,
    RunEventRepository,
    RunRepository,
    RuntimeConfigurationRepository,
)
from ava.repositories.conversation_hard_delete import ConversationHardDeleteCoordinator
from ava.repositories.tool_feature_repository import ToolFeatureRepository
from ava.repositories.workspace_access_repository import WorkspaceAccessRepository

# ============================================================
# BEGIN: Persistence Repositories
# ============================================================


@dataclass(frozen=True)
class PersistenceRepositories:
    """The relational repository adapters plus their shared database.

    Holds the five Phase 4 domain adapters, the document revision history
    adapter, the attachment metadata adapter, the independent Project adapter,
    and the document write
    coordinator (the transaction-owning seam that keeps the current
    ``documents`` row and its ``document_revisions`` history advancing
    atomically). Everything shares one ``SqliteDatabase``; the coordinator and
    the document adapters share the same repository instances so a write is
    never observed through a different connection or object identity.
    """

    database: SqliteDatabase
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
    document_write_coordinator: RelationalDocumentWriteCoordinator
    execution_defaults_repository: ExecutionDefaultsRepository
    tool_feature_repository: ToolFeatureRepository
    workspace_access_repository: WorkspaceAccessRepository
    approval_repository: ApprovalRepository
    project_repository: ProjectRepository
    project_file_repository: ProjectFileRepository
    core_prompt_repository: CorePromptRepository
    core_prompt_assignment_repository: CorePromptAssignmentRepository

    def dispose(self) -> None:
        """Close the shared database connection backing these adapters."""
        self.database.dispose()


def create_relational_repositories(
    database_url: str,
    *,
    run_migrations: bool = True,
) -> PersistenceRepositories:
    """Build the concrete relational adapters over a shared SQLite database.

    Args:
        database_url: The SQLite database location (a file path or ``:memory:``).
        run_migrations: Whether the bootstrap should run the migration system
            so the schema reaches the latest supported version before
            repositories are usable (``True`` for fresh databases and ordinary
            startups; ``False`` when the caller manages migration execution).

    Returns:
        A ``PersistenceRepositories`` set of the activated adapters plus the
        document write coordinator.
    """
    database = SqliteDatabase(database_url, auto_migrate=run_migrations)
    if run_migrations:
        database.ensure_schema()
    document_repository = RelationalDocumentRepository(database=database)
    document_revision_repository = RelationalDocumentRevisionRepository(database=database)
    provider_connection_repository = RelationalProviderConnectionRepository(database=database)
    model_configuration_repository = RelationalModelConfigurationRepository(database=database)
    runtime_configuration_repository = RelationalRuntimeConfigurationRepository(database=database)
    return PersistenceRepositories(
        approval_repository=RelationalApprovalRepository(database),
        tool_feature_repository=RelationalToolFeatureRepository(database),
        workspace_access_repository=RelationalWorkspaceAccessRepository(database),
        database=database,
        run_repository=RelationalRunRepository(database=database),
        run_event_repository=RelationalRunEventRepository(database=database),
        conversation_repository=RelationalConversationRepository(database=database),
        conversation_folder_repository=RelationalConversationFolderRepository(database=database),
        message_repository=RelationalMessageRepository(database=database),
        context_summary_repository=RelationalContextSummaryRepository(database=database),
        model_configuration_repository=model_configuration_repository,
        provider_connection_repository=provider_connection_repository,
        runtime_configuration_repository=runtime_configuration_repository,
        document_repository=document_repository,
        document_revision_repository=document_revision_repository,
        attachment_repository=RelationalAttachmentRepository(database=database),
        document_write_coordinator=RelationalDocumentWriteCoordinator(
            database=database,
            document_repository=document_repository,
            revision_repository=document_revision_repository,
        ),
        execution_defaults_repository=RelationalExecutionDefaultsRepository(
            database=database,
            provider_connections=provider_connection_repository,
            model_configurations=model_configuration_repository,
            runtime_configurations=runtime_configuration_repository,
        ),
        project_repository=RelationalProjectRepository(database=database),
        project_file_repository=RelationalProjectFileRepository(database=database),
        core_prompt_repository=RelationalCorePromptRepository(database=database),
        core_prompt_assignment_repository=RelationalCorePromptAssignmentRepository(database=database),
    )


def create_relational_conversation_hard_delete_coordinator(
    database: SqliteDatabase,
) -> ConversationHardDeleteCoordinator:
    """Construct the relational conversation hard-delete adapter.

    Keeping this concrete adapter inside persistence preserves the boundary
    that application and infrastructure composition consume through the
    exported persistence factory rather than importing repository adapters.
    """
    return RelationalConversationHardDeleteCoordinator(database=database)


# ============================================================
# END: Persistence Repositories
# ============================================================
