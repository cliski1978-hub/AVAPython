"""RelationalAttachmentRepository tests (Step 4.14.C).

Prove durable SQLite persistence for Step 4.14.A attachment metadata with
behavioral parity to the in-memory store:

* create/get round-trip every approved field exactly (enums, aware-UTC
  timestamps, owner nullability, status, size, storage key);
* duplicate ``attachment_id`` / ``storage_key`` raise distinct ``ValueError``s;
* the owner-pair and non-negative-size invariants match the in-memory
  validation boundary;
* ``update_state`` advances exactly the lifecycle-controlled pair
  (``size_bytes``/``status``) by id with the same validation and ``None`` for
  an unknown id;
* owner listings are exact, isolated, unassociated-excluding, and ordered by
  rowid insertion order;
* metadata survives a database dispose + reopen.

This is adapter-level durability: no content store, service, or routes.
"""

from datetime import UTC, datetime

import pytest

from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories import RelationalAttachmentRepository
from ava.repositories import AttachmentRecord
from ava.services.attachment_store import InMemoryAttachmentRepository


def _database(database_url: str) -> SqliteDatabase:
    return SqliteDatabase(database_url)


def _relational(database_url: str = ":memory:") -> RelationalAttachmentRepository:
    return RelationalAttachmentRepository(database=_database(database_url))


def _sample(
    attachment_id: str = "attachment-1",
    file_name: str = "report.pdf",
    media_type: str = "application/pdf",
    storage_key: str = "attachments/attachment-1/source.pdf",
    owner_type: AttachmentOwnerType | None = AttachmentOwnerType.DOCUMENT,
    owner_id: str | None = "doc-1",
    status: AttachmentStatus = AttachmentStatus.AVAILABLE,
    size_bytes: int = 1024,
    created_at: datetime | None = None,
) -> AttachmentRecord:
    return AttachmentRecord(
        attachment_id=attachment_id,
        file_name=file_name,
        media_type=media_type,
        size_bytes=size_bytes,
        storage_key=storage_key,
        owner_type=owner_type,
        owner_id=owner_id,
        status=status,
        created_at=created_at or datetime(2026, 3, 5, 7, 8, 9, tzinfo=UTC),
    )


# ============================================================
# BEGIN: Create/get round trip
# ============================================================


def test_create_and_get_round_trip_all_metadata_fields() -> None:
    repository = _relational()
    created_at = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    record = _sample(created_at=created_at)
    repository.create(record)

    stored = repository.get("attachment-1")

    assert stored is not None
    assert stored.attachment_id == record.attachment_id
    assert stored.file_name == record.file_name
    assert stored.media_type == record.media_type
    assert stored.size_bytes == record.size_bytes
    assert stored.storage_key == record.storage_key
    assert stored.owner_type == AttachmentOwnerType.DOCUMENT
    assert stored.owner_id == "doc-1"
    assert stored.status == AttachmentStatus.AVAILABLE
    assert stored.created_at == created_at
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset() == UTC.utcoffset(None)


def test_enum_round_trip_across_all_owner_and_status_values() -> None:
    repository = _relational()
    source = _sample(attachment_id="a-1", owner_type=AttachmentOwnerType.CONVERSATION, owner_id="c-1",
                     status=AttachmentStatus.PENDING)
    source_two = _sample(attachment_id="a-2", owner_type=AttachmentOwnerType.MESSAGE, owner_id="m-1",
                         status=AttachmentStatus.FAILED, storage_key="attachments/a-2/source")
    repository.create(source)
    repository.create(source_two)

    assert repository.get("a-1").owner_type == AttachmentOwnerType.CONVERSATION
    assert repository.get("a-1").status == AttachmentStatus.PENDING
    assert repository.get("a-2").owner_type == AttachmentOwnerType.MESSAGE
    assert repository.get("a-2").status == AttachmentStatus.FAILED


def test_aware_datetime_round_trip_is_exact() -> None:
    repository = _relational()
    created_at = datetime(2026, 6, 1, 12, 34, 56, 123456, tzinfo=UTC)
    repository.create(_sample(created_at=created_at))

    assert repository.get("attachment-1").created_at == created_at


def test_owner_nullability_round_trips_both_ways() -> None:
    repository = _relational()
    unassociated = _sample(owner_type=None, owner_id=None)
    repository.create(unassociated)

    stored = repository.get("attachment-1")
    assert stored.owner_type is None
    assert stored.owner_id is None


def test_create_returns_the_supplied_record_unchanged() -> None:
    repository = _relational()
    record = _sample()

    returned = repository.create(record)

    assert isinstance(returned, AttachmentRecord)
    assert returned == record
    assert returned.created_at == record.created_at


# ============================================================
# END: Create/get round trip
# ============================================================


# ============================================================
# BEGIN: Duplicate and invariant validation
# ============================================================


def test_duplicate_attachment_id_raises_value_error() -> None:
    repository = _relational()
    repository.create(_sample())

    with pytest.raises(ValueError, match=r"Attachment already exists: attachment-1"):
        repository.create(_sample())


def test_duplicate_storage_key_raises_value_error() -> None:
    repository = _relational()
    repository.create(_sample())

    with pytest.raises(ValueError, match=r"Attachment storage key already in use: attachments/attachment-1/source.pdf"):
        repository.create(_sample(attachment_id="attachment-9", status=AttachmentStatus.PENDING))


def test_invalid_owner_pair_raises_value_error() -> None:
    repository = _relational()
    for owner_type, owner_id in (
        (AttachmentOwnerType.DOCUMENT, None),
        (None, "doc-1"),
    ):
        with pytest.raises(ValueError, match="owner_type and owner_id must be both set or both None"):
            repository.create(_sample(owner_type=owner_type, owner_id=owner_id))


def test_negative_size_raises_value_error() -> None:
    repository = _relational()
    with pytest.raises(ValueError, match="size_bytes must be non-negative"):
        repository.create(_sample(size_bytes=-1))


def test_zero_size_is_allowed() -> None:
    repository = _relational()
    repository.create(_sample(size_bytes=0))

    stored = repository.get("attachment-1")
    assert stored.size_bytes == 0


def test_duplicate_filename_is_allowed() -> None:
    repository = _relational()
    repository.create(_sample())
    repository.create(
        _sample(attachment_id="attachment-2", file_name="report.pdf", storage_key="attachments/attachment-2/source.pdf")
    )

    assert repository.get("attachment-1").file_name == "report.pdf"
    assert repository.get("attachment-2").file_name == "report.pdf"


# ============================================================
# END: Duplicate and invariant validation
# ============================================================


# ============================================================
# BEGIN: list_for_owner
# ============================================================


def test_list_for_owner_is_isolated_by_type_and_id() -> None:
    repository = _relational()
    doc_of_doc1 = _sample(attachment_id="a-1", owner_type=AttachmentOwnerType.DOCUMENT, owner_id="doc-1")
    doc_of_other = _sample(attachment_id="a-2", owner_type=AttachmentOwnerType.DOCUMENT, owner_id="doc-2",
                           storage_key="attachments/a-2/source")
    conv = _sample(attachment_id="a-3", owner_type=AttachmentOwnerType.CONVERSATION, owner_id="doc-1",
                   storage_key="attachments/a-3/source")
    everyone = _sample(attachment_id="a-4", owner_type=None, owner_id=None,
                       storage_key="attachments/a-4/source")
    repository.create(doc_of_doc1)
    repository.create(doc_of_other)
    repository.create(conv)
    repository.create(everyone)

    assert [r.attachment_id for r in repository.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")] == ["a-1"]
    assert [r.attachment_id for r in repository.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-2")] == ["a-2"]
    assert [r.attachment_id for r in repository.list_for_owner(AttachmentOwnerType.CONVERSATION, "doc-1")] == ["a-3"]
    assert repository.list_for_owner(AttachmentOwnerType.MESSAGE, "doc-1") == []


def test_unassociated_attachments_are_excluded_from_owner_lists() -> None:
    repository = _relational()
    repository.create(_sample())
    repository.create(
        _sample(attachment_id="u-1", owner_type=None, owner_id=None, storage_key="attachments/u-1/source")
    )

    for owner_type in AttachmentOwnerType:
        if owner_type is AttachmentOwnerType.DOCUMENT:
            assert [r.attachment_id for r in repository.list_for_owner(owner_type, "doc-1")] == ["attachment-1"]
        else:
            assert repository.list_for_owner(owner_type, "doc-1") == []
    assert repository.list_for_owner(AttachmentOwnerType.DOCUMENT, "other") == []
    assert repository.list_for_owner(AttachmentOwnerType.MESSAGE, "other") == []


def test_list_for_owner_is_deterministic_creation_order() -> None:
    repository = _relational()
    for index in range(5):
        repository.create(
            _sample(attachment_id=f"a-{index}", storage_key=f"attachments/a-{index}/source")
        )

    listed = repository.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")
    assert [r.attachment_id for r in listed] == ["a-0", "a-1", "a-2", "a-3", "a-4"]


def test_list_for_owner_returns_a_caller_isolated_collection() -> None:
    repository = _relational()
    repository.create(_sample())

    first = repository.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")
    first.clear()

    assert [r.attachment_id for r in repository.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")] == [
        "attachment-1",
    ]


# ============================================================
# END: list_for_owner
# ============================================================


# ============================================================
# BEGIN: get() behavior
# ============================================================


def test_unknown_get_returns_none() -> None:
    repository = _relational()
    assert repository.get("missing") is None
    repository.create(_sample())
    assert repository.get("missing") is None


# ============================================================
# END: get() behavior
# ============================================================


# ============================================================
# BEGIN: update_state behavior
# ============================================================


def test_update_state_advances_size_and_status_and_preserves_immutables() -> None:
    repository = _relational()
    created_at = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    repository.create(_sample(created_at=created_at, size_bytes=0, status=AttachmentStatus.PENDING))

    updated = repository.update_state(
        "attachment-1", size_bytes=2048, status=AttachmentStatus.AVAILABLE
    )

    assert updated is not None
    assert updated.attachment_id == "attachment-1"
    assert updated.file_name == "report.pdf"
    assert updated.media_type == "application/pdf"
    assert updated.size_bytes == 2048
    assert updated.storage_key == "attachments/attachment-1/source.pdf"
    assert updated.owner_type == AttachmentOwnerType.DOCUMENT
    assert updated.owner_id == "doc-1"
    assert updated.status == AttachmentStatus.AVAILABLE
    assert updated.created_at == created_at
    assert updated.created_at.tzinfo is not None

    stored = repository.get("attachment-1")
    assert stored.size_bytes == 2048
    assert stored.status == AttachmentStatus.AVAILABLE


def test_update_state_records_failed_status_and_preserves_owner() -> None:
    repository = _relational()
    repository.create(
        _sample(attachment_id="a-1", owner_type=AttachmentOwnerType.CONVERSATION, owner_id="c-1",
                status=AttachmentStatus.PENDING, size_bytes=0)
    )

    output = repository.update_state("a-1", size_bytes=0, status=AttachmentStatus.FAILED)

    assert output.status == AttachmentStatus.FAILED
    stored = repository.get("a-1")
    assert stored.status == AttachmentStatus.FAILED
    assert stored.owner_type == AttachmentOwnerType.CONVERSATION
    assert stored.owner_id == "c-1"


def test_update_state_unknown_attachment_returns_none_without_error() -> None:
    repository = _relational()
    repository.create(_sample())

    assert repository.update_state("ghost", size_bytes=1, status=AttachmentStatus.FAILED) is None

    assert repository.get("attachment-1").status == AttachmentStatus.AVAILABLE
    assert repository.get("attachment-1").size_bytes == 1024


def test_update_state_rejects_negative_size_and_leaves_row_untouched() -> None:
    repository = _relational()
    repository.create(_sample(status=AttachmentStatus.PENDING))

    with pytest.raises(ValueError, match="non-negative"):
        repository.update_state("attachment-1", size_bytes=-1, status=AttachmentStatus.FAILED)

    stored = repository.get("attachment-1")
    assert stored.status == AttachmentStatus.PENDING
    assert stored.size_bytes == 1024


def test_update_state_survives_database_reopen(tmp_path) -> None:
    path = tmp_path / "ava.sqlite3"
    first = _relational(str(path))
    first.create(_sample(status=AttachmentStatus.PENDING, size_bytes=0))
    first.update_state("attachment-1", size_bytes=300, status=AttachmentStatus.AVAILABLE)
    first._database.dispose()

    second = _relational(str(path))
    try:
        restored = second.get("attachment-1")
        assert restored.size_bytes == 300
        assert restored.status == AttachmentStatus.AVAILABLE
    finally:
        second._database.dispose()


# ============================================================
# END: update_state behavior
# ============================================================


# ============================================================
# BEGIN: Behavioral parity with the in-memory store
# ============================================================


@pytest.mark.parametrize(
    "scenario",
    [
        "round_trip",
        "duplicate_id",
        "duplicate_storage_key",
        "invalid_owner_pair",
        "negative_size",
        "zero_size",
        "duplicate_filename",
        "unassociated_excluded",
        "ordering",
        "unknown_get",
        "update_state",
    ],
)
def test_memory_and_relational_repositories_agree(scenario: str) -> None:
    """Both stores produce identical outcomes for identical inputs."""
    memory = InMemoryAttachmentRepository()
    relational = _relational()

    def run(repository) -> list[object]:
        outcome: list[object] = []
        if scenario == "round_trip":
            record = _sample()
            repository.create(record)
            stored = repository.get("attachment-1")
            outcome.append(stored == record)
            outcome.append(stored.created_at.utcoffset() == UTC.utcoffset(None))
        elif scenario == "duplicate_id":
            repository.create(_sample())
            try:
                repository.create(_sample())
                outcome.append("no-error")
            except ValueError as exc:
                outcome.append(str(exc))
        elif scenario == "duplicate_storage_key":
            repository.create(_sample())
            try:
                repository.create(_sample(attachment_id="attachment-9"))
                outcome.append("no-error")
            except ValueError as exc:
                outcome.append(str(exc))
        elif scenario == "invalid_owner_pair":
            for owner_type, owner_id in ((AttachmentOwnerType.DOCUMENT, None), (None, "doc-1")):
                try:
                    repository.create(_sample(owner_type=owner_type, owner_id=owner_id))
                    outcome.append("no-error")
                except ValueError as exc:
                    outcome.append(str(exc))
        elif scenario == "negative_size":
            try:
                repository.create(_sample(size_bytes=-1))
                outcome.append("no-error")
            except ValueError as exc:
                outcome.append(str(exc))
        elif scenario == "zero_size":
            repository.create(_sample(size_bytes=0))
            outcome.append(repository.get("attachment-1").size_bytes)
        elif scenario == "duplicate_filename":
            repository.create(_sample())
            repository.create(_sample(attachment_id="attachment-2", storage_key="attachments/attachment-2/source"))
            outcome.append(repository.get("attachment-2").file_name)
        elif scenario == "unassociated_excluded":
            repository.create(_sample(owner_type=None, owner_id=None))
            outcome.append(
                [r.attachment_id for r in repository.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")]
            )
        elif scenario == "ordering":
            for index in range(3):
                repository.create(_sample(attachment_id=f"a-{index}", storage_key=f"attachments/a-{index}/source"))
            outcome.append(
                [r.attachment_id for r in repository.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")]
            )
        elif scenario == "unknown_get":
            outcome.append(repository.get("missing") is None)
        elif scenario == "update_state":
            repository.create(_sample(status=AttachmentStatus.PENDING, size_bytes=0))
            outcome.append(repository.update_state("ghost", size_bytes=1, status=AttachmentStatus.FAILED) is None)
            try:
                repository.update_state("attachment-1", size_bytes=555, status=AttachmentStatus.AVAILABLE)
                outcome.append("ok")
            except ValueError as exc:
                outcome.append(str(exc))
            stored = repository.get("attachment-1")
            outcome.append(stored.size_bytes)
            outcome.append(stored.status)
        return outcome

    assert run(memory) == run(relational), scenario


# ============================================================
# END: Behavioral parity with the in-memory store
# ============================================================


# ============================================================
# BEGIN: Reopen durability
# ============================================================


def test_attachment_metadata_survives_database_reopen(tmp_path) -> None:
    """Dispose + reopen of the same file-backed database restores metadata."""
    path = tmp_path / "ava.sqlite3"
    created_at = datetime(2026, 4, 12, 10, 20, 30, tzinfo=UTC)

    first = _relational(str(path))
    first.create(
        _sample(
            attachment_id="attachment-7",
            file_name="notes.txt",
            media_type="text/plain",
            storage_key="attachments/attachment-7/source",
            owner_type=AttachmentOwnerType.CONVERSATION,
            owner_id="conv-1",
            status=AttachmentStatus.PENDING,
            size_bytes=0,
            created_at=created_at,
        )
    )
    first.create(
        _sample(
            attachment_id="attachment-8",
            file_name="report.pdf",
            storage_key="attachments/attachment-8/source",
            owner_type=AttachmentOwnerType.DOCUMENT,
            owner_id="doc-9",
            status=AttachmentStatus.AVAILABLE,
            created_at=created_at,
        )
    )
    first._database.dispose()

    second = _relational(str(path))
    try:
        restored = second.get("attachment-7")
        assert restored is not None
        assert restored.file_name == "notes.txt"
        assert restored.media_type == "text/plain"
        assert restored.size_bytes == 0
        assert restored.storage_key == "attachments/attachment-7/source"
        assert restored.owner_type == AttachmentOwnerType.CONVERSATION
        assert restored.owner_id == "conv-1"
        assert restored.status == AttachmentStatus.PENDING
        assert restored.created_at == created_at
        assert restored.created_at.utcoffset() == UTC.utcoffset(None)

        assert [r.attachment_id for r in second.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-9")] == [
            "attachment-8",
        ]
        assert [r.attachment_id for r in second.list_for_owner(AttachmentOwnerType.CONVERSATION, "conv-1")] == [
            "attachment-7",
        ]
        assert second.get("attachment-7").created_at == created_at
    finally:
        second._database.dispose()


# ============================================================
# END: Reopen durability
# ============================================================


def test_public_surface_exposes_only_the_port_operations() -> None:
    """The relational adapter adds no metadata/content surface beyond the port."""
    from inspect import getmembers

    operations = {
        name
        for name, member in getmembers(RelationalAttachmentRepository)
        if not name.startswith("_") and callable(member)
    }
    assert operations == {"create", "get", "list_for_owner", "update_state", "delete"}
