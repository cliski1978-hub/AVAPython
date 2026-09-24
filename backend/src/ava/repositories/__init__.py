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
from ava.repositories.message_repository import MessageRecord, MessageRepository
from ava.repositories.run_event_repository import (
    TERMINAL_EVENT_TYPES,
    RunEventRepository,
)
from ava.repositories.run_repository import RunRecord, RunRepository

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
    "MessageRecord",
    "MessageRepository",
    "RunEventRepository",
    "RunRepository",
    "RunRecord",
    "StoredContentInfo",
    "TERMINAL_EVENT_TYPES",
]