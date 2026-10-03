"""AVA-owned reusable CORE system prompt definition."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CorePromptCategory(StrEnum):
    """Organizational category for reusable prompt definitions, not a scope."""

    CORE = "core"
    ENGINEERING = "engineering"
    RESEARCH = "research"
    SAFETY = "safety"
    STYLE = "style"
    TOOL_USE = "tool_use"
    ARCHITECTURE = "architecture"
    ORGANIZATION = "organization"
    GENERAL = "general"


@dataclass(frozen=True)
class CorePromptRecord:
    """Immutable snapshot of a reusable, provider-neutral prompt definition.

    ``id`` is a stable, opaque AVA-owned identity. Creation and update services
    own identity/timestamp mutation. This definition contains no assignment,
    scope, priority, inheritance, or execution-injection behavior.
    """

    id: str
    name: str
    description: str | None
    prompt_text: str
    category: CorePromptCategory
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
