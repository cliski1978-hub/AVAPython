"""AVA contracts package.

Framework-neutral, provider-neutral, JSON-compatible, versionable contracts.
"""

from ava.contracts.attachments import (
    AttachmentListResponse,
    AttachmentOwnerType,
    AttachmentResponse,
    AttachmentStatus,
)
from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import (
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    MessageResponse,
    MessageRole,
    MessageStatus,
    UpdateConversationRequest,
)
from ava.contracts.documents import (
    ContentFormat,
    CreateDocumentRequest,
    DocumentListResponse,
    DocumentResponse,
    UpdateDocumentRequest,
)
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import RunExecutionOverride, RunExecutionSelection
from ava.contracts.json_types import JsonValue
from ava.contracts.models import (
    ModelCapabilities,
    ModelHostingMode,
    ModelInfo,
    ModelMessage,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.contracts.responses import (
    CapabilitiesResponse,
    HealthResponse,
    HealthStatus,
    ModelDiscoveryResponse,
    ModelProviderDiscoveryItem,
    ModelProviderDiscoveryResponse,
    RunResponse,
    RunStatus,
    RuntimeDiscoveryItem,
    RuntimeDiscoveryResponse,
)
from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo
from ava.contracts.version import CONTRACT_VERSION

__all__ = [
    "CONTRACT_VERSION",
    "AttachmentListResponse",
    "AttachmentOwnerType",
    "AttachmentResponse",
    "AttachmentStatus",
    "CapabilitiesResponse",
    "CapabilityName",
    "ContentFormat",
    "ConversationListResponse",
    "ConversationMessagesResponse",
    "ConversationResponse",
    "CreateConversationRequest",
    "CreateDocumentRequest",
    "CreateMessageRequest",
    "DocumentListResponse",
    "DocumentResponse",
    "ErrorCategory",
    "ErrorResponse",
    "EventType",
    "HealthResponse",
    "HealthStatus",
    "JsonValue",
    "ModelCapabilities",
    "ModelDiscoveryResponse",
    "ModelHostingMode",
    "ModelInfo",
    "ModelMessage",
    "ModelProviderDiscoveryItem",
    "ModelProviderDiscoveryResponse",
    "ModelProviderHealth",
    "ModelProviderHealthStatus",
    "ModelRequest",
    "ModelResponse",
    "MessageResponse",
    "MessageRole",
    "MessageStatus",
    "RunEvent",
    "RunExecutionSelection",
    "RunExecutionOverride",
    "RunRequest",
    "RunResponse",
    "RunStatus",
    "RuntimeDiscoveryItem",
    "RuntimeDiscoveryResponse",
    "RuntimeCapabilities",
    "RuntimeInfo",
    "UpdateConversationRequest",
    "UpdateDocumentRequest",
]
