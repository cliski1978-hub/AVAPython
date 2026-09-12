"""Contract definitions for AVA domain events.

Framework-neutral event DTOs. Vendor SDK objects must never appear here.
Clients react to AVA events rather than framework-specific events.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from ava.contracts.json_types import JsonValue
from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Event Types
# ============================================================


class EventType(StrEnum):
    """Normalized AVA event types."""

    RUN_STARTED = "run_started"
    MESSAGE_STARTED = "message_started"
    MESSAGE_CONTENT = "message_content"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_COMPLETED = "tool_completed"
    APPROVAL_REQUESTED = "approval_requested"
    DOCUMENT_CHANGE_PROPOSED = "document_change_proposed"
    ARTIFACT_CREATED = "artifact_created"
    RUN_COMPLETED = "run_completed"
    RUN_CANCELLED = "run_cancelled"
    RUN_FAILED = "run_failed"


# ============================================================
# END: Event Types
# ============================================================


# ============================================================
# BEGIN: Run Event
# ============================================================


class RunEvent(BaseModel):
    """A normalized AVA run event.

    Every run event shares this common envelope so clients can handle all
    event types uniformly. Payload semantics vary by event_type.
    """

    event_id: str
    run_id: str
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


# ============================================================
# END: Run Event
# ============================================================