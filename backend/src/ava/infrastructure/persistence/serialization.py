"""Serialization helpers shared by the relational persistence adapters.

Storage mapping (engine-independent, no vendor objects):

* Enums are stored as their stable string values (``RunStatus.value``,
  ``EventType.value``, ``MessageRole.value``, ...) and restored with
  ``Enum(value)`` — never engine-native or implementation names.
* Timestamps are stored as ISO-8601 aware-UTC strings with an explicit offset
  (``...+00:00``) and restored as aware UTC datetimes.
* Structured fields (``RunEvent.payload``, ``RunRecord.execution_selection``)
  are stored as deterministic JSON text (``json.dumps(sort_keys=True,
  separators=(",", ":"))``). No pickling.

The row mappers below convert ``sqlite3.Row`` snapshots back into AVA-owned
contract/record types and are the only place driver row objects cross into
AVA types.
"""

import json
import sqlite3
from datetime import UTC, datetime
from typing import cast

from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.documents import ContentFormat
from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.json_types import JsonValue
from ava.contracts.responses import RunStatus
from ava.repositories.attachment_repository import AttachmentRecord
from ava.repositories.conversation_repository import ConversationRecord
from ava.repositories.document_repository import DocumentRecord
from ava.repositories.document_revision_repository import DocumentRevisionRecord
from ava.repositories.message_repository import MessageRecord
from ava.repositories.run_repository import RunRecord

# ============================================================
# BEGIN: Timestamp serialization
# ============================================================


def to_utc_iso(value: datetime) -> str:
    """Serialize a timezone-aware datetime as ISO-8601 with an explicit UTC offset."""
    return value.astimezone(UTC).isoformat()


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp back into an aware-UTC datetime.

    Naive values (no timezone suffix) are treated as UTC so manual or legacy
    rows never surface naive datetimes inside the application.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


# ============================================================
# END: Timestamp serialization
# ============================================================


# ============================================================
# BEGIN: JSON serialization
# ============================================================


def dump_json(payload: dict[str, JsonValue]) -> str:
    """Serialize a JSON-safe payload deterministically."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def load_json(raw: str) -> dict[str, JsonValue]:
    """Parse stored JSON text back into a JSON-safe map."""
    return cast(dict[str, JsonValue], json.loads(raw))


def dump_execution_selection(selection: RunExecutionSelection | None) -> str | None:
    """Serialize a run's execution selection to deterministic JSON text, or ``None``."""
    if selection is None:
        return None
    return json.dumps(selection.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def load_execution_selection(raw: str | None) -> RunExecutionSelection | None:
    """Restore a run's execution selection from stored JSON text, or ``None``."""
    if raw is None:
        return None
    return RunExecutionSelection.model_validate_json(raw)


# ============================================================
# END: JSON serialization
# ============================================================


# ============================================================
# BEGIN: Row mappers
# ============================================================


def row_to_run_record(row: sqlite3.Row) -> RunRecord:
    """Map a ``runs`` row back to an AVA run record."""
    return RunRecord(
        run_id=row["run_id"],
        status=RunStatus(row["status"]),
        created_at=parse_utc(row["created_at"]),
        updated_at=parse_utc(row["updated_at"]),
        execution_selection=load_execution_selection(row["execution_selection"]),
        conversation_id=row["conversation_id"],
        source_user_message_id=row["source_user_message_id"],
        assistant_message_id=row["assistant_message_id"],
        cancellation_requested_at=(
            parse_utc(row["cancellation_requested_at"])
            if row["cancellation_requested_at"] is not None
            else None
        ),
    )


def row_to_run_event(row: sqlite3.Row) -> RunEvent:
    """Map a ``run_events`` row back to an AVA run event."""
    return RunEvent(
        event_id=row["event_id"],
        run_id=row["run_id"],
        sequence=int(row["seq"]),
        event_type=EventType(row["event_type"]),
        timestamp=parse_utc(row["timestamp"]),
        payload=load_json(row["payload"]),
        contract_version=row["contract_version"],
    )


def row_to_conversation_record(row: sqlite3.Row) -> ConversationRecord:
    """Map a ``conversations`` row back to an AVA conversation record."""
    return ConversationRecord(
        conversation_id=row["conversation_id"],
        title=row["title"],
        created_at=parse_utc(row["created_at"]),
        updated_at=parse_utc(row["updated_at"]),
    )


def row_to_message_record(row: sqlite3.Row) -> MessageRecord:
    """Map a ``messages`` row back to an AVA message record."""
    return MessageRecord(
        message_id=row["message_id"],
        conversation_id=row["conversation_id"],
        role=MessageRole(row["role"]),
        content=row["content"],
        status=MessageStatus(row["status"]),
        created_at=parse_utc(row["created_at"]),
        updated_at=parse_utc(row["updated_at"]),
        source_run_id=row["source_run_id"],
    )


def row_to_document_record(row: sqlite3.Row) -> DocumentRecord:
    """Map a ``documents`` row back to an AVA document record."""
    return DocumentRecord(
        document_id=row["document_id"],
        title=row["title"],
        content=row["content"],
        content_format=ContentFormat(row["content_format"]),
        created_at=parse_utc(row["created_at"]),
        updated_at=parse_utc(row["updated_at"]),
    )


def row_to_document_revision_record(row: sqlite3.Row) -> DocumentRevisionRecord:
    """Map a ``document_revisions`` row back to an AVA revision record."""
    return DocumentRevisionRecord(
        revision_id=row["revision_id"],
        document_id=row["document_id"],
        revision_number=row["revision_number"],
        title=row["title"],
        content=row["content"],
        content_format=ContentFormat(row["content_format"]),
        created_at=parse_utc(row["created_at"]),
    )


def row_to_attachment_record(row: sqlite3.Row) -> AttachmentRecord:
    """Map an ``attachments`` row back to an AVA attachment record."""
    raw_owner_type = row["owner_type"]
    return AttachmentRecord(
        attachment_id=row["attachment_id"],
        file_name=row["file_name"],
        media_type=row["media_type"],
        size_bytes=row["size_bytes"],
        storage_key=row["storage_key"],
        owner_type=AttachmentOwnerType(raw_owner_type) if raw_owner_type is not None else None,
        owner_id=row["owner_id"],
        status=AttachmentStatus(row["status"]),
        created_at=parse_utc(row["created_at"]),
    )


# ============================================================
# END: Row mappers
# ============================================================
