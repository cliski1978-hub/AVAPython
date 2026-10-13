"""Captured, run-owned facts used by the Run Inspector."""

from datetime import datetime

from pydantic import BaseModel, Field

from ava.contracts.attachment_context import AttachmentContextItem
from ava.contracts.conversations import ContextMessage, ExecutionPromptLayers
from ava.contracts.events import RunEvent
from ava.contracts.execution import ExecutionMode, RunExecutionSelection
from ava.contracts.json_types import JsonValue
from ava.contracts.responses import RunStatus
from ava.contracts.version import CONTRACT_VERSION


class ContextWindowAccounting(BaseModel):
    """Captured estimate and budget used to prepare this model request."""

    context_window_tokens: int | None = None
    input_budget_tokens: int | None = None
    estimated_input_tokens: int
    output_reserve_tokens: int
    dropped_message_count: int = 0
    dropped_turn_count: int = 0
    count_accuracy: str = "estimated"
    can_fit: bool = True
    required_input_tokens: int | None = None
    model_id: str | None = None
    estimated_before_compaction_tokens: int | None = None
    compaction_recommended: bool = False
    active_summary_version: int | None = None
    active_summary_token_count: int = 0
    attachment_context_tokens: int = 0
    attachments: list[AttachmentContextItem] = Field(default_factory=list)


class ContextCompactionAccounting(BaseModel):
    attempted: bool = False
    used: bool = False
    failed: bool = False
    failure_reason: str | None = None
    summary_id: str | None = None
    summary_version: int | None = None
    summary_content: str | None = None
    summary_token_count: int = 0
    covers_through_message_id: str | None = None
    covers_through_sequence: int | None = None
    recent_message_ids: list[str] = Field(default_factory=list)
    source_token_count: int = 0
    estimated_before_tokens: int = 0
    estimated_after_tokens: int = 0
    trigger_percent: int = 80
    target_percent: int = 60


class RunInspectionSnapshot(BaseModel):
    """Execution facts captured before/after dispatch; never re-resolved later."""

    execution_resolution: dict[str, JsonValue] = Field(default_factory=dict)
    prompt_layers: ExecutionPromptLayers | None = None
    normalized_request: list[ContextMessage] = Field(default_factory=list)
    context_window: ContextWindowAccounting | None = None
    context_compaction: ContextCompactionAccounting | None = None
    attachments: list[AttachmentContextItem] = Field(default_factory=list)
    runtime_request: JsonValue | None = None
    runtime_response: JsonValue | None = None
    normalized_response: JsonValue | None = None
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class RunListItem(BaseModel):
    """Compact run-picker metadata for a conversation."""

    run_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    execution_mode: ExecutionMode = ExecutionMode.CHAT
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)


class RunInspection(BaseModel):
    """Backend-authoritative inspection response for one run."""

    run_id: str
    conversation_id: str | None = None
    source_user_message_id: str | None = None
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    execution_selection: RunExecutionSelection | None = None
    execution_mode: ExecutionMode = ExecutionMode.CHAT
    assistant_message_id: str | None = None
    assistant_message: str | None = None
    snapshot: RunInspectionSnapshot | None = None
    events: list[RunEvent] = Field(default_factory=list)
    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)
