"""DocumentRepository/DocumentStore tests (Step 4.5).

Prove the document repository port and its in-memory store:

* records are frozen, immutable snapshots;
* duplicate ``create`` is rejected as a ``ValueError``;
* title/content updates refresh ``updated_at`` but preserve ``created_at``;
* unknown-document operations return ``None`` without raising;
* listing preserves stable insertion order;
* the store keeps working copies isolated from callers.
"""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from ava.contracts.documents import ContentFormat
from ava.repositories import (
    DocumentRecord,
    DocumentRepository,
)
from ava.services.document_store import DocumentStore

# ============================================================
# BEGIN: Fixtures
# ============================================================


def make_store() -> DocumentStore:
    """Create a fresh in-memory document store."""
    return DocumentStore()


def sample_record(
    document_id: str = "doc-1",
    *,
    title: str = "Untitled Document",
    content: str = "<p>body</p>",
) -> DocumentRecord:
    """Create a sample document record for store assertions."""
    now = datetime.now(UTC)
    return DocumentRecord(
        document_id=document_id,
        title=title,
        content=content,
        content_format=ContentFormat.HTML,
        created_at=now,
        updated_at=now,
    )


# ============================================================
# END: Fixtures
# ============================================================


# ============================================================
# BEGIN: Record shape
# ============================================================


def test_document_record_is_a_frozen_snapshot() -> None:
    """Records are immutable; edits are detected at the store boundary."""
    record = sample_record()

    with pytest.raises(FrozenInstanceError):
        record.title = "changed"  # type: ignore[misc]

    assert record.document_id == "doc-1"
    assert record.title == "Untitled Document"
    assert record.content == "<p>body</p>"
    assert record.content_format == ContentFormat.HTML


def test_document_record_carries_no_revision_fields() -> None:
    """Step 4.5 records have no revision/history vocabulary (Step 4.13)."""
    record = sample_record()
    fields = {field.name for field in record.__class__.__dataclass_fields__.values()}
    assert fields == {
        "document_id",
        "title",
        "content",
        "content_format",
        "created_at",
        "updated_at",
    }


# ============================================================
# END: Record shape
# ============================================================


# ============================================================
# BEGIN: Create
# ============================================================


def test_create_returns_a_record_visible_to_all_reads() -> None:
    store = make_store()
    record = store.create(
        "doc-1",
        title="My Doc",
        content="<p>hello</p>",
        content_format=ContentFormat.HTML,
    )

    assert store.get("doc-1") == record
    assert store.list() == [record]


def test_create_collides_raise_value_error() -> None:
    store = make_store()
    store.create(
        "doc-1",
        title="My Doc",
        content="<p>hello</p>",
        content_format=ContentFormat.HTML,
    )

    with pytest.raises(ValueError, match="already exists"):
        store.create(
            "doc-1",
            title="Other Doc",
            content="<p>other</p>",
            content_format=ContentFormat.HTML,
        )


def test_duplicate_create_does_not_clobber_the_original() -> None:
    store = make_store()
    original = store.create(
        "doc-1",
        title="Original",
        content="<p>original</p>",
        content_format=ContentFormat.HTML,
    )
    with pytest.raises(ValueError):
        store.create(
            "doc-1",
            title="Intruder",
            content="<p>intruder</p>",
            content_format=ContentFormat.HTML,
        )

    assert store.get("doc-1") == original


# ============================================================
# END: Create
# ============================================================


# ============================================================
# BEGIN: Get / List / Clear
# ============================================================


def test_get_returns_none_for_unknown_documents() -> None:
    store = make_store()
    assert store.get("missing") is None


def test_list_preserves_insertion_order() -> None:
    store = make_store()
    first = store.create("a", title="A", content="<p>a</p>", content_format=ContentFormat.HTML)
    second = store.create("b", title="B", content="<p>b</p>", content_format=ContentFormat.HTML)
    third = store.create("c", title="C", content="<p>c</p>", content_format=ContentFormat.HTML)

    assert store.list() == [first, second, third]


def test_list_returns_caller_isolated_copies() -> None:
    """Mutating the returned list must not mutate store state."""
    store = make_store()
    first = store.create("a", title="A", content="<p>a</p>", content_format=ContentFormat.HTML)

    listed = store.list()
    assert listed == [first]
    listed.clear()

    assert store.list() == [first]


def test_listed_records_are_the_store_records() -> None:
    """The store hands out its own (frozen) snapshots, not clones."""
    store = make_store()
    first = store.create("a", title="A", content="<p>a</p>", content_format=ContentFormat.HTML)

    listed = store.list()
    assert listed[0] is first


def test_clear_empties_the_store() -> None:
    store = make_store()
    store.create("a", title="A", content="<p>a</p>", content_format=ContentFormat.HTML)
    store.clear()
    assert store.list() == []


# ============================================================
# END: Get / List / Clear
# ============================================================


# ============================================================
# BEGIN: Updates
# ============================================================


def test_update_title_returns_none_for_unknown_documents() -> None:
    store = make_store()
    assert store.update_title("missing", "New Title") is None


def test_update_content_returns_none_for_unknown_documents() -> None:
    store = make_store()
    assert (
        store.update_content(
            "missing",
            content="<p>new</p>",
            content_format=ContentFormat.HTML,
        )
        is None
    )


def test_update_title_refreshes_updated_at_and_preserves_created_at() -> None:
    store = make_store()
    original = store.create("doc-1", title="Before", content="<p>body</p>", content_format=ContentFormat.HTML)
    first_update = store.update_title("doc-1", "After")

    assert first_update is not None
    assert first_update.title == "After"
    assert first_update.created_at == original.created_at
    assert first_update.content == original.content
    assert first_update.updated_at >= original.updated_at

    second_update = store.update_title("doc-1", "Later")
    assert second_update is not None
    assert second_update.updated_at >= first_update.updated_at


def test_update_content_replaces_content_and_format() -> None:
    store = make_store()
    store.create("doc-1", title="My Doc", content="<p>old</p>", content_format=ContentFormat.HTML)

    updated = store.update_content(
        "doc-1",
        content="<h2>new heading</h2>",
        content_format=ContentFormat.HTML,
    )

    assert updated is not None
    assert updated.document_id == "doc-1"
    assert updated.title == "My Doc"
    assert updated.content == "<h2>new heading</h2>"
    assert updated.content_format == ContentFormat.HTML
    assert updated.created_at <= updated.updated_at


def test_updates_do_not_mutate_the_original_snapshot_passed_out() -> None:
    """Callers holding an old record keep seeing the pre-update snapshot."""
    store = make_store()
    original = store.create("doc-1", title="Before", content="<p>body</p>", content_format=ContentFormat.HTML)

    store.update_title("doc-1", "After")
    store.update_content("doc-1", content="<p>new</p>", content_format=ContentFormat.HTML)

    assert original.title == "Before"
    assert original.content == "<p>body</p>"


# ============================================================
# END: Updates
# ============================================================


# ============================================================
# BEGIN: Port typing
# ============================================================


def test_document_store_conforms_to_the_document_port() -> None:
    """The store satisfies the whole DocumentRepository contract."""
    assert isinstance(DocumentStore(), DocumentRepository)


def test_document_store_methods_accept_only_record_types() -> None:
    """The store's public surface takes only contract-typed values."""
    store = make_store()

    record = store.create(
        "doc-2",
        title="My Doc",
        content="<p>body</p>",
        content_format=ContentFormat.HTML,
    )
    assert record.content_format is ContentFormat.HTML


# ============================================================
# END: Port typing
# ============================================================