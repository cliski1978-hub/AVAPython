"""AVA-owned conversation folder domain record."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConversationFolderRecord:
    """Snapshot of a flat, organizational conversation folder.

    Identity is an opaque AVA-owned string. ``created_at`` and ``updated_at``
    are authoritative timestamps; later write services own their creation and
    update semantics. Name validation belongs at the write boundary.
    """

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    owner_principal_ref: str | None = None
    owner_tenant_ref: str | None = None
