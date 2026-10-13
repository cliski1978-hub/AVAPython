"""Internal, storage-neutral outcomes of attachment text extraction."""

from dataclasses import dataclass
from enum import StrEnum


class AttachmentExtractionStatus(StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass(frozen=True)
class AttachmentExtractionResult:
    attachment_id: str
    file_name: str
    media_type: str
    status: AttachmentExtractionStatus
    text: str | None = None
    error_code: str | None = None
    error_message: str | None = None
