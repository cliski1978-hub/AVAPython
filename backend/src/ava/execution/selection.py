"""AVA-owned selection provenance, independent of provider/runtime SDK types."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ExecutionSelectionSource(StrEnum):
    """The tier that supplied one effective selection axis."""

    EXPLICIT = "explicit"
    PROJECT = "project"
    APPLICATION = "application"
    BOOTSTRAP = "bootstrap"


@dataclass(frozen=True)
class ProjectExecutionPreference:
    """Project references derived from the canonical conversation relationship."""

    project_id: str
    runtime_key: str | None
    model_id: str | None


@dataclass(frozen=True)
class ResolvedExecutionSelection:
    """Effective runtime/model identities with independent source provenance."""

    runtime_key: str
    runtime_source: ExecutionSelectionSource
    model_id: str
    model_source: ExecutionSelectionSource
    project_id: str | None = None


@runtime_checkable
class ProjectExecutionDefaultsResolverPort(Protocol):
    """Resolve Project preference references from an AVA conversation ID."""

    def resolve_for_conversation(self, conversation_id: str | None) -> ProjectExecutionPreference | None:
        """Return the linked Project defaults, if the conversation has a Project."""
        ...
