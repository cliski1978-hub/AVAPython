"""AVA-owned metadata snapshot for a Project file."""

from dataclasses import dataclass
from datetime import datetime


def normalize_project_file_name(file_name: str) -> str:
    """Return the Project-scoped comparison key for a display filename."""
    return file_name.strip().casefold()


@dataclass(frozen=True)
class ProjectFileRecord:
    """Project-owned file metadata with an opaque reference to separately stored bytes.

    ``id`` is a stable opaque AVA identity (created as UUID4 by the future
    service). ``file_name`` is an authored display name, not a storage path.
    ``content_ref`` is an opaque AVA reference understood only by a content
    port. The metadata snapshot never contains bytes or storage-provider data.
    ``size_bytes`` is the measured byte count reported by the future content
    port and may be zero.
    """

    id: str
    project_id: str
    file_name: str
    content_type: str | None
    size_bytes: int
    content_ref: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("id", self.id),
            ("project_id", self.project_id),
            ("file_name", self.file_name),
            ("content_ref", self.content_ref),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.content_type is not None and not self.content_type.strip():
            raise ValueError("content_type must not be blank when provided")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ValueError("size_bytes must be an integer greater than or equal to zero")
        for field_name, timestamp in (("created_at", self.created_at), ("updated_at", self.updated_at)):
            if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
