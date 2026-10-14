"""Safe, read-only tool activity projection for one inspected Run."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ToolActivityStatus(StrEnum):
    REQUESTED = "requested"
    REJECTED = "rejected"
    AWAITING_APPROVAL = "awaiting_approval"
    RESERVED = "reserved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INDETERMINATE = "indeterminate"


class ToolActivityItem(BaseModel):
    """One invocation summarized without operation arguments or raw output."""

    invocation_id: str
    tool_id: str
    tool_name: str | None = None
    tool_version: str | None = None
    execution_mode: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: ToolActivityStatus
    reason_code: str | None = None
    approval_required: bool = False
    recovery_status: str | None = None


class ToolActivityHistory(BaseModel):
    """Bounded history returned alongside the existing Run inspection."""

    available: bool = True
    items: list[ToolActivityItem] = Field(default_factory=list)
    has_more: bool = False
