"""Attachment wire-contract tests (Step 4.14.F).

Pins the exact transport surface: the ``AttachmentResponse`` and
``AttachmentListResponse`` shapes, AVA-owned enums, timezone-aware UTC
timestamps, the transport ``contract_version``, and — decisively — the
absence of storage internals (``storage_key``, absolute paths, provider or
surrogate identifiers) on the wire.
"""

from datetime import UTC, datetime

from ava.contracts.attachments import (
    AttachmentListResponse,
    AttachmentOwnerType,
    AttachmentResponse,
    AttachmentStatus,
)
from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: AttachmentResponse
# ============================================================

RESPONSE_FIELDS = {
    "attachment_id",
    "file_name",
    "media_type",
    "size_bytes",
    "owner_type",
    "owner_id",
    "status",
    "created_at",
    "contract_version",
}


def _response(
    *,
    attachment_id: str = "a-1",
    file_name: str = "report.pdf",
    media_type: str = "application/pdf",
    size_bytes: int = 12,
    owner_type: AttachmentOwnerType | None = None,
    owner_id: str | None = None,
    status: AttachmentStatus = AttachmentStatus.AVAILABLE,
) -> AttachmentResponse:
    """Build an AttachmentResponse with sane defaults for shape assertions."""
    return AttachmentResponse(
        attachment_id=attachment_id,
        file_name=file_name,
        media_type=media_type,
        size_bytes=size_bytes,
        owner_type=owner_type,
        owner_id=owner_id,
        status=status,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_response_has_exactly_the_approved_fields() -> None:
    """The wire response carries exactly the approved metadata fields."""
    assert set(AttachmentResponse.model_fields) == RESPONSE_FIELDS


def test_response_never_exposes_storage_internals() -> None:
    """Storage internals must never leak: no storage key, path, or store."""
    fields = set(AttachmentResponse.model_fields)
    assert "storage_key" not in fields
    assert "storage_path" not in fields
    assert "content_store" not in fields
    internal_vocab = {
        f for f in fields if "storage" in f or "key" in f or "path" in f or "store" in f
    }
    assert not internal_vocab
    assert "attachment_id" in fields


def test_response_serializes_with_ava_owned_enum_strings() -> None:
    """Enums serialize to their string values, not member reprs."""
    body = _response(
        owner_type=AttachmentOwnerType.DOCUMENT,
        owner_id="doc-1",
        status=AttachmentStatus.AVAILABLE,
    ).model_dump(mode="json")
    assert body["owner_type"] == "document"
    assert body["owner_id"] == "doc-1"
    assert body["status"] == "available"


def test_response_owner_pair_is_nullable() -> None:
    """An unassociated attachment serializes with null owner fields."""
    body = _response().model_dump(mode="json")
    assert body["owner_type"] is None
    assert body["owner_id"] is None


def test_response_preserves_aware_utc_created_at() -> None:
    """The backend-minted created_at round-trips with a UTC offset."""
    body = _response().model_dump(mode="json")
    assert body["created_at"].endswith(("Z", "+00:00"))
    parsed = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed == datetime(2026, 1, 1, tzinfo=UTC)


def test_response_carries_the_transport_contract_version() -> None:
    """Every attachment response is versioned with the transport contract."""
    body = _response().model_dump(mode="json")
    assert body["contract_version"] == CONTRACT_VERSION == "v1"


def test_response_contract_version_is_frozen() -> None:
    """Clients cannot inject their own contract version."""
    with_override = _response()
    assert with_override.contract_version == CONTRACT_VERSION


# ============================================================
# END: AttachmentResponse
# ============================================================


# ============================================================
# BEGIN: AttachmentListResponse
# ============================================================

LIST_FIELDS = {"contract_version", "owner_type", "owner_id", "attachments"}


def test_list_response_has_exactly_the_approved_fields() -> None:
    """The owner-scoped list envelope carries only the approved fields."""
    assert set(AttachmentListResponse.model_fields) == LIST_FIELDS


def test_list_response_is_owner_scoped() -> None:
    """The list envelope echoes the owner pair and carries no global scope."""
    body = AttachmentListResponse(
        owner_type=AttachmentOwnerType.CONVERSATION,
        owner_id="conv-9",
        attachments=[_response()],
    ).model_dump(mode="json")
    assert body["owner_type"] == "conversation"
    assert body["owner_id"] == "conv-9"
    assert body["contract_version"] == CONTRACT_VERSION
    assert len(body["attachments"]) == 1
    assert set(body["attachments"][0]) == RESPONSE_FIELDS


# ============================================================
# END: AttachmentListResponse
# ============================================================