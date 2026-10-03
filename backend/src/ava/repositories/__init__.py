"""AVA repository ports package.

Framework-neutral persistence contracts that durable implementations satisfy.

    Application Services
            ↓
    AVA Repository Ports   ← this package
            ↑
    Persistence Adapters

Only AVA-owned domain/contract types cross these interfaces. No SQL, ORM,
database drivers, vendor frameworks, or frontend types appear here.
"""

from ava.repositories.attachment_content_store import (
    AttachmentContentStore,
    StoredContentInfo,
)
from ava.repositories.attachment_repository import (
    AttachmentRecord,
    AttachmentRepository,
)
from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.repositories.conversation_folder_repository import ConversationFolderRepository
from ava.repositories.conversation_repository import (
    ConversationRecord,
    ConversationRepository,
)
from ava.repositories.core_prompt import CorePromptCategory, CorePromptRecord
from ava.repositories.core_prompt_assignment import (
    CorePromptAssignmentMode,
    CorePromptAssignmentRecord,
    CorePromptScopeType,
)
from ava.repositories.core_prompt_assignment_repository import CorePromptAssignmentRepository
from ava.repositories.core_prompt_repository import CorePromptRepository
from ava.repositories.document_repository import DocumentRecord, DocumentRepository
from ava.repositories.document_revision_repository import (
    DocumentRevisionRecord,
    DocumentRevisionRepository,
)
from ava.repositories.execution_defaults_repository import ExecutionDefaultsRepository
from ava.repositories.knowledge import (
    KnowledgeDocumentRecord,
    KnowledgeQuery,
    KnowledgeRetrievalResult,
    KnowledgeScopeRef,
    KnowledgeSourceRef,
    project_file_source_ref,
)
from ava.repositories.knowledge_ports import KnowledgeIngestionPort, KnowledgeRetrieverPort
from ava.repositories.message_repository import MessageRecord, MessageRepository
from ava.repositories.model_configuration_repository import ModelConfigurationRepository
from ava.repositories.project import ProjectExecutionDefaults, ProjectRecord
from ava.repositories.project_file import ProjectFileRecord
from ava.repositories.project_file_content import ProjectFileContentPort
from ava.repositories.project_file_repository import ProjectFileRepository
from ava.repositories.project_repository import ProjectRepository
from ava.repositories.provider_connection_repository import ProviderConnectionRepository
from ava.repositories.run_event_repository import (
    TERMINAL_EVENT_TYPES,
    RunEventRepository,
)
from ava.repositories.run_repository import RunRecord, RunRepository
from ava.repositories.runtime_configuration_repository import RuntimeConfigurationRepository

__all__ = [
    "AttachmentContentStore",
    "AttachmentRecord",
    "AttachmentRepository",
    "ConversationRecord",
    "ConversationRepository",
    "ConversationFolderRecord",
    "ConversationFolderRepository",
    "CorePromptCategory",
    "CorePromptRecord",
    "CorePromptRepository",
    "CorePromptAssignmentMode",
    "CorePromptAssignmentRecord",
    "CorePromptAssignmentRepository",
    "CorePromptScopeType",
    "DocumentRecord",
    "DocumentRepository",
    "DocumentRevisionRecord",
    "DocumentRevisionRepository",
    "ExecutionDefaultsRepository",
    "KnowledgeDocumentRecord",
    "KnowledgeIngestionPort",
    "KnowledgeQuery",
    "KnowledgeRetrievalResult",
    "KnowledgeRetrieverPort",
    "KnowledgeScopeRef",
    "KnowledgeSourceRef",
    "MessageRecord",
    "MessageRepository",
    "ModelConfigurationRepository",
    "ProviderConnectionRepository",
    "ProjectRecord",
    "ProjectExecutionDefaults",
    "ProjectFileContentPort",
    "ProjectFileRecord",
    "ProjectFileRepository",
    "ProjectRepository",
    "RunEventRepository",
    "RunRepository",
    "RunRecord",
    "RuntimeConfigurationRepository",
    "StoredContentInfo",
    "TERMINAL_EVENT_TYPES",
    "project_file_source_ref",
]
