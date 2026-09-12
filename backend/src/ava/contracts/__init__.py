"""AVA contracts package.

Framework-neutral, provider-neutral, JSON-compatible, versionable contracts.
"""

from ava.contracts.capabilities import CapabilityName
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.events import EventType, RunEvent
from ava.contracts.json_types import JsonValue
from ava.contracts.models import (
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
    RunResponse,
    RunStatus,
)
from ava.contracts.version import CONTRACT_VERSION

__all__ = [
    "CONTRACT_VERSION",
    "CapabilitiesResponse",
    "CapabilityName",
    "ErrorCategory",
    "ErrorResponse",
    "EventType",
    "HealthResponse",
    "HealthStatus",
    "JsonValue",
    "ModelInfo",
    "ModelMessage",
    "ModelProviderHealth",
    "ModelProviderHealthStatus",
    "ModelRequest",
    "ModelResponse",
    "RunEvent",
    "RunRequest",
    "RunResponse",
    "RunStatus",
]