"""Concrete relational repository adapters (Step 4.6).

Each adapter implements its AVA repository port over the shared
``SqliteDatabase`` and is behaviorally compatible with the corresponding
in-memory store. This package is the only AVA code authorized to touch
database drivers/ORM tooling.
"""

from ava.infrastructure.persistence.repositories.attachment_repository import (
    RelationalAttachmentRepository,
)
from ava.infrastructure.persistence.repositories.conversation_repository import (
    RelationalConversationRepository,
)
from ava.infrastructure.persistence.repositories.document_repository import (
    RelationalDocumentRepository,
)
from ava.infrastructure.persistence.repositories.document_revision_repository import (
    RelationalDocumentRevisionRepository,
)
from ava.infrastructure.persistence.repositories.document_write_coordinator import (
    RelationalDocumentWriteCoordinator,
)
from ava.infrastructure.persistence.repositories.execution_defaults_repository import (
    RelationalExecutionDefaultsRepository,
)
from ava.infrastructure.persistence.repositories.message_repository import (
    RelationalMessageRepository,
)
from ava.infrastructure.persistence.repositories.model_configuration_repository import (
    RelationalModelConfigurationRepository,
)
from ava.infrastructure.persistence.repositories.provider_connection_repository import (
    RelationalProviderConnectionRepository,
)
from ava.infrastructure.persistence.repositories.run_event_repository import (
    RelationalRunEventRepository,
)
from ava.infrastructure.persistence.repositories.run_repository import (
    RelationalRunRepository,
)
from ava.infrastructure.persistence.repositories.runtime_configuration_repository import (
    RelationalRuntimeConfigurationRepository,
)

__all__ = [
    "RelationalAttachmentRepository",
    "RelationalConversationRepository",
    "RelationalDocumentRepository",
    "RelationalDocumentRevisionRepository",
    "RelationalDocumentWriteCoordinator",
    "RelationalExecutionDefaultsRepository",
    "RelationalMessageRepository",
    "RelationalModelConfigurationRepository",
    "RelationalProviderConnectionRepository",
    "RelationalRunEventRepository",
    "RelationalRunRepository",
    "RelationalRuntimeConfigurationRepository",
]
