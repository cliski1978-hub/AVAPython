"""AVA-owned scoped CORE prompt assignment record."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CorePromptScopeType(StrEnum):
    GLOBAL = "global"
    APPLICATION = "application"
    PROJECT = "project"
    FOLDER = "folder"
    CONVERSATION = "conversation"
    RUNTIME = "runtime"
    CAPABILITY = "capability"
    MODEL_COMPATIBILITY = "model_compatibility"


class CorePromptAssignmentMode(StrEnum):
    ENABLE = "enable"
    DISABLE = "disable"


@dataclass(frozen=True)
class CorePromptAssignmentRecord:
    id: str
    core_prompt_id: str
    scope_type: CorePromptScopeType
    scope_id: str | None
    mode: CorePromptAssignmentMode
    created_at: datetime
    updated_at: datetime
