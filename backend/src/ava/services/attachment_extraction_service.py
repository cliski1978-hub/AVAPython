"""On-demand extraction of stored conversation attachments, independent of runs."""

from ava.contracts.attachment_extraction import AttachmentExtractionResult, AttachmentExtractionStatus
from ava.contracts.attachments import AttachmentOwnerType
from ava.repositories.attachment_repository import AttachmentRecord
from ava.repositories.conversation_repository import ConversationRepository
from ava.services.attachment_service import AttachmentService, AttachmentStateError

_TEXT_EXTENSIONS = frozenset({"txt", "md", "json", "csv"})
_TEXT_MEDIA_TYPES = frozenset({"text/plain", "text/markdown", "text/csv", "application/json"})


def _result(
    record: AttachmentRecord,
    status: AttachmentExtractionStatus,
    *,
    text: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> AttachmentExtractionResult:
    return AttachmentExtractionResult(
        attachment_id=record.attachment_id,
        file_name=record.file_name,
        media_type=record.media_type,
        status=status,
        text=text,
        error_code=error_code,
        error_message=error_message,
    )


class AttachmentTextExtractor:
    """Conservative V1 text policy; never parses or transforms document content."""

    def supports(self, record: AttachmentRecord) -> bool:
        name = record.file_name.strip().casefold()
        # An explicit unsupported extension wins over a caller-supplied MIME.
        # MIME is useful only for extensionless text-like uploads.
        if "." in name:
            return name.rsplit(".", 1)[1] in _TEXT_EXTENSIONS
        return record.media_type.split(";", 1)[0].strip().casefold() in _TEXT_MEDIA_TYPES

    def extract(self, record: AttachmentRecord, content: bytes) -> AttachmentExtractionResult:
        if not self.supports(record):
            return _result(
                record,
                AttachmentExtractionStatus.UNSUPPORTED,
                error_code="attachment_type_unsupported",
                error_message="Text extraction is not supported for this file type.",
            )
        try:
            text = content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            return _result(
                record,
                AttachmentExtractionStatus.FAILED,
                error_code="attachment_text_decode_failed",
                error_message="Could not decode attachment as UTF-8 text.",
            )
        # Reject binary control bytes even when the bytes happen to be UTF-8.
        if any((ord(char) < 32 and char not in "\t\n\r") or 127 <= ord(char) <= 159 for char in text):
            return _result(
                record,
                AttachmentExtractionStatus.FAILED,
                error_code="attachment_binary_content",
                error_message="Attachment contains binary control characters rather than supported text.",
            )
        return _result(record, AttachmentExtractionStatus.SUCCESS, text=text)


class AttachmentExtractionService:
    """Validate exact Conversation ownership before opening a stored byte stream.

    None means missing Conversation/attachment or wrong ownership, matching the
    scoped attachment routes' not-found behavior. Known, owned extraction errors
    are normalized results and never mutate attachment lifecycle or content.
    """

    def __init__(
        self,
        *,
        attachment_service: AttachmentService,
        conversation_repository: ConversationRepository,
        max_size_bytes: int,
        extractor: AttachmentTextExtractor | None = None,
    ) -> None:
        if max_size_bytes <= 0:
            raise ValueError("Attachment extraction size limit must be positive")
        self._attachments = attachment_service
        self._conversations = conversation_repository
        self._maximum = max_size_bytes
        self._extractor = extractor or AttachmentTextExtractor()

    def extract(self, conversation_id: str, attachment_id: str) -> AttachmentExtractionResult | None:
        if self._conversations.get(conversation_id) is None:
            return None
        record = self._attachments.get_attachment(attachment_id)
        if (
            record is None
            or record.owner_type is not AttachmentOwnerType.CONVERSATION
            or record.owner_id != conversation_id
        ):
            return None
        if not self._extractor.supports(record):
            return self._extractor.extract(record, b"")
        if record.size_bytes > self._maximum:
            return self._too_large(record)
        try:
            ref = self._attachments.open_attachment_content(attachment_id)
            if ref is None:
                return None
            # Bound actual reads too: metadata alone is not a resource limit.
            with ref.stream:
                content = bytearray()
                while len(content) <= self._maximum:
                    chunk = ref.stream.read(min(64 * 1024, self._maximum + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
                if len(content) > self._maximum:
                    return self._too_large(record)
            return self._extractor.extract(record, bytes(content))
        except AttachmentStateError:
            return _result(
                record,
                AttachmentExtractionStatus.FAILED,
                error_code="attachment_content_unavailable",
                error_message="Attachment content is not available for extraction.",
            )
        except Exception:
            # Content-store adapters have no shared read-error type. Normalize
            # failures without returning storage paths or exception text.
            return _result(
                record,
                AttachmentExtractionStatus.FAILED,
                error_code="attachment_content_read_failed",
                error_message="Could not read stored attachment content.",
            )

    def _too_large(self, record: AttachmentRecord) -> AttachmentExtractionResult:
        return _result(
            record,
            AttachmentExtractionStatus.FAILED,
            error_code="attachment_too_large",
            error_message="Attachment exceeds the configured attachment size limit.",
        )
