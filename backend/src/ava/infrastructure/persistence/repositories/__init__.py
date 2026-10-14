"""Concrete relational repository adapters (Step 4.6).

Each adapter implements its AVA repository port over the shared
``SqliteDatabase`` and is behaviorally compatible with the corresponding
in-memory store. This package is the only AVA code authorized to touch
database drivers/ORM tooling.
"""

from ava.infrastructure.persistence.repositories.approval_repository import RelationalApprovalRepository
from ava.infrastructure.persistence.repositories.attachment_repository import (
    RelationalAttachmentRepository,
)
from ava.infrastructure.persistence.repositories.context_summary_repository import RelationalContextSummaryRepository
from ava.infrastructure.persistence.repositories.conversation_folder_repository import (
    RelationalConversationFolderRepository,
)
from ava.infrastructure.persistence.repositories.conversation_repository import (
    RelationalConversationRepository,
)
from ava.infrastructure.persistence.repositories.core_prompt_assignment_repository import (
    RelationalCorePromptAssignmentRepository,
)
from ava.infrastructure.persistence.repositories.core_prompt_repository import RelationalCorePromptRepository
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
from ava.infrastructure.persistence.repositories.invocation_reservation_repository import (
    RelationalInvocationReservationRepository,
)
from ava.infrastructure.persistence.repositories.message_repository import (
    RelationalMessageRepository,
)
from ava.infrastructure.persistence.repositories.model_configuration_repository import (
    RelationalModelConfigurationRepository,
)
from ava.infrastructure.persistence.repositories.project_file_repository import RelationalProjectFileRepository
from ava.infrastructure.persistence.repositories.project_repository import RelationalProjectRepository
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
from ava.infrastructure.persistence.repositories.workspace_access_repository import RelationalWorkspaceAccessRepository
from ava.infrastructure.persistence.repositories.workspace_grant_repository import RelationalWorkspaceGrantRepository

__all__ = [
    "RelationalApprovalRepository",
    "RelationalAttachmentRepository",
    "RelationalConversationRepository",
    "RelationalContextSummaryRepository",
    "RelationalConversationFolderRepository",
    "RelationalCorePromptRepository",
    "RelationalCorePromptAssignmentRepository",
    "RelationalDocumentRepository",
    "RelationalDocumentRevisionRepository",
    "RelationalDocumentWriteCoordinator",
    "RelationalExecutionDefaultsRepository",
    "RelationalMessageRepository",
    "RelationalModelConfigurationRepository",
    "RelationalProviderConnectionRepository",
    "RelationalProjectRepository",
    "RelationalProjectFileRepository",
    "RelationalRunEventRepository",
    "RelationalRunRepository",
    "RelationalRuntimeConfigurationRepository",
    "RelationalWorkspaceAccessRepository",
    "RelationalWorkspaceGrantRepository",
    "RelationalInvocationReservationRepository",
]
