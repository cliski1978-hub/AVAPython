"""AVA-owned Project domain record."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ProjectExecutionDefaults:
    """Independent Project preferences referencing AVA runtime/model identities."""

    runtime_key: str | None = None
    model_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("runtime_key", self.runtime_key), ("model_id", self.model_id)):
            if value is not None and not value.strip():
                raise ValueError(f"{name} must not be blank")


@dataclass(frozen=True)
class ProjectRecord:
    """Snapshot of a Project's durable workspace/context metadata.

    ``id`` is a stable, opaque AVA-owned string identity. ``created_at`` and
    ``updated_at`` are timezone-aware UTC timestamps; future write services
    own ID generation and timestamp mutation.

    A Project is distinct from a Conversation Folder: it is a workspace and
    context boundary, while a folder only organizes conversations. This
    record intentionally has no conversation linkage, files, or knowledge state.
    """

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    instructions: str | None = None
    is_archived: bool = False
    execution_defaults: ProjectExecutionDefaults = field(default_factory=ProjectExecutionDefaults)
    owner_principal_ref: str | None = None
    owner_tenant_ref: str | None = None
