"""Load context candidates through the Step 1 ownership/extraction boundary."""

from ava.contracts.attachment_context import (
    AttachmentContextItem,
    AttachmentContextStatus,
    ConversationAttachmentContextPort,
)
from ava.contracts.attachment_extraction import AttachmentExtractionStatus
from ava.contracts.attachments import AttachmentOwnerType
from ava.services.attachment_extraction_service import AttachmentExtractionService
from ava.services.attachment_service import AttachmentService


class ConversationAttachmentContextService(ConversationAttachmentContextPort):
    def __init__(self, attachments: AttachmentService, extraction: AttachmentExtractionService) -> None:
        self._attachments = attachments
        self._extraction = extraction

    def load(self, conversation_id: str) -> list[AttachmentContextItem]:
        items: list[AttachmentContextItem] = []
        for record in self._attachments.list_attachments(AttachmentOwnerType.CONVERSATION, conversation_id):
            code: str | None
            message: str | None
            result = self._extraction.extract(conversation_id, record.attachment_id)
            if result is None:
                status = AttachmentContextStatus.EXTRACTION_FAILED
                code, message = "attachment_not_found", "Attachment was unavailable when context was prepared."
            else:
                status = {
                    AttachmentExtractionStatus.SUCCESS: AttachmentContextStatus.EXTRACTED,
                    AttachmentExtractionStatus.UNSUPPORTED: AttachmentContextStatus.UNSUPPORTED,
                    AttachmentExtractionStatus.FAILED: AttachmentContextStatus.EXTRACTION_FAILED,
                }[result.status]
                code, message = result.error_code, result.error_message
            items.append(
                AttachmentContextItem(
                    attachment_id=record.attachment_id,
                    file_name=record.file_name,
                    media_type=record.media_type,
                    status=status,
                    text=result.text if result else None,
                    error_code=code,
                    error_message=message,
                )
            )
        return items
