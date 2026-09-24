"""InMemoryDocumentWriteCoordinator tests (Step 4.13.B).

Prove the in-memory write coordinator advances document current state and
immutable revision history as one atomic unit:

* ``create`` persists the document and appends exactly revision 1;
* ``update`` advances the current state and appends exactly one next revision
  (a combined title+content save stays one revision) while earlier revisions
  remain untouched;
* any failure rolls back *both* stores: a document whose revision append
  failed does not exist / stays at its prior state, and history is unchanged;
* an unknown-document update and a duplicate create are ``ValueError``s that
  leave no trace.

Focused in-memory state only: no database, no service, no routes (Step 4.13.C+).
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from ava.contracts.documents import ContentFormat
from ava.repositories import DocumentRecord
from ava.services.document_revision_store import InMemoryDocumentRevisionStore
from ava.services.document_store import DocumentStore
from ava.services.document_write_coordinator import InMemoryDocumentWriteCoordinator

# ============================================================
# BEGIN: Fixtures
# ============================================================

STAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
NEXT_STAMP = datetime(2026, 1, 1, 12, 30, 0, tzinfo=UTC)


def make_coordinator(
    *,
    documents: DocumentStore | None = None,
    revisions: InMemoryDocumentRevisionStore | None = None,
) -> InMemoryDocumentWriteCoordinator:
    """Create a coordinator over fresh in-memory stores."""
    return InMemoryDocumentWriteCoordinator(
        documents=documents or DocumentStore(),
        revisions=revisions or InMemoryDocumentRevisionStore(),
    )


def sample_record(
    document_id: str = "doc-1",
    *,
    title: str = "Untitled Document",
    content: str = "<p>body</p>",
) -> DocumentRecord:
    """Create a sample current-state record for coordinator writes."""
    return DocumentRecord(
        document_id=document_id,
        title=title,
        content=content,
        content_format=ContentFormat.HTML,
        created_at=STAMP,
        updated_at=STAMP,
    )


class FailingRevisionStore(InMemoryDocumentRevisionStore):
    """Test double: an append of the ``poison`` revision id always fails.

    Proves the coordinator rolls the whole write back when the revision append
    fails after the current-state write has already happened.
    """

    def append(
        self,
        document_id: str,
        *,
        revision_id: str,
        title: str,
        content: str,
        content_format: ContentFormat,
        created_at: datetime,
    ):
        if revision_id == "poison":
            raise ValueError("Injected revision append failure")
        return super().append(
            document_id,
            revision_id=revision_id,
            title=title,
            content=content,
            content_format=content_format,
            created_at=created_at,
        )


# ============================================================
# END: Fixtures
# ============================================================

# ============================================================
# BEGIN: Create
# ============================================================

def test_create_persists_the_document_and_appends_revision_one() -> None:
    coordinator = make_coordinator()

    current, revision = coordinator.create(
        sample_record(),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )

    assert current.document_id == "doc-1"
    assert current.title == "Untitled Document"
    assert current.content == "<p>body</p>"
    assert coordinator._documents.get("doc-1") == current
    assert coordinator._revisions.list_for_document("doc-1") == [revision]

    assert revision.revision_id == "revision-1"
    assert revision.document_id == "doc-1"
    assert revision.revision_number == 1
    assert revision.title == "Untitled Document"
    assert revision.content == "<p>body</p>"
    assert revision.created_at == STAMP
    assert coordinator._revisions.get_latest("doc-1") is revision


def test_create_with_a_duplicate_document_leaves_no_trace() -> None:
    coordinator = make_coordinator()
    coordinator.create(sample_record(), revision_id="revision-1", revision_created_at=STAMP)

    with pytest.raises(ValueError, match="already exists"):
        coordinator.create(
            sample_record(title="Intruder"),
            revision_id="revision-2",
            revision_created_at=STAMP,
        )

    assert coordinator._revisions.list_for_document("doc-1") == [
        coordinator._revisions.get("doc-1", "revision-1"),
    ]
    assert coordinator._documents.list()[0].title == "Untitled Document"


def test_create_appends_exactly_one_revision() -> None:
    coordinator = make_coordinator()
    coordinator.create(sample_record(), revision_id="revision-1", revision_created_at=STAMP)

    assert len(coordinator._revisions.list_for_document("doc-1")) == 1


# ============================================================
# END: Create
# ============================================================

# ============================================================
# BEGIN: Update
# ============================================================

def test_update_advances_the_current_state_and_appends_one_revision() -> None:
    coordinator = make_coordinator()
    create_current, _ = coordinator.create(
        sample_record(title="Before", content="<p>first</p>"),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )

    updated, revision = coordinator.update(
        replace(create_current, title="After", content="<p>second</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )

    assert updated.title == "After"
    assert updated.content == "<p>second</p>"
    assert updated.created_at == create_current.created_at
    assert coordinator._documents.get("doc-1") == updated

    assert revision.revision_number == 2
    assert revision.title == "After"
    assert revision.content == "<p>second</p>"
    assert revision.created_at == NEXT_STAMP
    assert coordinator._revisions.get_latest("doc-1") is revision


def test_combined_title_and_content_save_stays_one_revision() -> None:
    coordinator = make_coordinator()
    create_current, _ = coordinator.create(
        sample_record(title="Old", content="<p>first</p>"),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )

    updated, revision = coordinator.update(
        replace(create_current, title="New Title", content="<p>deep</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )

    assert updated.title == "New Title"
    assert updated.content == "<p>deep</p>"
    assert revision.revision_number == 2
    assert len(coordinator._revisions.list_for_document("doc-1")) == 2


def test_update_preserves_earlier_revisions_untouched() -> None:
    coordinator = make_coordinator()
    create_current, first_revision = coordinator.create(
        sample_record(title="Version One", content="<p>first</p>"),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )

    coordinator.update(
        replace(create_current, title="Version Two", content="<p>second</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )

    assert coordinator._revisions.get("doc-1", "revision-1") == first_revision
    assert first_revision.revision_number == 1
    assert first_revision.title == "Version One"
    assert first_revision.content == "<p>first</p>"

    listed = coordinator._revisions.list_for_document("doc-1")
    assert [record.revision_id for record in listed] == ["revision-1", "revision-2"]


def test_update_on_an_unknown_document_raises_and_leaves_no_trace() -> None:
    coordinator = make_coordinator()

    with pytest.raises(ValueError, match="Document not found"):
        coordinator.update(
            sample_record(),
            revision_id="revision-1",
            revision_created_at=STAMP,
        )

    assert coordinator._documents.list() == []
    assert coordinator._revisions.list_for_document("doc-1") == []


# ============================================================
# END: Update
# ============================================================

# ============================================================
# BEGIN: Atomicity / rollback
# ============================================================

def test_create_rolls_back_when_the_revision_append_fails() -> None:
    coordinator = make_coordinator(revisions=FailingRevisionStore())

    with pytest.raises(ValueError, match="Injected revision append failure"):
        coordinator.create(
            sample_record(),
            revision_id="poison",
            revision_created_at=STAMP,
        )

    assert coordinator._documents.list() == []
    assert coordinator._revisions.list_for_document("doc-1") == []
    assert coordinator._revisions.get_latest("doc-1") is None


def test_update_rolls_back_to_the_prior_state_when_the_append_fails() -> None:
    revisions = FailingRevisionStore()
    revisions.append(
        "doc-1",
        revision_id="revision-1",
        title="Version One",
        content="<p>first</p>",
        content_format=ContentFormat.HTML,
        created_at=STAMP,
    )
    documents = DocumentStore()
    original = documents.create(
        "doc-1",
        title="Version One",
        content="<p>first</p>",
        content_format=ContentFormat.HTML,
    )
    coordinator = InMemoryDocumentWriteCoordinator(documents=documents, revisions=revisions)

    with pytest.raises(ValueError, match="Injected revision append failure"):
        coordinator.update(
            replace(original, title="Version Two", content="<p>second</p>"),
            revision_id="poison",
            revision_created_at=NEXT_STAMP,
        )

    assert documents.get("doc-1") == original
    assert documents.get("doc-1").title == "Version One"  # type: ignore[union-attr]
    assert documents.get("doc-1").content == "<p>first</p>"  # type: ignore[union-attr]

    listed = revisions.list_for_document("doc-1")
    assert [record.revision_id for record in listed] == ["revision-1"]
    assert listed[0].revision_number == 1
    assert listed[0].title == "Version One"


def test_update_rolls_back_history_when_the_append_fails_after_rev_one() -> None:
    """The failing append must not consume a revision number in the snapshot."""
    revisions = FailingRevisionStore()
    revisions.append(
        "doc-1",
        revision_id="revision-1",
        title="Version One",
        content="<p>first</p>",
        content_format=ContentFormat.HTML,
        created_at=STAMP,
    )
    documents = DocumentStore()
    original = documents.create(
        "doc-1",
        title="Version One",
        content="<p>first</p>",
        content_format=ContentFormat.HTML,
    )
    coordinator = InMemoryDocumentWriteCoordinator(documents=documents, revisions=revisions)

    with pytest.raises(ValueError):
        coordinator.update(
            replace(original, title="Version Two", content="<p>second</p>"),
            revision_id="poison",
            revision_created_at=NEXT_STAMP,
        )

    updated, recovered = coordinator.update(
        replace(original, title="Version Two", content="<p>second</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )

    assert updated.title == "Version Two"
    assert recovered.revision_number == 2
    assert len(revisions.list_for_document("doc-1")) == 2


def test_a_failed_write_leaves_the_duplicate_protection_healthy() -> None:
    coordinator = make_coordinator()
    coordinator.create(sample_record(), revision_id="revision-1", revision_created_at=STAMP)

    with pytest.raises(ValueError, match="already exists"):
        coordinator.create(
            sample_record(title="Intruder"),
            revision_id="revision-1",
            revision_created_at=STAMP,
        )

    coordinator.update(
        replace(coordinator._documents.get("doc-1"), title="After", content="<p>two</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )
    assert coordinator._revisions.get("doc-1", "revision-2").revision_number == 2  # type: ignore[union-attr]


# ============================================================
# END: Atomicity / rollback
# ============================================================

# ============================================================
# BEGIN: Composition
# ============================================================

def test_coordinator_is_constructed_with_explicit_stores() -> None:
    """The composition passes stores in; the coordinator never mints its own."""
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    coordinator = InMemoryDocumentWriteCoordinator(documents=documents, revisions=revisions)

    assert coordinator._documents is documents
    assert coordinator._revisions is revisions


# ============================================================
# END: Composition
# ============================================================