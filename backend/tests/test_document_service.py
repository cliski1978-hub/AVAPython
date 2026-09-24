"""DocumentService behavior tests (Step 4.5, revisions in Step 4.13.D).

Prove the document service owns the domain invariants:

* identifier generation (service-owned UUIDs, never client-supplied);
* timezone-aware UTC timestamps produced by the service;
* the default title resolution for omitted/blank titles;
* the HTML content policy is enforced before content becomes trusted;
* coordinator duplicate collisions map onto explicit domain errors;
* unknown-document operations return ``None`` without raising;
* the service never manipulates editor objects, only strings.

Step 4.13.D adds the write-coordinator integration proofs: every service
create appends revision 1, every successful update appends exactly one next
revision, combined title+content updates stay a single revision, and a failed
revision append rolls the whole service write back.
"""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from ava.contracts.documents import (
    ContentFormat,
    DocumentListResponse,
)
from ava.repositories import DocumentRecord
from ava.services.document_revision_store import InMemoryDocumentRevisionStore
from ava.services.document_service import (
    DEFAULT_DOCUMENT_TITLE,
    DocumentService,
    DuplicateDocumentError,
    InvalidDocumentContentError,
)
from ava.services.document_store import DocumentStore
from ava.services.document_write_coordinator import (
    DocumentWriteCoordinator,
    InMemoryDocumentWriteCoordinator,
)

# ============================================================
# BEGIN: Fixtures
# ============================================================


def make_service() -> DocumentService:
    """Create a service over fresh shared in-memory stores and a coordinator."""
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    return DocumentService(
        document_repository=documents,
        document_revision_repository=revisions,
        document_write_coordinator=InMemoryDocumentWriteCoordinator(
            documents=documents,
            revisions=revisions,
        ),
    )


def make_service_with_coordinator(
    *,
    documents: DocumentStore,
    revisions: InMemoryDocumentRevisionStore,
) -> DocumentService:
    """Create a service sharing explicit stores with its coordinator."""
    return DocumentService(
        document_repository=documents,
        document_revision_repository=revisions,
        document_write_coordinator=InMemoryDocumentWriteCoordinator(
            documents=documents,
            revisions=revisions,
        ),
    )


class _FailingCreateCoordinator:
    """Write-coordinator double whose create always reports a duplicate id."""

    def create(
        self,
        document: DocumentRecord,
        *,
        revision_id: str,
        revision_created_at: datetime,
    ) -> tuple[DocumentRecord, object]:
        raise ValueError(f"Document already exists: {document.document_id}")

    def update(
        self,
        document: DocumentRecord,
        *,
        revision_id: str,
        revision_created_at: datetime,
    ) -> tuple[DocumentRecord, object]:
        raise ValueError(f"Document already exists: {document.document_id}")


# ============================================================
# END: Fixtures
# ============================================================


# ============================================================
# BEGIN: Create Document
# ============================================================


def test_create_document_assigns_default_title_and_default_format() -> None:
    service = make_service()
    document = service.create_document(content="<p>body</p>")

    assert document.title == DEFAULT_DOCUMENT_TITLE
    assert document.content_format == ContentFormat.HTML
    assert document.created_at == document.updated_at


def test_create_document_accepts_explicit_title_and_trims_blanks() -> None:
    service = make_service()

    titled = service.create_document(title="  My Doc  ", content="<p>body</p>")
    assert titled.title == "My Doc"

    blank = service.create_document(title="   ", content="<p>body</p>")
    assert blank.title == DEFAULT_DOCUMENT_TITLE

    empty = service.create_document(title="", content="<p>body</p>")
    assert empty.title == DEFAULT_DOCUMENT_TITLE


def test_create_document_mints_a_valid_ava_owned_uuid_identifier() -> None:
    service = make_service()
    document = service.create_document(content="<p>body</p>")

    assert UUID(document.document_id)
    assert str(UUID(document.document_id)) == document.document_id


def test_create_document_produces_utc_timestamps_consistent_with_now() -> None:
    service = make_service()
    before = datetime.now(UTC)
    document = service.create_document(content="<p>body</p>")
    after = datetime.now(UTC)

    assert before <= document.created_at <= after
    assert before <= document.updated_at <= after


def test_create_document_rejects_policy_violating_content() -> None:
    service = make_service()
    with pytest.raises(InvalidDocumentContentError):
        service.create_document(content="<script>alert(1)</script>")
    with pytest.raises(InvalidDocumentContentError):
        service.create_document(content="<p onclick='x()'>y</p>")
    with pytest.raises(InvalidDocumentContentError):
        service.create_document(content="")


def test_create_document_passes_canonical_editor_content() -> None:
    service = make_service()
    content = "<h1>AVA Document Workspace</h1><p>This is an AVA document.</p>"
    document = service.create_document(content=content)
    assert document.content == content


def test_create_document_maps_repository_collision_to_domain_error() -> None:
    service = DocumentService(
        document_repository=DocumentStore(),
        document_revision_repository=InMemoryDocumentRevisionStore(),
        document_write_coordinator=_FailingCreateCoordinator(),
    )
    with pytest.raises(DuplicateDocumentError):
        service.create_document(content="<p>body</p>")


# ============================================================
# END: Create Document
# ============================================================


# ============================================================
# BEGIN: Get / List
# ============================================================


def test_get_document_returns_none_for_unknown_documents() -> None:
    service = make_service()
    assert service.get_document("missing") is None


def test_get_document_round_trips_a_created_document() -> None:
    service = make_service()
    created = service.create_document(title="My Doc", content="<p>one</p>")
    fetched = service.get_document(created.document_id)

    assert fetched is not None
    assert fetched == created


def test_list_documents_preserves_insertion_order() -> None:
    service = make_service()
    first = service.create_document(title="A", content="<p>a</p>")
    second = service.create_document(title="B", content="<p>b</p>")
    third = service.create_document(title="C", content="<p>c</p>")

    result: DocumentListResponse = service.list_documents()
    assert [document.document_id for document in result.documents] == [
        first.document_id,
        second.document_id,
        third.document_id,
    ]


# ============================================================
# END: Get / List
# ============================================================


# ============================================================
# BEGIN: Revision History Reads (Step 4.13.E)
# ============================================================


def test_list_revisions_returns_ordered_history_after_writes() -> None:
    """The write path and the revision read path observe the same history."""
    service = make_service()
    created = service.create_document(title="Before", content="<p>first</p>")
    updated = service.update_document(created.document_id, title="After", content="<p>second</p>")
    assert updated is not None

    history = service.list_revisions(created.document_id)
    assert history is not None
    assert history.document_id == created.document_id
    assert [revision.revision_number for revision in history.revisions] == [1, 2]

    first, second = history.revisions
    assert first.revision_id != second.revision_id
    assert first.title == "Before"
    assert first.content == "<p>first</p>"
    assert second.title == "After"
    assert second.content == "<p>second</p>"


def test_list_revisions_is_revision_number_ascending_not_timestamp_sorted() -> None:
    """Order is the repository's deterministic revision_number ASC sequence."""
    service = make_service()
    created = service.create_document(title="T1", content="<p>a</p>")
    service.update_document(created.document_id, title="T2", content="<p>b</p>")
    service.update_document(created.document_id, title="T3", content="<p>c</p>")

    history = service.list_revisions(created.document_id)
    assert history is not None
    assert [revision.revision_number for revision in history.revisions] == [1, 2, 3]

    timestamps = [revision.created_at for revision in history.revisions]
    assert timestamps == sorted(timestamps)
    # The sequence is what orders the history, not the timestamps alone.
    assert history.revisions[0].revision_number < history.revisions[1].revision_number
    assert history.revisions[1].revision_number < history.revisions[2].revision_number


def test_list_revisions_returns_none_for_unknown_document() -> None:
    """Unknown document → None, which the route normalizes to 404."""
    service = make_service()
    assert service.list_revisions("missing") is None


def test_list_revisions_empty_history_for_known_document() -> None:
    """A known document with no history yields an empty list (≠ unknown → None)."""
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)

    documents.create(
        "legacy",
        title="Legacy",
        content="<p>pre history</p>",
        content_format=ContentFormat.HTML,
    )

    empty = service.list_revisions("legacy")
    assert empty is not None
    assert empty.document_id == "legacy"
    assert empty.revisions == []

    # The known document still lists; the unknown one is None.
    assert service.list_revisions("missing") is None
    assert service.get_document("legacy") is not None


def test_get_revision_returns_exact_revision_snapshot() -> None:
    """get_revision returns the exact revision back, unchanged."""
    service = make_service()
    created = service.create_document(title="My Doc", content="<p>html a</p>")
    updated = service.update_document(created.document_id, title="My Doc", content="<p>html b</p>")
    assert updated is not None

    history = service.list_revisions(created.document_id)
    assert history is not None
    first_id, second_id = (
        history.revisions[0].revision_id,
        history.revisions[1].revision_id,
    )

    first = service.get_revision(created.document_id, first_id)
    second = service.get_revision(created.document_id, second_id)
    assert first is not None
    assert second is not None
    assert first.revision_number == 1
    assert first.title == "My Doc"
    assert first.content == "<p>html a</p>"
    assert first.content_format == ContentFormat.HTML
    assert first.created_at.tzinfo is not None
    # The in-memory store re-stamps current-state rows, so revision snapshots
    # carry the service's own authoritative timestamp; it is aware UTC and
    # monotonic across the sequence.
    assert first.created_at <= second.created_at
    assert second.revision_number == 2
    assert second.content == "<p>html b</p>"


def test_get_revision_returns_none_for_unknown_document_and_unknown_revision() -> None:
    """Unknown document or unknown revision → None (route normalizes to 404)."""
    service = make_service()
    created = service.create_document(content="<p>body</p>")

    assert service.get_revision("missing", "any") is None
    assert service.get_revision(created.document_id, "missing-revision") is None


def test_get_revision_cross_document_lookup_returns_none() -> None:
    """A revision from document A never resolves through document B."""
    service = make_service()
    document_a = service.create_document(title="A", content="<p>from a</p>")
    document_b = service.create_document(title="B", content="<p>from b</p>")

    revision_a = service.get_revision(document_a.document_id, _first_revision_id(service, document_a.document_id))
    assert revision_a is not None
    assert service.get_revision(document_b.document_id, revision_a.revision_id) is None


def _first_revision_id(service: DocumentService, document_id: str) -> str:
    history = service.list_revisions(document_id)
    assert history is not None and history.revisions
    return history.revisions[0].revision_id


def test_revision_history_round_trips_canonical_html_unchanged() -> None:
    """Stored HTML re-serializes byte-exact; reads never re-sanitize."""
    service = make_service()
    original = "<h1>AVA Workspace</h1><p>Canonical <strong>HTML</strong>.</p>"
    created = service.create_document(title="Doc", content=original)
    service.update_document(created.document_id, content=original)

    history = service.list_revisions(created.document_id)
    assert history is not None
    assert [revision.content for revision in history.revisions] == [original, original]


def test_revision_reads_use_the_same_store_the_write_path_writes() -> None:
    """The service read and write dependencies share one revision store."""
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)

    created = service.create_document(content="<p>one</p>")
    service.update_document(created.document_id, content="<p>two</p>")

    via_repository = revisions.list_for_document(created.document_id)
    via_service = service.list_revisions(created.document_id)
    assert via_service is not None
    assert [r.revision_id for r in via_service.revisions] == [
        r.revision_id for r in via_repository
    ]


# ============================================================
# END: Revision History Reads (Step 4.13.E)
# ============================================================


# ============================================================
# BEGIN: Rename / Update Content
# ============================================================


def test_rename_document_returns_none_for_unknown_documents() -> None:
    service = make_service()
    assert service.rename_document("missing", "New Title") is None


def test_rename_document_trims_and_applies_the_new_title() -> None:
    service = make_service()
    created = service.create_document(title="Before", content="<p>body</p>")

    renamed = service.rename_document(created.document_id, "  After  ")
    assert renamed is not None
    assert renamed.title == "After"
    assert renamed.content == created.content
    assert renamed.created_at == created.created_at
    assert renamed.updated_at >= created.updated_at


def test_rename_document_rejects_blank_titles() -> None:
    service = make_service()
    created = service.create_document(title="Before", content="<p>body</p>")

    with pytest.raises(ValueError):
        service.rename_document(created.document_id, "   ")


def test_update_document_content_returns_none_for_unknown_documents() -> None:
    service = make_service()
    assert (
        service.update_document_content("missing", content="<p>new</p>")
        is None
    )


def test_update_content_replaces_content_in_place() -> None:
    service = make_service()
    created = service.create_document(title="My Doc", content="<p>old</p>")

    updated = service.update_document_content(created.document_id, content="<h2>new</h2>")

    assert updated is not None
    assert updated.title == "My Doc"
    assert updated.content == "<h2>new</h2>"
    assert updated.created_at == created.created_at


def test_update_content_unknown_document_wins_over_invalid_content() -> None:
    """Existence is resolved before validation: 404 semantics beat 422."""
    service = make_service()
    assert (
        service.update_document_content("missing", content="<script>alert(1)</script>")
        is None
    )


def test_update_content_rejects_policy_violating_content() -> None:
    service = make_service()
    created = service.create_document(content="<p>safe</p>")

    with pytest.raises(InvalidDocumentContentError):
        service.update_document_content(created.document_id, content="<script>x</script>")
    with pytest.raises(InvalidDocumentContentError):
        service.update_document_content(created.document_id, content="<p onclick='x()'>y</p>")

    untouched = service.get_document(created.document_id)
    assert untouched is not None
    assert untouched.content == "<p>safe</p>"


# ============================================================
# END: Rename / Update Content
# ============================================================


# ============================================================
# BEGIN: Domain Boundaries
# ============================================================


def test_document_service_never_sees_editor_objects() -> None:
    """The service only ever receives and returns strings, never editor nodes."""

    class _RecordingCoordinator(DocumentWriteCoordinator):
        """Double that records the content types handed to the coordinator."""

        received_types: list[type] = []

        def __init__(
            self,
            *,
            documents: DocumentStore,
            revisions: InMemoryDocumentRevisionStore,
        ) -> None:
            self._inner = InMemoryDocumentWriteCoordinator(documents=documents, revisions=revisions)

        def create(
            self,
            document: DocumentRecord,
            *,
            revision_id: str,
            revision_created_at: datetime,
        ) -> tuple[DocumentRecord, object]:
            _RecordingCoordinator.received_types.append(type(document.content))
            return self._inner.create(
                document,
                revision_id=revision_id,
                revision_created_at=revision_created_at,
            )

        def update(
            self,
            document: DocumentRecord,
            *,
            revision_id: str,
            revision_created_at: datetime,
        ) -> tuple[DocumentRecord, object]:
            _RecordingCoordinator.received_types.append(type(document.content))
            return self._inner.update(
                document,
                revision_id=revision_id,
                revision_created_at=revision_created_at,
            )

    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = DocumentService(
        document_repository=documents,
        document_revision_repository=revisions,
        document_write_coordinator=_RecordingCoordinator(documents=documents, revisions=revisions),
    )
    service.create_document(content="<p>body</p>")
    created = service.list_documents().documents[0]
    service.update_document_content(created.document_id, content="<p>new</p>")
    assert all(item is str for item in _RecordingCoordinator.received_types)


# ============================================================
# END: Domain Boundaries
# ============================================================


# ============================================================
# BEGIN: Write Coordinator Integration (Step 4.13.D)
# ============================================================


class _AlwaysFailingRevisionStore(InMemoryDocumentRevisionStore):
    """Test double: every revision append fails after the current-state write."""

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
        raise ValueError("Injected revision append failure")


class _CapturingCoordinator:
    """Double that records what the service hands to the coordinator."""

    def __init__(self, inner: DocumentWriteCoordinator) -> None:
        self._inner = inner
        self.created: list[tuple[DocumentRecord, str, datetime]] = []
        self.updated: list[tuple[DocumentRecord, str, datetime]] = []

    def create(
        self,
        document: DocumentRecord,
        *,
        revision_id: str,
        revision_created_at: datetime,
    ) -> tuple[DocumentRecord, object]:
        self.created.append((document, revision_id, revision_created_at))
        return self._inner.create(
            document,
            revision_id=revision_id,
            revision_created_at=revision_created_at,
        )

    def update(
        self,
        document: DocumentRecord,
        *,
        revision_id: str,
        revision_created_at: datetime,
    ) -> tuple[DocumentRecord, object]:
        self.updated.append((document, revision_id, revision_created_at))
        return self._inner.update(
            document,
            revision_id=revision_id,
            revision_created_at=revision_created_at,
        )


def test_create_appends_revision_one_that_matches_the_created_document() -> None:
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)

    created = service.create_document(title="My Doc", content="<p>hello</p>")

    listed = revisions.list_for_document(created.document_id)
    assert len(listed) == 1
    revision = listed[0]
    assert revision.revision_number == 1
    assert revision.document_id == created.document_id
    assert revision.title == created.title
    assert revision.content == created.content
    assert revision.content_format == created.content_format


def test_update_appends_exactly_one_next_revision() -> None:
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)
    created = service.create_document(title="Before", content="<p>first</p>")

    updated = service.update_document(
        created.document_id, title="After", content="<p>second</p>"
    )
    assert updated is not None

    listed = revisions.list_for_document(created.document_id)
    assert [revision.revision_number for revision in listed] == [1, 2]
    assert listed[-1].title == "After"
    assert listed[-1].content == "<p>second</p>"
    assert listed[0].title == "Before"
    assert listed[0].content == "<p>first</p>"


def test_combined_title_and_content_update_produces_only_revision_two() -> None:
    """A combined title+content save is one atomic write, never two revisions."""
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)
    created = service.create_document(title="Old", content="<p>first</p>")

    updated = service.update_document(
        created.document_id, title="New Title", content="<p>deep</p>"
    )
    assert updated is not None

    listed = revisions.list_for_document(created.document_id)
    assert len(listed) == 2
    assert [revision.revision_number for revision in listed] == [1, 2]
    assert listed[1].title == "New Title"
    assert listed[1].content == "<p>deep</p>"


def test_revision_snapshot_matches_the_final_current_state() -> None:
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)
    created = service.create_document(title="Before", content="<p>old</p>")
    updated = service.update_document(created.document_id, title="After", content="<p>new</p>")
    assert updated is not None

    latest = revisions.get_latest(created.document_id)
    assert latest is not None
    assert (latest.title, latest.content, latest.content_format) == (
        updated.title,
        updated.content,
        updated.content_format,
    )
    assert created.created_at == updated.created_at


def test_each_successful_update_field_combination_appends_exactly_one_revision() -> None:
    """Every successful PATCH combination yields revision count N → N + 1."""
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)
    created = service.create_document(title="Start", content="<p>base</p>")
    document_id = created.document_id

    def revision_count() -> int:
        return len(revisions.list_for_document(document_id))

    assert revision_count() == 1
    service.update_document(document_id, title="T2")
    assert revision_count() == 2
    service.update_document(document_id, content="<p>c2</p>")
    assert revision_count() == 3
    service.update_document(
        document_id, title="T3", content="<p>c3</p>", content_format=ContentFormat.HTML
    )
    assert revision_count() == 4
    service.update_document_content(document_id, content="<p>c4</p>")
    assert revision_count() == 5
    service.rename_document(document_id, "T5")
    assert revision_count() == 6


def test_a_no_op_value_patch_still_appends_exactly_one_revision() -> None:
    """A successful PATCH represents a durable save: one revision even if unchanged.

    The pre-4.13 route always performed writes for any successful request, so a
    request whose values equal the current values still records a save.
    """
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)
    created = service.create_document(title="Same", content="<p>same</p>")

    updated = service.update_document(created.document_id, title="Same", content="<p>same</p>")
    assert updated is not None

    listed = revisions.list_for_document(created.document_id)
    assert len(listed) == 2
    assert listed[1].title == "Same"
    assert listed[1].content == "<p>same</p>"
    assert listed[1].revision_number == 2


def test_create_hands_the_coordinator_prepared_identity_and_timestamps() -> None:
    """The service mints document_id/revision_id and one coherent timestamp."""
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    inner = InMemoryDocumentWriteCoordinator(documents=documents, revisions=revisions)
    capturing = _CapturingCoordinator(inner)
    service = DocumentService(
        document_repository=documents,
        document_revision_repository=revisions,
        document_write_coordinator=capturing,
    )

    created = service.create_document(title="My Doc", content="<p>body</p>")

    assert len(capturing.created) == 1
    prepared, revision_id, revision_created_at = capturing.created[0]
    assert prepared.document_id == created.document_id
    assert prepared.document_id == str(UUID(prepared.document_id))
    assert revision_id == str(UUID(revision_id))
    assert prepared.title == "My Doc"
    assert prepared.content == "<p>body</p>"
    assert prepared.created_at == prepared.updated_at == revision_created_at
    assert revision_created_at.tzinfo is not None
    assert created.created_at == created.updated_at
    assert created.created_at.tzinfo is not None


def test_update_hands_the_coordinator_one_coherent_timestamp() -> None:
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    inner = InMemoryDocumentWriteCoordinator(documents=documents, revisions=revisions)
    capturing = _CapturingCoordinator(inner)
    service = DocumentService(
        document_repository=documents,
        document_revision_repository=revisions,
        document_write_coordinator=capturing,
    )
    created = service.create_document(title="Before", content="<p>old</p>")

    updated = service.update_document(created.document_id, title="After", content="<p>new</p>")
    assert updated is not None

    assert len(capturing.updated) == 1
    prepared, revision_id, revision_created_at = capturing.updated[0]
    assert revision_id == str(UUID(revision_id))
    assert prepared.document_id == created.document_id
    assert prepared.created_at == created.created_at
    assert prepared.updated_at == revision_created_at
    assert revision_created_at.tzinfo is not None


def test_invalid_update_leaves_current_state_and_history_untouched() -> None:
    """Validation runs before the atomic write: failures append nothing."""
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)
    created = service.create_document(title="Safe", content="<p>safe</p>")

    with pytest.raises(InvalidDocumentContentError):
        service.update_document(created.document_id, content="<script>alert(1)</script>")
    with pytest.raises(InvalidDocumentContentError):
        service.update_document_content(
            created.document_id,
            content="<p>new</p>",
            content_format=cast(ContentFormat, "markdown"),
        )
    with pytest.raises(ValueError, match="title must not be blank"):
        service.update_document(created.document_id, title="   ")

    current = service.get_document(created.document_id)
    assert current == created
    assert [revision.revision_number for revision in revisions.list_for_document(created.document_id)] == [1]


def test_create_rolls_back_when_the_revision_append_fails() -> None:
    documents = DocumentStore()
    failing = _AlwaysFailingRevisionStore()
    service = DocumentService(
        document_repository=documents,
        document_revision_repository=failing,
        document_write_coordinator=InMemoryDocumentWriteCoordinator(
            documents=documents,
            revisions=failing,
        ),
    )

    with pytest.raises(DuplicateDocumentError):
        service.create_document(content="<p>body</p>")

    assert documents.list() == []
    assert failing.list_for_document("none") == []


def test_update_rolls_back_to_the_prior_state_when_the_append_fails() -> None:
    documents = DocumentStore()
    revisions = InMemoryDocumentRevisionStore()
    service = make_service_with_coordinator(documents=documents, revisions=revisions)
    created = service.create_document(title="State A", content="<p>first</p>")

    failing = _AlwaysFailingRevisionStore()
    failing_service = DocumentService(
        document_repository=documents,
        document_revision_repository=revisions,
        document_write_coordinator=InMemoryDocumentWriteCoordinator(
            documents=documents,
            revisions=failing,
        ),
    )
    with pytest.raises(ValueError, match="Injected revision append failure"):
        failing_service.update_document(created.document_id, title="State B", content="<p>second</p>")

    current = service.get_document(created.document_id)
    assert current == created
    assert current.title == "State A"  # type: ignore[union-attr]
    assert current.content == "<p>first</p>"  # type: ignore[union-attr]
    assert [revision.revision_number for revision in revisions.list_for_document(created.document_id)] == [1]
    assert [revision.title for revision in revisions.list_for_document(created.document_id)] == ["State A"]

    recovered = service.update_document(created.document_id, title="State B", content="<p>second</p>")
    assert recovered is not None
    assert recovered.title == "State B"
    assert [revision.revision_number for revision in revisions.list_for_document(created.document_id)] == [1, 2]


def test_update_document_unknown_wins_over_invalid_payload() -> None:
    """Existence resolves first: unknown document yields None before validation."""
    service = make_service()
    assert (
        service.update_document("missing", content="<script>alert(1)</script>")
        is None
    )
    assert service.update_document("missing", title="   ") is None


# ============================================================
# END: Write Coordinator Integration (Step 4.13.D)
# ============================================================