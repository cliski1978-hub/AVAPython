"""InMemoryAttachmentRepository tests (Step 4.14.A).

Prove the in-memory attachment *metadata* store:

* create/get round-trips the exact immutable metadata;
* duplicate ``attachment_id`` and duplicate ``storage_key`` are ``ValueError``
  and leave the store untouched;
* duplicate display filenames are allowed;
* owner listing filters by owner type + owner id exactly, never leaking
  unassociated attachments or other owners, and is insertion-ordered;
* the owner pair (both-set or both-``None``) and non-negative ``size_bytes``
  are enforced on ``create``; zero-byte files are allowed;
* ``update_state`` advances exactly the lifecycle-controlled pair (authoritative
  ``size_bytes`` + ``status``) by id, preserving every immutable field and the
  listing position, and leaving an unknown id untouched;
* unknown ``get`` resolves ``None`` and returned collections are
  caller-isolated;
* ``clear`` forgets everything, letting ids and storage keys be reused.

Focused in-memory metadata only: no content store, no database, no service,
no routes (Step 4.14.B+).
"""

from datetime import UTC, datetime

import pytest

from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.repositories import AttachmentRecord, AttachmentRepository
from ava.services.attachment_store import InMemoryAttachmentRepository

# ============================================================
# BEGIN: Fixtures
# ============================================================

STAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def make_store() -> InMemoryAttachmentRepository:
    """Create a fresh in-memory attachment metadata store."""
    return InMemoryAttachmentRepository()


def make_record(
    attachment_id: str = "attachment-1",
    file_name: str = "report.pdf",
    media_type: str = "application/pdf",
    size_bytes: int = 1024,
    storage_key: str | None = None,
    owner_type: AttachmentOwnerType | None = AttachmentOwnerType.DOCUMENT,
    owner_id: str | None = "doc-1",
    status: AttachmentStatus = AttachmentStatus.AVAILABLE,
) -> AttachmentRecord:
    """Build an attachment record through the public port type."""
    return AttachmentRecord(
        attachment_id=attachment_id,
        file_name=file_name,
        media_type=media_type,
        size_bytes=size_bytes,
        storage_key=storage_key or f"attachments/{attachment_id}/source",
        owner_type=owner_type,
        owner_id=owner_id,
        status=status,
        created_at=STAMP,
    )


# ============================================================
# END: Fixtures
# ============================================================


# ============================================================
# BEGIN: Port conformance
# ============================================================


def test_store_conforms_to_the_attachment_repository_port() -> None:
    """The store satisfies the whole AttachmentRepository contract."""
    assert isinstance(make_store(), AttachmentRepository)


# ============================================================
# END: Port conformance
# ============================================================


# ============================================================
# BEGIN: Create / get
# ============================================================


def test_create_get_returns_exact_metadata() -> None:
    store = make_store()
    record = store.create(make_record())

    fetched = store.get("attachment-1")
    assert fetched is record
    assert fetched.attachment_id == "attachment-1"  # type: ignore[union-attr]
    assert fetched.file_name == "report.pdf"  # type: ignore[union-attr]
    assert fetched.media_type == "application/pdf"  # type: ignore[union-attr]
    assert fetched.size_bytes == 1024  # type: ignore[union-attr]
    assert fetched.storage_key == "attachments/attachment-1/source"  # type: ignore[union-attr]
    assert fetched.owner_type == AttachmentOwnerType.DOCUMENT  # type: ignore[union-attr]
    assert fetched.owner_id == "doc-1"  # type: ignore[union-attr]
    assert fetched.status == AttachmentStatus.AVAILABLE  # type: ignore[union-attr]
    assert fetched.created_at == STAMP  # type: ignore[union-attr]


def test_create_retains_every_status_exactly() -> None:
    store = make_store()
    for status in AttachmentStatus:
        store.create(make_record(attachment_id=f"attachment-{status.value}", status=status))
        assert store.get(f"attachment-{status.value}").status == status  # type: ignore[union-attr]


# ============================================================
# END: Create / get
# ============================================================


# ============================================================
# BEGIN: Duplicate identity / storage key
# ============================================================


def test_duplicate_attachment_id_is_rejected() -> None:
    store = make_store()
    store.create(make_record())
    with pytest.raises(ValueError, match="already exists"):
        store.create(make_record(attachment_id="attachment-1"))


def test_duplicate_storage_key_is_rejected() -> None:
    store = make_store()
    store.create(make_record())
    with pytest.raises(ValueError, match="storage key already in use"):
        store.create(make_record(attachment_id="attachment-2", storage_key="attachments/attachment-1/source"))


def test_failed_create_leaves_store_untouched() -> None:
    store = make_store()
    store.create(make_record())
    with pytest.raises(ValueError):
        store.create(make_record(attachment_id="attachment-2", storage_key="attachments/attachment-1/source"))
    assert store.get("attachment-2") is None
    assert [r.attachment_id for r in store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")] == [
        "attachment-1",
    ]


# ============================================================
# END: Duplicate identity / storage key
# ============================================================


# ============================================================
# BEGIN: Duplicate filenames
# ============================================================


def test_duplicate_filenames_are_allowed_across_attachments() -> None:
    store = make_store()
    first = store.create(make_record(attachment_id="attachment-1", file_name="report.pdf"))
    second = store.create(make_record(attachment_id="attachment-2", file_name="report.pdf"))

    assert first.file_name == "report.pdf"
    assert second.file_name == "report.pdf"
    assert len(store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")) == 2


# ============================================================
# END: Duplicate filenames
# ============================================================


# ============================================================
# BEGIN: Owner pair invariant
# ============================================================


def test_owner_type_without_owner_id_is_rejected() -> None:
    store = make_store()
    with pytest.raises(ValueError, match="both set or both None"):
        store.create(make_record(owner_type=AttachmentOwnerType.DOCUMENT, owner_id=None))


def test_owner_id_without_owner_type_is_rejected() -> None:
    store = make_store()
    with pytest.raises(ValueError, match="both set or both None"):
        store.create(make_record(owner_type=None, owner_id="doc-1"))


def test_unassociated_owner_pair_is_allowed() -> None:
    store = make_store()
    record = store.create(make_record(attachment_id="attachment-1", owner_type=None, owner_id=None))
    assert record.owner_type is None
    assert record.owner_id is None


# ============================================================
# END: Owner pair invariant
# ============================================================


# ============================================================
# BEGIN: Size semantics
# ============================================================


def test_negative_size_is_rejected() -> None:
    store = make_store()
    with pytest.raises(ValueError, match="non-negative"):
        store.create(make_record(size_bytes=-1))


def test_zero_size_is_allowed() -> None:
    store = make_store()
    record = store.create(make_record(size_bytes=0))
    assert record.size_bytes == 0


# ============================================================
# END: Size semantics
# ============================================================


# ============================================================
# BEGIN: Owner listing
# ============================================================


def test_owner_listing_filters_exactly_by_owner_and_is_isolated() -> None:
    store = make_store()
    store.create(make_record(attachment_id="doc-a1", owner_type=AttachmentOwnerType.DOCUMENT, owner_id="doc-1"))
    store.create(make_record(attachment_id="doc-b1", owner_type=AttachmentOwnerType.DOCUMENT, owner_id="doc-2"))
    store.create(make_record(attachment_id="conv-c1", owner_type=AttachmentOwnerType.CONVERSATION, owner_id="conv-1"))
    store.create(make_record(attachment_id="msg-m1", owner_type=AttachmentOwnerType.MESSAGE, owner_id="msg-1"))
    store.create(make_record(attachment_id="loose-1", owner_type=None, owner_id=None))

    assert [r.attachment_id for r in store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")] == [
        "doc-a1",
    ]
    assert [r.attachment_id for r in store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-2")] == [
        "doc-b1",
    ]
    assert [r.attachment_id for r in store.list_for_owner(AttachmentOwnerType.CONVERSATION, "conv-1")] == [
        "conv-c1",
    ]
    assert [r.attachment_id for r in store.list_for_owner(AttachmentOwnerType.MESSAGE, "msg-1")] == ["msg-m1"]

    listed = list(store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1"))
    listed.extend(store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-2"))
    listed.extend(store.list_for_owner(AttachmentOwnerType.CONVERSATION, "conv-1"))
    listed.extend(store.list_for_owner(AttachmentOwnerType.MESSAGE, "msg-1"))
    assert "loose-1" not in [r.attachment_id for r in listed]


def test_owner_listing_is_insertion_ordered() -> None:
    store = make_store()
    store.create(make_record(attachment_id="attachment-3", owner_type=AttachmentOwnerType.DOCUMENT, owner_id="doc-1"))
    store.create(make_record(attachment_id="attachment-1", owner_type=AttachmentOwnerType.DOCUMENT, owner_id="doc-1"))
    store.create(make_record(attachment_id="attachment-2", owner_type=AttachmentOwnerType.DOCUMENT, owner_id="doc-1"))

    assert [r.attachment_id for r in store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")] == [
        "attachment-3",
        "attachment-1",
        "attachment-2",
    ]


def test_returned_owner_list_is_caller_isolated() -> None:
    store = make_store()
    store.create(make_record(attachment_id="attachment-1", owner_type=AttachmentOwnerType.DOCUMENT, owner_id="doc-1"))

    listing = store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")
    listing.clear()

    assert store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1") != []


# ============================================================
# END: Owner listing
# ============================================================


# ============================================================
# BEGIN: Lifecycle state updates
# ============================================================


def test_update_state_advances_size_and_status_and_preserves_immutables() -> None:
    store = make_store()
    store.create(make_record(attachment_id="attachment-1", size_bytes=0, status=AttachmentStatus.PENDING))

    updated = store.update_state(
        "attachment-1", size_bytes=4096, status=AttachmentStatus.AVAILABLE
    )

    assert updated is not None
    assert updated.size_bytes == 4096
    assert updated.status == AttachmentStatus.AVAILABLE
    assert updated.attachment_id == "attachment-1"
    assert updated.file_name == "report.pdf"
    assert updated.media_type == "application/pdf"
    assert updated.storage_key == "attachments/attachment-1/source"
    assert updated.owner_type == AttachmentOwnerType.DOCUMENT
    assert updated.owner_id == "doc-1"
    assert updated.created_at == STAMP

    fetched = store.get("attachment-1")
    assert fetched.size_bytes == 4096
    assert fetched.status == AttachmentStatus.AVAILABLE


def test_update_state_can_record_failed_status() -> None:
    store = make_store()
    store.create(make_record(attachment_id="attachment-1", status=AttachmentStatus.PENDING))

    updated = store.update_state("attachment-1", size_bytes=0, status=AttachmentStatus.FAILED)

    assert updated.status == AttachmentStatus.FAILED
    assert store.get("attachment-1").status == AttachmentStatus.FAILED


def test_update_state_unknown_attachment_returns_none_and_changes_nothing() -> None:
    store = make_store()
    store.create(make_record())

    assert store.update_state("ghost", size_bytes=1, status=AttachmentStatus.FAILED) is None

    assert store.get("attachment-1").status == AttachmentStatus.AVAILABLE
    assert store.get("attachment-1").size_bytes == 1024


def test_update_state_rejects_negative_size_and_leaves_store_untouched() -> None:
    store = make_store()
    store.create(make_record(attachment_id="attachment-1", status=AttachmentStatus.PENDING))

    with pytest.raises(ValueError, match="non-negative"):
        store.update_state("attachment-1", size_bytes=-1, status=AttachmentStatus.FAILED)

    assert store.get("attachment-1").status == AttachmentStatus.PENDING
    assert store.get("attachment-1").size_bytes == 1024


def test_update_state_does_not_move_the_listing_position() -> None:
    store = make_store()
    store.create(make_record(attachment_id="attachment-1"))
    store.create(make_record(attachment_id="attachment-2", storage_key="attachments/attachment-2/source"))

    store.update_state("attachment-1", size_bytes=7, status=AttachmentStatus.FAILED)

    assert [r.attachment_id for r in store.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")] == [
        "attachment-1",
        "attachment-2",
    ]


# ============================================================
# END: Lifecycle state updates
# ============================================================


# ============================================================
# BEGIN: Lookup semantics
# ============================================================


def test_unknown_attachment_get_returns_none() -> None:
    store = make_store()
    assert store.get("ghost") is None
    assert store.get("attachment-1") is None


# ============================================================
# END: Lookup semantics
# ============================================================


# ============================================================
# BEGIN: Clear helper
# ============================================================


def test_clear_forgets_everything_and_allows_reuse() -> None:
    store = make_store()
    store.create(make_record(attachment_id="attachment-1", storage_key="attachments/attachment-1/source"))
    store.clear()

    assert store.get("attachment-1") is None
    reused = store.create(make_record(attachment_id="attachment-1", storage_key="attachments/attachment-1/source"))
    assert reused.attachment_id == "attachment-1"


# ============================================================
# END: Clear helper
# ============================================================