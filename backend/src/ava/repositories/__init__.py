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
from ava.repositories.conversation_repository import (
    ConversationRecord,
    ConversationRepository,
)
from ava.repositories.document_repository import DocumentRecord, DocumentRepository
from ava.repositories.document_revision_repository import (
    DocumentRevisionRecord,
    DocumentRevisionRepository,
)
from ava.repositories.execution_defaults_repository import ExecutionDefaultsRepository
from ava.repositories.message_repository import MessageRecord, MessageRepository
from ava.repositories.model_configuration_repository import ModelConfigurationRepository
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
    "DocumentRecord",
    "DocumentRepository",
    "DocumentRevisionRecord",
    "DocumentRevisionRepository",
    "ExecutionDefaultsRepository",
    "MessageRecord",
    "MessageRepository",
    "ModelConfigurationRepository",
    "ProviderConnectionRepository",
    "RunEventRepository",
    "RunRepository",
    "RunRecord",
    "RuntimeConfigurationRepository",
    "StoredContentInfo",
    "TERMINAL_EVENT_TYPES",
]
