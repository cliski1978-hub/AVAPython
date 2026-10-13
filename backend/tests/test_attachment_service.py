"""AttachmentService tests (Step 4.14.E).

Prove the attachment orchestration slice:

* ``create_attachment`` mints an ``attachment_id`` (``uuid4``) + opaque
  ``attachments/{id}/content`` storage key + aware-UTC ``created_at``, then
  runs pending → put → verify → available with the content store's
  authoritative ``size_bytes`` and the owner pair validated at the boundary;
* the display filename never participates in the physical storage key;
* every attachment gets a unique id/key; zero-byte and binary payloads
  round-trip through ``open_attachment_content``;
* failure invariants: metadata-create failure writes no content; content-write
  or verification failure marks the record failed and raises; a final metadata
  transition failure attempts a failed mark and reports truthfully;
* content is only readable for ``available`` attachments (pending/failed raise
  ``AttachmentStateError``; unknown resolves ``None`` without touching the
  store); ``get``/``list`` never touch the content store;
* memory/local content parity and memory/relational metadata parity hold over
  the same service.
"""

import uuid
from datetime import UTC, datetime
from io import BytesIO

import pytest

from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.infrastructure.attachment_content_store import LocalAttachmentContentStore
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories import RelationalAttachmentRepository
from ava.repositories import AttachmentRecord
from ava.repositories.attachment_content_store import AttachmentContentStore
from ava.services.attachment_content_store import InMemoryAttachmentContentStore
from ava.services.attachment_service import (
    AttachmentService,
    AttachmentStateError,
    AttachmentStorageError,
)
from ava.services.attachment_store import InMemoryAttachmentRepository

PAYLOAD = bytes(range(256)) * 2048


def make_record(
    attachment_id: str = "attachment-1",
    file_name: str = "report.pdf",
    media_type: str = "application/pdf",
    size_bytes: int = 0,
    storage_key: str | None = None,
    owner_type: AttachmentOwnerType | None = AttachmentOwnerType.DOCUMENT,
    owner_id: str | None = "doc-1",
    status: AttachmentStatus = AttachmentStatus.PENDING,
) -> AttachmentRecord:
    return AttachmentRecord(
        attachment_id=attachment_id,
        file_name=file_name,
        media_type=media_type,
        size_bytes=size_bytes,
        storage_key=storage_key or f"attachments/{attachment_id}/content",
        owner_type=owner_type,
        owner_id=owner_id,
        status=status,
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


# ============================================================
# BEGIN: Test doubles
# ============================================================


class _InMemoryRepository(InMemoryAttachmentRepository):
    """In-memory repository with a records introspection helper for tests."""

    def records(self) -> list[AttachmentRecord]:
        return list(self._attachments.values())


class _RecordingContentStore(InMemoryAttachmentContentStore):
    """Content store that records put/open keys for call assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.put_calls: list[str] = []
        self.open_calls: list[str] = []

    def put(self, storage_key: str, source) -> object:
        self.put_calls.append(storage_key)
        return super().put(storage_key, source)

    def open(self, storage_key: str):
        self.open_calls.append(storage_key)
        return super().open(storage_key)


class _ExplodingContentStore(AttachmentContentStore):
    """Content store that fails if any content operation is attempted."""

    def put(self, storage_key: str, source):
        raise AssertionError("content store must not be touched during reads")

    def open(self, storage_key: str):
        raise AssertionError("content store must not be touched during reads")

    def exists(self, storage_key: str) -> bool:
        raise AssertionError("content store must not be touched during reads")


class _FailingCreateRepository(_InMemoryRepository):
    def create(self, record: AttachmentRecord) -> AttachmentRecord:
        raise ValueError("simulated metadata failure")


class _FailingPutContentStore(InMemoryAttachmentContentStore):
    def put(self, storage_key: str, source):
        raise OSError("disk full")


class _BrokenExistsContentStore(InMemoryAttachmentContentStore):
    """Store whose put succeeds but whose exists always lies to the caller."""

    def exists(self, storage_key: str) -> bool:
        return False


class _FailingFinalizeRepository(_InMemoryRepository):
    def update_state(self, attachment_id, *, size_bytes, status):
        raise ValueError("finalize unavailable")


class _FailingAvailableTransitionRepository(_InMemoryRepository):
    def update_state(self, attachment_id, *, size_bytes, status):
        if status is AttachmentStatus.AVAILABLE:
            raise RuntimeError("transition rejected")
        return super().update_state(attachment_id, size_bytes=size_bytes, status=status)


def _relational() -> RelationalAttachmentRepository:
    return RelationalAttachmentRepository(database=SqliteDatabase(":memory:"))


# ============================================================
# END: Test doubles
# ============================================================


# ============================================================
# BEGIN: Happy-path lifecycle
# ============================================================


def test_create_attachment_returns_an_available_record_with_server_owned_identity() -> None:
    repository = _InMemoryRepository()
    service = AttachmentService(
        attachment_repository=repository,
        attachment_content_store=InMemoryAttachmentContentStore(),
    )

    created = service.create_attachment(
        file_name="report.pdf",
        media_type="application/pdf",
        source=BytesIO(PAYLOAD),
        owner_type=AttachmentOwnerType.DOCUMENT,
        owner_id="doc-1",
    )

    assert uuid.UUID(created.attachment_id)
    assert created.storage_key == f"attachments/{created.attachment_id}/content"
    assert created.status is AttachmentStatus.AVAILABLE
    assert created.size_bytes == len(PAYLOAD)
    assert created.file_name == "report.pdf"
    assert created.media_type == "application/pdf"
    assert created.owner_type is AttachmentOwnerType.DOCUMENT
    assert created.owner_id == "doc-1"
    assert created.created_at.tzinfo is not None
    assert created.created_at.utcoffset() == UTC.utcoffset(None)

    stored = repository.get(created.attachment_id)
    assert stored is created
    assert [r.attachment_id for r in service.list_attachments(AttachmentOwnerType.DOCUMENT, "doc-1")] == [
        created.attachment_id
    ]


def test_create_attachment_verifies_content_exists_before_available(tmp_path) -> None:
    root = tmp_path / "storage"
    repository = _InMemoryRepository()
    service = AttachmentService(
        attachment_repository=repository,
        attachment_content_store=LocalAttachmentContentStore(root),
    )

    created = service.create_attachment(
        file_name="notes.txt",
        media_type="text/plain",
        source=BytesIO(b"hello"),
    )

    assert created.status is AttachmentStatus.AVAILABLE
    assert created.size_bytes == 5
    assert (root / "attachments" / created.attachment_id / "content").is_file()
    assert (root / "attachments" / created.attachment_id / "content").read_bytes() == b"hello"


def test_zero_byte_attachment_round_trips() -> None:
    service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=InMemoryAttachmentContentStore(),
    )

    created = service.create_attachment(
        file_name="empty.bin",
        media_type="application/octet-stream",
        source=BytesIO(b""),
    )

    assert created.status is AttachmentStatus.AVAILABLE
    assert created.size_bytes == 0
    ref = service.open_attachment_content(created.attachment_id)
    assert ref is not None
    assert ref.stream.read() == b""


def test_binary_payload_round_trips_through_open() -> None:
    service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=InMemoryAttachmentContentStore(),
    )

    created = service.create_attachment(
        file_name="blob.bin",
        media_type="application/octet-stream",
        source=BytesIO(PAYLOAD),
    )

    ref = service.open_attachment_content(created.attachment_id)
    assert ref is not None
    assert ref.record is created
    assert ref.stream.read() == PAYLOAD


def test_source_stream_is_left_open_and_read_from_current_position() -> None:
    service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=InMemoryAttachmentContentStore(),
    )
    source = BytesIO(b"tail")

    created = service.create_attachment(
        file_name="slice.bin",
        media_type="application/octet-stream",
        source=source,
    )

    assert created.size_bytes == 4
    assert not source.closed


# ============================================================
# END: Happy-path lifecycle
# ============================================================


# ============================================================
# BEGIN: Identity and owner-pair semantics
# ============================================================


def test_each_create_mints_a_distinct_id_and_storage_key() -> None:
    service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=InMemoryAttachmentContentStore(),
    )
    first = service.create_attachment(
        file_name="a.pdf",
        media_type="application/pdf",
        source=BytesIO(b"a"),
        owner_type=AttachmentOwnerType.DOCUMENT,
        owner_id="doc-1",
    )
    second = service.create_attachment(
        file_name="b.pdf",
        media_type="application/pdf",
        source=BytesIO(b"b"),
        owner_type=AttachmentOwnerType.DOCUMENT,
        owner_id="doc-1",
    )

    assert first.attachment_id != second.attachment_id
    assert first.storage_key != second.storage_key
    assert uuid.UUID(first.attachment_id) != uuid.UUID(second.attachment_id)
    assert len(service.list_attachments(AttachmentOwnerType.DOCUMENT, "doc-1")) == 2


def test_filename_never_participates_in_the_storage_key(tmp_path) -> None:
    """Hostile/duplicate display names cannot influence physical placement."""
    root = tmp_path / "storage"
    service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=LocalAttachmentContentStore(root),
    )
    tricky_names = ["../../etc/passwd", "../attachments/evil", "report.pdf", "", "a/b/c"]

    keys: list[str] = []
    attachment_ids: list[str] = []
    for index, file_name in enumerate(tricky_names):
        created = service.create_attachment(
            file_name=file_name,
            media_type="application/octet-stream",
            source=BytesIO(bytes([index])),
        )
        attachment_ids.append(created.attachment_id)
        keys.append(created.storage_key)

    assert len(set(keys)) == len(tricky_names)
    assert len(set(attachment_ids)) == len(tricky_names)
    for attachment_id, storage_key in zip(attachment_ids, keys, strict=True):
        assert storage_key == f"attachments/{attachment_id}/content"
        physical = root / "attachments" / attachment_id / "content"
        assert physical.is_file()
        assert ".." not in physical.parts
        assert physical == root / "attachments" / attachment_id / "content"


def test_owner_type_without_owner_id_is_rejected_before_any_write() -> None:
    recording = _RecordingContentStore()
    service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=recording,
    )

    with pytest.raises(ValueError, match="both set or both None"):
        service.create_attachment(
            file_name="a.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"x"),
            owner_type=AttachmentOwnerType.DOCUMENT,
            owner_id=None,
        )

    assert recording.put_calls == []


def test_owner_id_without_owner_type_is_rejected_and_unassociated_is_allowed() -> None:
    service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=InMemoryAttachmentContentStore(),
    )

    with pytest.raises(ValueError, match="both set or both None"):
        service.create_attachment(
            file_name="a.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"x"),
            owner_type=None,
            owner_id="doc-1",
        )

    created = service.create_attachment(
        file_name="loose.bin",
        media_type="application/octet-stream",
        source=BytesIO(b"y"),
    )
    assert created.owner_type is None
    assert created.owner_id is None
    assert service.list_attachments(AttachmentOwnerType.DOCUMENT, "doc-1") == []


# ============================================================
# END: Identity and owner-pair semantics
# ============================================================


# ============================================================
# BEGIN: Failure invariants
# ============================================================


def test_metadata_create_failure_writes_no_content() -> None:
    recording = _RecordingContentStore()
    service = AttachmentService(
        attachment_repository=_FailingCreateRepository(),
        attachment_content_store=recording,
    )

    with pytest.raises(AttachmentStorageError, match="Failed to record attachment metadata"):
        service.create_attachment(
            file_name="a.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"payload"),
        )

    assert recording.put_calls == []
    assert recording.open_calls == []


def test_content_write_failure_marks_the_record_failed_and_raises() -> None:
    repository = _InMemoryRepository()
    service = AttachmentService(
        attachment_repository=repository,
        attachment_content_store=_FailingPutContentStore(),
    )

    with pytest.raises(AttachmentStorageError, match="Failed to store attachment content"):
        service.create_attachment(
            file_name="a.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"payload"),
        )

    (record,) = repository.records()
    assert record.status is AttachmentStatus.FAILED
    assert record.size_bytes == 0
    assert record.attachment_id
    assert repository.get(record.attachment_id).status is AttachmentStatus.FAILED


def test_verification_inconsistency_marks_the_record_failed_and_raises() -> None:
    repository = _InMemoryRepository()
    service = AttachmentService(
        attachment_repository=repository,
        attachment_content_store=_BrokenExistsContentStore(),
    )

    with pytest.raises(AttachmentStorageError, match="content is not present after put"):
        service.create_attachment(
            file_name="a.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"payload"),
        )

    (record,) = repository.records()
    assert record.status is AttachmentStatus.FAILED
    assert repository.get(record.attachment_id).status is AttachmentStatus.FAILED


def test_conversation_upload_failure_removes_partial_metadata_and_content() -> None:
    repository = _InMemoryRepository()
    content = _BrokenExistsContentStore()
    service = AttachmentService(attachment_repository=repository, attachment_content_store=content)

    with pytest.raises(AttachmentStorageError, match="content is not present after put"):
        service.create_attachment(
            file_name="notes.txt",
            media_type="text/plain",
            source=BytesIO(b"partial upload"),
            owner_type=AttachmentOwnerType.CONVERSATION,
            owner_id="conversation-1",
            retain_failed_record=False,
        )

    assert repository.records() == []
    assert content._contents == {}


def test_final_transition_failure_attempts_failed_mark_and_reports_truthfully() -> None:
    repository = _FailingFinalizeRepository()
    service = AttachmentService(
        attachment_repository=repository,
        attachment_content_store=InMemoryAttachmentContentStore(),
    )

    with pytest.raises(AttachmentStorageError, match="failed state could not be recorded"):
        service.create_attachment(
            file_name="a.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"payload"),
        )

    (record,) = repository.records()
    assert record.status is AttachmentStatus.PENDING
    assert record.size_bytes == 0


def test_final_transition_failure_succeeds_in_recording_failed() -> None:
    repository = _FailingAvailableTransitionRepository()
    service = AttachmentService(
        attachment_repository=repository,
        attachment_content_store=InMemoryAttachmentContentStore(),
    )

    with pytest.raises(AttachmentStorageError, match="record was marked failed"):
        service.create_attachment(
            file_name="a.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"payload"),
        )

    (record,) = repository.records()
    assert record.status is AttachmentStatus.FAILED
    assert record.size_bytes == 0


# ============================================================
# END: Failure invariants
# ============================================================


# ============================================================
# BEGIN: Content-read gating
# ============================================================


def test_content_is_readable_only_for_available_attachments() -> None:
    repository = _InMemoryRepository()
    recording = _RecordingContentStore()
    service = AttachmentService(
        attachment_repository=repository,
        attachment_content_store=recording,
    )
    available = service.create_attachment(
        file_name="a.bin", media_type="application/octet-stream", source=BytesIO(b"bytes")
    )
    pending = repository.create(make_record(attachment_id="pending-1", status=AttachmentStatus.PENDING))
    failed = repository.create(make_record(attachment_id="failed-1", status=AttachmentStatus.FAILED))

    ref = service.open_attachment_content(available.attachment_id)
    assert ref is not None
    assert ref.stream.read() == b"bytes"
    assert recording.open_calls == [available.storage_key]

    with pytest.raises(AttachmentStateError, match=f"attachment {pending.attachment_id}: status is pending"):
        service.open_attachment_content(pending.attachment_id)
    with pytest.raises(AttachmentStateError, match=f"attachment {failed.attachment_id}: status is failed"):
        service.open_attachment_content(failed.attachment_id)


def test_unknown_attachment_resolves_none_without_touching_the_content_store() -> None:
    recording = _RecordingContentStore()
    service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=recording,
    )

    assert service.get_attachment("ghost") is None
    assert service.open_attachment_content("ghost") is None
    assert recording.put_calls == []
    assert recording.open_calls == []


def test_get_and_list_never_touch_content_operations() -> None:
    repository = _InMemoryRepository()
    repository.create(make_record(attachment_id="a-1", status=AttachmentStatus.AVAILABLE))
    repository.create(make_record(attachment_id="a-2", status=AttachmentStatus.PENDING))
    service = AttachmentService(
        attachment_repository=repository,
        attachment_content_store=_ExplodingContentStore(),
    )

    assert service.get_attachment("a-1").attachment_id == "a-1"
    assert service.get_attachment("a-2").status is AttachmentStatus.PENDING
    assert [r.attachment_id for r in service.list_attachments(AttachmentOwnerType.DOCUMENT, "doc-1")] == [
        "a-1",
        "a-2",
    ]


def test_available_record_missing_content_raises_storage_error() -> None:
    repository = _InMemoryRepository()
    repository.create(make_record(attachment_id="ghost-content", status=AttachmentStatus.AVAILABLE))
    service = AttachmentService(
        attachment_repository=repository,
        attachment_content_store=InMemoryAttachmentContentStore(),
    )

    with pytest.raises(AttachmentStorageError, match="missing for ghost-content"):
        service.open_attachment_content("ghost-content")


# ============================================================
# END: Content-read gating
# ============================================================


# ============================================================
# BEGIN: Parity over the same service
# ============================================================


def _assert_same_finalized_metadata(actual: AttachmentRecord, expected: AttachmentRecord) -> None:
    assert actual.status is AttachmentStatus.AVAILABLE
    assert actual.owner_type == expected.owner_type
    assert actual.owner_id == expected.owner_id
    storage_template = "attachments/{attachment_id}/content"
    assert actual.storage_key == storage_template.format(attachment_id=actual.attachment_id)
    assert expected.storage_key == storage_template.format(attachment_id=expected.attachment_id)


def test_memory_and_local_content_stores_agree_over_the_same_service(tmp_path) -> None:
    local_root = tmp_path / "storage"
    memory_service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=InMemoryAttachmentContentStore(),
    )
    local_service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=LocalAttachmentContentStore(local_root),
    )

    memory_record = memory_service.create_attachment(
        file_name="ml.bin", media_type="application/octet-stream", source=BytesIO(PAYLOAD)
    )
    local_record = local_service.create_attachment(
        file_name="ml.bin", media_type="application/octet-stream", source=BytesIO(PAYLOAD)
    )

    assert memory_record.size_bytes == len(PAYLOAD) == local_record.size_bytes
    _assert_same_finalized_metadata(memory_record, local_record)
    assert memory_record.created_at.utcoffset() == UTC.utcoffset(None)
    assert local_record.created_at.utcoffset() == UTC.utcoffset(None)

    memory_ref = memory_service.open_attachment_content(memory_record.attachment_id)
    local_ref = local_service.open_attachment_content(local_record.attachment_id)
    with memory_ref.stream as memory_stream:
        memory_bytes = memory_stream.read()
    with local_ref.stream as local_stream:
        local_bytes = local_stream.read()
    assert memory_bytes == PAYLOAD
    assert local_bytes == PAYLOAD


def test_memory_and_relational_metadata_agree_over_the_same_service() -> None:
    memory_service = AttachmentService(
        attachment_repository=_InMemoryRepository(),
        attachment_content_store=InMemoryAttachmentContentStore(),
    )
    memory_record = memory_service.create_attachment(
        file_name="meta.bin",
        media_type="application/octet-stream",
        source=BytesIO(b"m"),
        owner_type=AttachmentOwnerType.MESSAGE,
        owner_id="message-42",
    )

    relational_service = AttachmentService(
        attachment_repository=_relational(),
        attachment_content_store=InMemoryAttachmentContentStore(),
    )
    relational_record = relational_service.create_attachment(
        file_name="meta.bin",
        media_type="application/octet-stream",
        source=BytesIO(b"m"),
        owner_type=AttachmentOwnerType.MESSAGE,
        owner_id="message-42",
    )

    assert relational_record.size_bytes == memory_record.size_bytes == 1
    assert relational_record.status is AttachmentStatus.AVAILABLE
    assert relational_record.status == memory_record.status
    assert relational_record.file_name == memory_record.file_name
    assert relational_record.media_type == memory_record.media_type
    assert relational_record.owner_type == memory_record.owner_type
    assert relational_record.owner_id == memory_record.owner_id
    assert relational_record.created_at.utcoffset() == memory_record.created_at.utcoffset()
    assert relational_record.attachment_id != memory_record.attachment_id

    assert relational_service.get_attachment(relational_record.attachment_id).status is AttachmentStatus.AVAILABLE
    assert memory_service.get_attachment(memory_record.attachment_id).status is AttachmentStatus.AVAILABLE


# ============================================================
# END: Parity over the same service
# ============================================================
