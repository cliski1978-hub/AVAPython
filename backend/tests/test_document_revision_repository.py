"""DocumentRevisionRecord/DocumentRevisionRepository port tests (Step 4.13.A).

Prove the immutable document-revision domain contract:

* records are frozen snapshots with exactly the approved fields;
* the repository is an abstract contract declaring exactly four operations
  (``append``/``list_for_document``/``get``/``get_latest``) and no mutation
  operations;
* ``append`` never accepts a caller-supplied ``revision_number`` and rejects a
  duplicate ``revision_id`` as a ``ValueError``;
* a framework-free test double can satisfy the port;
* every port boundary type is AVA-owned or stdlib.

No revision persistence is introduced or exercised here (Step 4.13.B+).
"""

import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from inspect import getmembers, signature
from typing import get_args, get_type_hints

import pytest

from ava.contracts.documents import ContentFormat
from ava.repositories import (
    DocumentRevisionRecord,
    DocumentRevisionRepository,
)

# ============================================================
# BEGIN: Test double (port shape prove)
# ============================================================


class MemoryDocumentRevisionRepository(DocumentRevisionRepository):
    """Framework-free test double used only to prove the port is implementable.

    Mirrors the semantics the real stores will honor in later slices:
    ``append`` assigns ``revision_number`` internally (never caller-supplied),
    a duplicate ``revision_id`` raises ``ValueError``, and listings order by
    revision number. This is a port-shape fake, not the Step 4.13.B store.
    """

    def __init__(self) -> None:
        self._revisions: dict[str, list[DocumentRevisionRecord]] = {}

    def append(
        self,
        document_id: str,
        *,
        revision_id: str,
        title: str,
        content: str,
        content_format: ContentFormat,
        created_at: datetime,
    ) -> DocumentRevisionRecord:
        revisions = self._revisions.setdefault(document_id, [])
        if any(record.revision_id == revision_id for record in revisions):
            raise ValueError(f"Revision already exists: {revision_id}")
        record = DocumentRevisionRecord(
            revision_id=revision_id,
            document_id=document_id,
            revision_number=len(revisions) + 1,
            title=title,
            content=content,
            content_format=content_format,
            created_at=created_at,
        )
        revisions.append(record)
        return record

    def list_for_document(self, document_id: str) -> list[DocumentRevisionRecord]:
        return list(self._revisions.get(document_id, []))

    def get(self, document_id: str, revision_id: str) -> DocumentRevisionRecord | None:
        for record in self._revisions.get(document_id, []):
            if record.revision_id == revision_id:
                return record
        return None

    def get_latest(self, document_id: str) -> DocumentRevisionRecord | None:
        revisions = self._revisions.get(document_id)
        return revisions[-1] if revisions else None


# ============================================================
# END: Test double (port shape prove)
# ============================================================


# ============================================================
# BEGIN: Fixtures
# ============================================================


def sample_revision(
    revision_id: str = "revision-1",
    document_id: str = "doc-1",
    revision_number: int = 1,
) -> DocumentRevisionRecord:
    """Create a sample immutable revision record for assertions."""
    return DocumentRevisionRecord(
        revision_id=revision_id,
        document_id=document_id,
        revision_number=revision_number,
        title="Untitled Document",
        content="<p>body</p>",
        content_format=ContentFormat.HTML,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# ============================================================
# END: Fixtures
# ============================================================


# ============================================================
# BEGIN: Record shape
# ============================================================


def test_document_revision_record_retains_all_fields() -> None:
    """Every approved field is retained exactly as supplied."""
    created_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    record = DocumentRevisionRecord(
        revision_id="revision-9",
        document_id="doc-7",
        revision_number=3,
        title="Planning Notes",
        content="<h2>Plan</h2><p>body</p>",
        content_format=ContentFormat.HTML,
        created_at=created_at,
    )

    assert record.revision_id == "revision-9"
    assert record.document_id == "doc-7"
    assert record.revision_number == 3
    assert record.title == "Planning Notes"
    assert record.content == "<h2>Plan</h2><p>body</p>"
    assert record.content_format == ContentFormat.HTML
    assert record.created_at == created_at


def test_document_revision_record_has_exactly_the_approved_fields() -> None:
    """No wire-only, persistence-surrogate, or deferred fields creep into the record."""
    fields = {
        field.name for field in DocumentRevisionRecord.__dataclass_fields__.values()
    }
    assert fields == {
        "revision_id",
        "document_id",
        "revision_number",
        "title",
        "content",
        "content_format",
        "created_at",
    }


def test_document_revision_record_is_immutable() -> None:
    """The frozen snapshot cannot be mutated after construction."""
    record = sample_revision()

    with pytest.raises(FrozenInstanceError):
        record.title = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.revision_number = 99  # type: ignore[misc]


# ============================================================
# END: Record shape
# ============================================================


# ============================================================
# BEGIN: Abstract contract
# ============================================================


def test_document_revision_repository_is_an_abstract_contract() -> None:
    """The port is a contract, not a usable default implementation."""
    with pytest.raises(TypeError):
        DocumentRevisionRepository()  # type: ignore[abstract]


def test_port_declares_exactly_the_four_operations_as_abstract() -> None:
    """All four approved operations are abstract; nothing else is enforced."""
    assert DocumentRevisionRepository.__abstractmethods__ == frozenset(
        {"append", "list_for_document", "get", "get_latest"}
    )


def test_document_revision_repository_is_implementable_by_fake() -> None:
    """The port surface can be satisfied without any framework or database."""
    repo = MemoryDocumentRevisionRepository()
    created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    first = repo.append(
        "doc-1",
        revision_id="revision-1",
        title="Untitled Document",
        content="<p></p>",
        content_format=ContentFormat.HTML,
        created_at=created_at,
    )
    second = repo.append(
        "doc-1",
        revision_id="revision-2",
        title="Untitled Document",
        content="<p>edit</p>",
        content_format=ContentFormat.HTML,
        created_at=created_at,
    )

    assert first.revision_number == 1
    assert second.revision_number == 2
    assert [record.revision_id for record in repo.list_for_document("doc-1")] == [
        "revision-1",
        "revision-2",
    ]
    assert repo.get("doc-1", "revision-2") is second
    assert repo.get_latest("doc-1") is second

    assert repo.list_for_document("unknown") == []
    assert repo.get("unknown", "revision-1") is None
    assert repo.get("doc-1", "ghost") is None
    assert repo.get_latest("unknown") is None


def test_append_rejects_duplicate_revision_id() -> None:
    """A duplicate immutable revision identity is a ``ValueError``."""
    repo = MemoryDocumentRevisionRepository()
    repo.append(
        "doc-1",
        revision_id="revision-1",
        title="T",
        content="<p></p>",
        content_format=ContentFormat.HTML,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="already exists"):
        repo.append(
            "doc-1",
            revision_id="revision-1",
            title="T",
            content="<p>other</p>",
            content_format=ContentFormat.HTML,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_append_never_accepts_a_caller_supplied_revision_number() -> None:
    """``revision_number`` is repository-owned and absent from the port signature."""
    parameters = list(signature(DocumentRevisionRepository.append).parameters)
    assert "revision_number" not in parameters
    assert "document_id" in parameters
    assert "revision_id" in parameters
    assert "title" in parameters
    assert "content" in parameters
    assert "content_format" in parameters
    assert "created_at" in parameters


# ============================================================
# END: Abstract contract
# ============================================================


# ============================================================
# BEGIN: No mutation surface
# ============================================================


def test_revision_port_exposes_no_mutation_operations() -> None:
    """Historical revisions are immutable: no update/delete/replace/rename."""
    operations = {
        name
        for name, member in getmembers(DocumentRevisionRepository)
        if not name.startswith("_") and callable(member)
    }
    assert operations == {"append", "list_for_document", "get", "get_latest"}


# ============================================================
# END: No mutation surface
# ============================================================


# ============================================================
# BEGIN: Return-type conventions
# ============================================================


def test_revision_port_return_type_conventions() -> None:
    """Lists return a document-revision collection; lookups are optional."""
    list_hint = get_type_hints(DocumentRevisionRepository.list_for_document)["return"]
    assert get_args(list_hint)[0] is DocumentRevisionRecord

    for method in (DocumentRevisionRepository.get, DocumentRevisionRepository.get_latest):
        return_hint = get_type_hints(method)["return"]
        assert get_args(return_hint) == (DocumentRevisionRecord, type(None))


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


def test_revision_port_boundary_types_are_ava_owned_or_stdlib_only() -> None:
    """No provider/framework/database type crosses the port boundary."""
    methods = [
        DocumentRevisionRepository.append,
        DocumentRevisionRepository.list_for_document,
        DocumentRevisionRepository.get,
        DocumentRevisionRepository.get_latest,
    ]
    for method in methods:
        for annotation in get_type_hints(method).values():
            for module in _annotation_root_modules(annotation):
                assert module in sys.stdlib_module_names or module == "ava", (
                    DocumentRevisionRepository.__name__,
                    method.__name__,
                    module,
                )


# ============================================================
# END: Boundary type discipline
# ============================================================


# ============================================================
# BEGIN: Public exports
# ============================================================


def test_document_revision_symbols_are_publicly_exported() -> None:
    """Callers reach both symbols through the ``ava.repositories`` barrel."""
    from ava.repositories import __all__ as repositories_all

    assert "DocumentRevisionRecord" in repositories_all
    assert "DocumentRevisionRepository" in repositories_all

    import ava.repositories as repositories

    exported_record = repositories.DocumentRevisionRecord
    exported_repository = repositories.DocumentRevisionRepository
    assert isinstance(sample_revision(), exported_record)
    assert exported_repository is DocumentRevisionRepository
    assert exported_repository.__abstractmethods__ == frozenset(
        {"append", "list_for_document", "get", "get_latest"}
    )


# ============================================================
# END: Public exports
# ============================================================