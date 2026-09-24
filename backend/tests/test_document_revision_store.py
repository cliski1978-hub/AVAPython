"""InMemoryDocumentRevisionStore tests (Step 4.13.B).

Prove the in-memory immutable revision store:

* revision numbering starts at 1 per document and increments monotonically;
* ordering is deterministic revision-number ascending;
* exact and latest lookups resolve only within the owning document;
* duplicate ``revision_id`` (same document *and* across documents) is a
  ``ValueError``; history stays untouched after the reject;
* appended records are immutable AND returned callers cannot corrupt ordering;
* ``clear`` forgets everything, restarting numbering and letting ids reuse;
* ``snapshot``/``restore`` round-trips the exact state (coordinator support).

Focused in-memory state only: no database, no service, no routes (Step 4.13.C+).
"""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from ava.contracts.documents import ContentFormat
from ava.repositories import DocumentRevisionRepository
from ava.services.document_revision_store import InMemoryDocumentRevisionStore

# ============================================================
# BEGIN: Fixtures
# ============================================================

STAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def make_store() -> InMemoryDocumentRevisionStore:
    """Create a fresh in-memory document revision store."""
    return InMemoryDocumentRevisionStore()


def append_revision(
    store: InMemoryDocumentRevisionStore,
    document_id: str = "doc-1",
    revision_id: str = "revision-1",
    title: str = "Untitled Document",
    content: str = "<p>body</p>",
) -> None:
    """Append one revision through the public port surface."""
    store.append(
        document_id,
        revision_id=revision_id,
        title=title,
        content=content,
        content_format=ContentFormat.HTML,
        created_at=STAMP,
    )


# ============================================================
# END: Fixtures
# ============================================================

# ============================================================
# BEGIN: Port conformance
# ============================================================

def test_store_conforms_to_the_revision_port() -> None:
    """The store satisfies the whole DocumentRevisionRepository contract."""
    assert isinstance(make_store(), DocumentRevisionRepository)


# ============================================================
# END: Port conformance
# ============================================================

# ============================================================
# BEGIN: Numbering
# ============================================================

def test_revision_numbering_starts_at_one_and_increments() -> None:
    store = make_store()
    first = store.append(
        "doc-1",
        revision_id="revision-1",
        title="Untitled Document",
        content="<p>one</p>",
        content_format=ContentFormat.HTML,
        created_at=STAMP,
    )
    second = store.append(
        "doc-1",
        revision_id="revision-2",
        title="Untitled Document",
        content="<p>two</p>",
        content_format=ContentFormat.HTML,
        created_at=STAMP,
    )
    third = store.append(
        "doc-1",
        revision_id="revision-3",
        title="Untitled Document",
        content="<p>three</p>",
        content_format=ContentFormat.HTML,
        created_at=STAMP,
    )

    assert [r.revision_number for r in store.list_for_document("doc-1")] == [1, 2, 3]
    assert first.revision_number == 1
    assert second.revision_number == 2
    assert third.revision_number == 3


def test_numbering_is_per_document() -> None:
    store = make_store()
    append_revision(store, "doc-a", "rev-a1")
    append_revision(store, "doc-b", "rev-b1")
    append_revision(store, "doc-a", "rev-a2")

    assert store.get("doc-a", "rev-a1").revision_number == 1  # type: ignore[union-attr]
    assert store.get("doc-a", "rev-a2").revision_number == 2  # type: ignore[union-attr]
    assert store.get("doc-b", "rev-b1").revision_number == 1  # type: ignore[union-attr]


# ============================================================
# END: Numbering
# ============================================================

# ============================================================
# BEGIN: Ordering
# ============================================================

def test_list_orders_by_revision_number_ascending() -> None:
    store = make_store()
    append_revision(store, "doc-1", "revision-1", content="<p>first</p>")
    append_revision(store, "doc-1", "revision-2", content="<p>second</p>")
    append_revision(store, "doc-1", "revision-3", content="<p>third</p>")

    listed = store.list_for_document("doc-1")
    assert [r.revision_id for r in listed] == ["revision-1", "revision-2", "revision-3"]
    assert [r.content for r in listed] == ["<p>first</p>", "<p>second</p>", "<p>third</p>"]


def test_list_returns_an_empty_collection_for_unknown_documents() -> None:
    assert make_store().list_for_document("missing") == []


def test_list_returns_caller_isolated_copies() -> None:
    store = make_store()
    append_revision(store, "doc-1", "revision-1")

    listed = store.list_for_document("doc-1")
    assert listed == [store.get("doc-1", "revision-1")]
    listed.clear()

    assert len(store.list_for_document("doc-1")) == 1


# ============================================================
# END: Ordering
# ============================================================

# ============================================================
# BEGIN: Lookups
# ============================================================

def test_get_resolves_the_exact_revision() -> None:
    store = make_store()
    append_revision(store, "doc-1", "revision-1", title="One")
    append_revision(store, "doc-1", "revision-2", title="Two")

    assert store.get("doc-1", "revision-1").title == "One"  # type: ignore[union-attr]
    assert store.get("doc-1", "revision-2").title == "Two"  # type: ignore[union-attr]


def test_get_returns_none_for_unknown_document_or_revision() -> None:
    store = make_store()
    append_revision(store, "doc-1", "revision-1")

    assert store.get("missing", "revision-1") is None
    assert store.get("doc-1", "ghost") is None


def test_get_never_resolves_across_documents() -> None:
    """A revision id from another document must not resolve through this one."""
    store = make_store()
    append_revision(store, "doc-a", "shared-revision")
    append_revision(store, "doc-b", "other-revision")

    assert store.get("doc-a", "other-revision") is None
    assert store.get("doc-b", "shared-revision") is None
    assert store.get("doc-a", "shared-revision") is not None


def test_get_latest_returns_the_highest_numbered_revision() -> None:
    store = make_store()
    append_revision(store, "doc-1", "revision-1", content="<p>one</p>")
    latest = store.append(
        "doc-1",
        revision_id="revision-2",
        title="Untitled Document",
        content="<p>two</p>",
        content_format=ContentFormat.HTML,
        created_at=STAMP,
    )

    assert store.get_latest("doc-1") is latest


def test_get_latest_returns_none_for_unknown_documents() -> None:
    assert make_store().get_latest("missing") is None


# ============================================================
# END: Lookups
# ============================================================

# ============================================================
# BEGIN: Duplicate identity
# ============================================================

def test_same_document_duplicate_revision_id_is_rejected() -> None:
    store = make_store()
    append_revision(store, "doc-1", "revision-1")

    with pytest.raises(ValueError, match="already exists"):
        append_revision(store, "doc-1", "revision-1")


def test_cross_document_duplicate_revision_id_is_rejected() -> None:
    store = make_store()
    append_revision(store, "doc-a", "shared-revision")
    append_revision(store, "doc-b", "other-revision")

    with pytest.raises(ValueError, match="already exists"):
        append_revision(store, "doc-b", "shared-revision")


def test_duplicate_rejection_leaves_history_untouched() -> None:
    store = make_store()
    append_revision(store, "doc-a", "revision-1", content="<p>one</p>")
    append_revision(store, "doc-b", "other-revision", content="<p>other</p>")

    with pytest.raises(ValueError):
        append_revision(store, "doc-b", "revision-1")

    assert [r.revision_id for r in store.list_for_document("doc-a")] == ["revision-1"]
    assert [r.revision_id for r in store.list_for_document("doc-b")] == ["other-revision"]
    assert store.get_latest("doc-b").revision_number == 1  # type: ignore[union-attr]


# ============================================================
# END: Duplicate identity
# ============================================================

# ============================================================
# BEGIN: Immutability
# ============================================================

def test_appended_records_are_immutable_snapshots() -> None:
    store = make_store()
    record = store.append(
        "doc-1",
        revision_id="revision-1",
        title="Untitled Document",
        content="<p>body</p>",
        content_format=ContentFormat.HTML,
        created_at=STAMP,
    )

    with pytest.raises(FrozenInstanceError):
        record.title = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.content = "<p>changed</p>"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.revision_number = 99  # type: ignore[misc]

    assert store.get_latest("doc-1") == record


# ============================================================
# END: Immutability
# ============================================================

# ============================================================
# BEGIN: Reset
# ============================================================

def test_clear_restarts_numbering_and_reuses_ids() -> None:
    store = make_store()
    append_revision(store, "doc-1", "revision-1")
    append_revision(store, "doc-1", "revision-2")

    store.clear()

    assert store.list_for_document("doc-1") == []
    assert store.get_latest("doc-1") is None

    revision = store.append(
        "doc-1",
        revision_id="revision-1",
        title="Untitled Document",
        content="<p>fresh</p>",
        content_format=ContentFormat.HTML,
        created_at=STAMP,
    )
    assert revision.revision_number == 1


# ============================================================
# END: Reset
# ============================================================

# ============================================================
# BEGIN: Snapshot / restore (coordinator support)
# ============================================================

def test_snapshot_restore_round_trips_the_exact_state() -> None:
    store = make_store()
    append_revision(store, "doc-a", "revision-1", title="One")
    append_revision(store, "doc-b", "revision-b-1", title="Other")
    append_revision(store, "doc-a", "revision-2", title="Two")

    snapshot = store.snapshot()

    store.clear()
    append_revision(store, "doc-c", "revision-c-1")
    store.restore(snapshot)

    assert [r.revision_id for r in store.list_for_document("doc-a")] == [
        "revision-1",
        "revision-2",
    ]
    assert [r.revision_id for r in store.list_for_document("doc-b")] == ["revision-b-1"]
    assert store.list_for_document("doc-c") == []


def test_restore_rebuilds_duplicate_protection() -> None:
    store = make_store()
    append_revision(store, "doc-a", "shared", title="One")
    snapshot = store.snapshot()

    store.clear()
    store.restore(snapshot)

    with pytest.raises(ValueError, match="already exists"):
        append_revision(store, "doc-b", "shared")


# ============================================================
# END: Snapshot / restore (coordinator support)
# ============================================================