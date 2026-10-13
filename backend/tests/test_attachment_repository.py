"""AttachmentRecord/AttachmentRepository port tests (Step 4.14.A).

Prove the immutable attachment-metadata domain contract:

* records are frozen snapshots with exactly the approved metadata fields;
* the owner/status enums are AVA-owned ``StrEnum`` vocabulary;
* the repository is an abstract contract declaring its metadata operations
  (``create``/``get``/``list_for_owner``/``update_state``/``delete``);
  beyond the lifecycle-controlled ``size_bytes``/``status`` pair;
* ``create`` accepts the immutable record wholesale (no caller-supplied
  identity/status split) and every boundary type is AVA-owned or stdlib.

No physical content, database, service, or routes are introduced or
exercised here (Step 4.14.B+).
"""

import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from inspect import getmembers, signature
from typing import get_args, get_type_hints

import pytest

from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.repositories import (
    AttachmentRecord,
    AttachmentRepository,
)

# ============================================================
# BEGIN: Test double (port shape prove)
# ============================================================


class MemoryAttachmentRepository(AttachmentRepository):
    """Framework-free test double used only to prove the port is implementable.

    Mirrors the semantics the real stores will honor: duplicate
    ``attachment_id`` and duplicate ``storage_key`` raise ``ValueError``, the
    owner pair must be both-set/both-``None``, ``size_bytes`` must be
    non-negative, listings are insertion-ordered, and ``update_state`` mutates
    exactly the lifecycle-controlled pair (``None`` for an unknown id). This
    is a port-shape fake, not the Step 4.14.A store.
    """

    def __init__(self) -> None:
        self._attachments: dict[str, AttachmentRecord] = {}

    def create(self, record: AttachmentRecord) -> AttachmentRecord:
        if record.attachment_id in self._attachments:
            raise ValueError(f"Attachment already exists: {record.attachment_id}")
        if (record.owner_type is None) != (record.owner_id is None):
            raise ValueError("owner_type and owner_id must be both set or both None")
        if record.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        self._attachments[record.attachment_id] = record
        return record

    def get(self, attachment_id: str) -> AttachmentRecord | None:
        return self._attachments.get(attachment_id)

    def list_for_owner(
        self,
        owner_type: AttachmentOwnerType,
        owner_id: str,
    ) -> list[AttachmentRecord]:
        return [
            record
            for record in self._attachments.values()
            if record.owner_type == owner_type and record.owner_id == owner_id
        ]

    def update_state(
        self,
        attachment_id: str,
        *,
        size_bytes: int,
        status: AttachmentStatus,
    ) -> AttachmentRecord | None:
        current = self._attachments.get(attachment_id)
        if current is None:
            return None
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        refreshed = AttachmentRecord(
            attachment_id=current.attachment_id,
            file_name=current.file_name,
            media_type=current.media_type,
            size_bytes=size_bytes,
            storage_key=current.storage_key,
            owner_type=current.owner_type,
            owner_id=current.owner_id,
            status=status,
            created_at=current.created_at,
        )
        self._attachments[attachment_id] = refreshed
        return refreshed

    def delete(self, attachment_id: str) -> AttachmentRecord | None:
        return self._attachments.pop(attachment_id, None)


# ============================================================
# END: Test double (port shape prove)
# ============================================================


# ============================================================
# BEGIN: Fixtures
# ============================================================


def sample_attachment(
    attachment_id: str = "attachment-1",
    file_name: str = "report.pdf",
    status: AttachmentStatus = AttachmentStatus.AVAILABLE,
    owner_type: AttachmentOwnerType | None = AttachmentOwnerType.DOCUMENT,
    owner_id: str | None = "doc-1",
) -> AttachmentRecord:
    """Create a sample immutable attachment record for assertions."""
    return AttachmentRecord(
        attachment_id=attachment_id,
        file_name=file_name,
        media_type="application/pdf",
        size_bytes=1024,
        storage_key=f"attachments/{attachment_id}/source.pdf",
        owner_type=owner_type,
        owner_id=owner_id,
        status=status,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# ============================================================
# END: Fixtures
# ============================================================


# ============================================================
# BEGIN: Vocabulary
# ============================================================


def test_attachment_owner_type_enum_membership() -> None:
    """The owner vocabulary is exactly document/conversation/message."""
    assert AttachmentOwnerType.DOCUMENT.value == "document"
    assert AttachmentOwnerType.CONVERSATION.value == "conversation"
    assert AttachmentOwnerType.MESSAGE.value == "message"
    assert set(AttachmentOwnerType) == {
        AttachmentOwnerType.DOCUMENT,
        AttachmentOwnerType.CONVERSATION,
        AttachmentOwnerType.MESSAGE,
    }


def test_attachment_status_enum_membership() -> None:
    """The lifecycle vocabulary is exactly pending/available/failed."""
    assert AttachmentStatus.PENDING.value == "pending"
    assert AttachmentStatus.AVAILABLE.value == "available"
    assert AttachmentStatus.FAILED.value == "failed"
    assert set(AttachmentStatus) == {
        AttachmentStatus.PENDING,
        AttachmentStatus.AVAILABLE,
        AttachmentStatus.FAILED,
    }


# ============================================================
# END: Vocabulary
# ============================================================


# ============================================================
# BEGIN: Record shape
# ============================================================


def test_attachment_record_retains_all_fields() -> None:
    """Every approved field is retained exactly as supplied."""
    created_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    record = AttachmentRecord(
        attachment_id="attachment-9",
        file_name="notes.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=0,
        storage_key="attachments/attachment-9/source.docx",
        owner_type=AttachmentOwnerType.MESSAGE,
        owner_id="message-42",
        status=AttachmentStatus.PENDING,
        created_at=created_at,
    )

    assert record.attachment_id == "attachment-9"
    assert record.file_name == "notes.docx"
    assert record.media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert record.size_bytes == 0
    assert record.storage_key == "attachments/attachment-9/source.docx"
    assert record.owner_type == AttachmentOwnerType.MESSAGE
    assert record.owner_id == "message-42"
    assert record.status == AttachmentStatus.PENDING
    assert record.created_at == created_at


def test_attachment_record_has_exactly_the_approved_fields() -> None:
    """No wire-only, persistence-surrogate, provider, or deferred fields creep in."""
    fields = {field.name for field in AttachmentRecord.__dataclass_fields__.values()}
    assert fields == {
        "attachment_id",
        "file_name",
        "media_type",
        "size_bytes",
        "storage_key",
        "owner_type",
        "owner_id",
        "status",
        "created_at",
    }


def test_attachment_record_is_immutable() -> None:
    """The frozen snapshot cannot be mutated after construction."""
    record = sample_attachment()

    with pytest.raises(FrozenInstanceError):
        record.file_name = "changed.txt"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.status = AttachmentStatus.FAILED  # type: ignore[misc]


def test_attachment_record_supports_unassociated_owner() -> None:
    """``owner_type=None``/``owner_id=None`` is a valid (unassociated) record."""
    record = sample_attachment(owner_type=None, owner_id=None)
    assert record.owner_type is None
    assert record.owner_id is None


# ============================================================
# END: Record shape
# ============================================================


# ============================================================
# BEGIN: Abstract contract
# ============================================================


def test_attachment_repository_is_an_abstract_contract() -> None:
    """The port is a contract, not a usable default implementation."""
    with pytest.raises(TypeError):
        AttachmentRepository()  # type: ignore[abstract]


def test_port_declares_exactly_the_four_operations_as_abstract() -> None:
    """All four approved operations are abstract; nothing else is enforced."""
    assert AttachmentRepository.__abstractmethods__ == frozenset(
        {"create", "get", "list_for_owner", "update_state", "delete"}
    )


def test_attachment_repository_is_implementable_by_fake() -> None:
    """The port surface can be satisfied without any framework or database."""
    repo = MemoryAttachmentRepository()

    stored = repo.create(sample_attachment())
    assert repo.get("attachment-1") is stored
    assert [r.attachment_id for r in repo.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-1")] == [
        "attachment-1",
    ]

    assert repo.get("unknown") is None
    assert repo.list_for_owner(AttachmentOwnerType.DOCUMENT, "other") == []
    assert repo.list_for_owner(AttachmentOwnerType.MESSAGE, "doc-1") == []
    assert repo.update_state("unknown", size_bytes=5, status=AttachmentStatus.FAILED) is None


def test_create_accepts_the_immutable_record_wholesale() -> None:
    """``create`` takes one ``AttachmentRecord``; identity/status are not split out."""
    parameters = [
        name for name in signature(AttachmentRepository.create).parameters if name != "self"
    ]
    assert parameters == ["record"]


# ============================================================
# END: Abstract contract
# ============================================================


# ============================================================
# BEGIN: No mutation beyond update_state
# ============================================================


def test_attachment_port_exposes_scoped_delete_and_lifecycle_update() -> None:
    """Metadata supports deletion and lifecycle update, not generic mutation."""
    operations = {
        name
        for name, member in getmembers(AttachmentRepository)
        if not name.startswith("_") and callable(member)
    }
    assert operations == {"create", "get", "list_for_owner", "update_state", "delete"}


# ============================================================
# END: No mutation beyond update_state
# ============================================================


# ============================================================
# BEGIN: Return-type conventions
# ============================================================


def test_attachment_port_return_type_conventions() -> None:
    """Lists return an attachment collection; lookups are optional."""
    list_hint = get_type_hints(AttachmentRepository.list_for_owner)["return"]
    assert get_args(list_hint)[0] is AttachmentRecord

    get_hint = get_type_hints(AttachmentRepository.get)["return"]
    assert get_args(get_hint) == (AttachmentRecord, type(None))

    state_hint = get_type_hints(AttachmentRepository.update_state)["return"]
    assert get_args(state_hint) == (AttachmentRecord, type(None))


# ============================================================
# END: Return-type conventions
# ============================================================


# ============================================================
# BEGIN: Boundary type discipline
# ============================================================


def _annotation_root_modules(annotation: object) -> set[str]:
    """Collect top-level module names reachable from a type annotation."""
    modules: set[str] = set()
    pending = [annotation]
    while pending:
        current = pending.pop()
        module = getattr(current, "__module__", None)
        if module:
            modules.add(module.split(".")[0])
        pending.extend(arg for arg in get_args(current) if arg is not current)
    return modules


def test_attachment_port_boundary_types_are_ava_owned_or_stdlib_only() -> None:
    """No provider/framework/database type crosses the port boundary."""
    methods = [
        AttachmentRepository.create,
        AttachmentRepository.get,
        AttachmentRepository.list_for_owner,
        AttachmentRepository.update_state,
    ]
    for method in methods:
        for annotation in get_type_hints(method).values():
            for module in _annotation_root_modules(annotation):
                assert module in sys.stdlib_module_names or module == "ava", (
                    AttachmentRepository.__name__,
                    method.__name__,
                    module,
                )


# ============================================================
# END: Boundary type discipline
# ============================================================


# ============================================================
# BEGIN: Public exports
# ============================================================


def test_attachment_symbols_are_publicly_exported() -> None:
    """Callers reach the record + port through the ``ava.repositories`` barrel."""
    from ava.repositories import __all__ as repositories_all

    assert "AttachmentRecord" in repositories_all
    assert "AttachmentRepository" in repositories_all

    import ava.repositories as repositories

    exported_record = repositories.AttachmentRecord
    exported_repository = repositories.AttachmentRepository
    assert isinstance(sample_attachment(), exported_record)
    assert exported_repository is AttachmentRepository
    assert exported_repository.__abstractmethods__ == frozenset(
        {"create", "get", "list_for_owner", "update_state", "delete"}
    )


def test_attachment_enum_symbols_are_publicly_exported() -> None:
    """The owner/status vocabulary is reachable through the ``ava.contracts`` barrel."""
    import ava.contracts as contracts

    assert contracts.AttachmentOwnerType is AttachmentOwnerType
    assert contracts.AttachmentStatus is AttachmentStatus

    from ava.contracts import __all__ as contracts_all

    assert "AttachmentOwnerType" in contracts_all
    assert "AttachmentStatus" in contracts_all


# ============================================================
# END: Public exports
# ============================================================
