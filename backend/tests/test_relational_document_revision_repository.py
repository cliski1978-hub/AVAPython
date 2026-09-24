"""Relational document revision repository tests (Step 4.13.C).

Mirror the in-memory ``InMemoryDocumentRevisionStore`` semantics against the
SQLite-backed ``RelationalDocumentRevisionRepository``: externally numbered
append-only snapshots (``revision_number`` assigned per document inside a
transactional MAX+1, never caller-supplied), globally-unique ``revision_id``
rejected as ``ValueError``, deterministic revision-number-ascending listings,
document-scoped lookups, aware-UTC timestamp round-tripping, and durability of
immutable history across dispose/reopen.
"""

from datetime import UTC, datetime

import pytest

from ava.contracts.documents import ContentFormat
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import RelationalDocumentRevisionRepository
from ava.repositories import DocumentRevisionRepository

STAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def repository() -> tuple[RelationalDocumentRevisionRepository, SqliteDatabase]:
    database = SqliteDatabase(":memory:")
    yield RelationalDocumentRevisionRepository(database=database), database
    database.dispose()


# ============================================================
# BEGIN: Port conformance
# ============================================================


def test_adapters_conform_to_the_revision_port() -> None:
    assert issubclass(RelationalDocumentRevisionRepository, DocumentRevisionRepository)


# ============================================================
# END: Port conformance
# ============================================================


# ============================================================
# BEGIN: Append / list / get semantics
# ============================================================


def test_append_numbers_revisions_per_document(
    repository: tuple[RelationalDocumentRevisionRepository, SqliteDatabase],
) -> None:
    revision_repository, _ = repository
    first = revision_repository.append(
        "doc-1", revision_id="revision-1", title="T", content="<p>one</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )
    second = revision_repository.append(
        "doc-1", revision_id="revision-2", title="T", content="<p>two</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )
    third = revision_repository.append(
        "doc-1", revision_id="revision-3", title="T", content="<p>three</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )

    assert first.revision_number == 1
    assert second.revision_number == 2
    assert third.revision_number == 3


def test_list_for_document_orders_by_revision_number_ascending(
    repository: tuple[RelationalDocumentRevisionRepository, SqliteDatabase],
) -> None:
    revision_repository, _ = repository
    for revision_id in ("revision-1", "revision-2", "revision-3"):
        revision_repository.append(
            "doc-1", revision_id=revision_id, title="T", content="<p>x</p>",
            content_format=ContentFormat.HTML, created_at=STAMP,
        )
    listed = revision_repository.list_for_document("doc-1")
    assert [record.revision_id for record in listed] == ["revision-1", "revision-2", "revision-3"]
    assert [record.revision_number for record in listed] == [1, 2, 3]


def test_list_for_document_unknown_is_empty(
    repository: tuple[RelationalDocumentRevisionRepository, SqliteDatabase],
) -> None:
    revision_repository, _ = repository
    assert revision_repository.list_for_document("ghost") == []


def test_get_resolves_only_through_the_owning_document(
    repository: tuple[RelationalDocumentRevisionRepository, SqliteDatabase],
) -> None:
    revision_repository, _ = repository
    revision_repository.append(
        "doc-1", revision_id="revision-1", title="T", content="<p>one</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )
    revision_repository.append(
        "doc-2", revision_id="revision-2", title="T", content="<p>two</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )

    assert revision_repository.get("doc-1", "revision-1") is not None
    assert revision_repository.get("doc-1", "revision-2") is None
    assert revision_repository.get("doc-2", "revision-1") is None
    assert revision_repository.get("ghost", "revision-1") is None


def test_get_latest_returns_the_highest_numbered_revision(
    repository: tuple[RelationalDocumentRevisionRepository, SqliteDatabase],
) -> None:
    revision_repository, _ = repository
    assert revision_repository.get_latest("doc-1") is None
    revision_repository.append(
        "doc-1", revision_id="revision-1", title="T", content="<p>one</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )
    revision_repository.append(
        "doc-1", revision_id="revision-2", title="T", content="<p>two</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )
    latest = revision_repository.get_latest("doc-1")
    assert latest is not None
    assert latest.revision_id == "revision-2"
    assert latest.revision_number == 2


# ============================================================
# END: Append / list / get semantics
# ============================================================


# ============================================================
# BEGIN: Duplicate and identity semantics
# ============================================================


def test_duplicate_revision_id_raises_value_error(
    repository: tuple[RelationalDocumentRevisionRepository, SqliteDatabase],
) -> None:
    revision_repository, _ = repository
    revision_repository.append(
        "doc-1", revision_id="revision-1", title="T", content="<p>one</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )
    with pytest.raises(ValueError, match="Revision already exists: revision-1"):
        revision_repository.append(
            "doc-1", revision_id="revision-1", title="T", content="<p>two</p>",
            content_format=ContentFormat.HTML, created_at=STAMP,
        )


def test_revision_id_is_globally_unique_across_documents(
    repository: tuple[RelationalDocumentRevisionRepository, SqliteDatabase],
) -> None:
    revision_repository, _ = repository
    revision_repository.append(
        "doc-1", revision_id="revision-1", title="T", content="<p>one</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )
    with pytest.raises(ValueError, match="Revision already exists: revision-1"):
        revision_repository.append(
            "doc-2", revision_id="revision-1", title="T", content="<p>two</p>",
            content_format=ContentFormat.HTML, created_at=STAMP,
        )


def test_append_snapshot_fields_round_trip(
    repository: tuple[RelationalDocumentRevisionRepository, SqliteDatabase],
) -> None:
    revision_repository, _ = repository
    created_at = datetime(2026, 4, 5, 6, 7, 8, tzinfo=UTC)
    revision_repository.append(
        "doc-1",
        revision_id="revision-1",
        title="Planning Notes",
        content="<h2>Plan</h2><p>body</p>",
        content_format=ContentFormat.HTML,
        created_at=created_at,
    )
    stored = revision_repository.get("doc-1", "revision-1")
    assert stored == revision_repository.list_for_document("doc-1")[0]
    assert stored is not None
    assert stored.title == "Planning Notes"
    assert stored.content == "<h2>Plan</h2><p>body</p>"
    assert stored.content_format == ContentFormat.HTML
    assert stored.created_at == created_at
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset() == UTC.utcoffset(None)


# ============================================================
# END: Duplicate and identity semantics
# ============================================================


# ============================================================
# BEGIN: Durability across reopen
# ============================================================


def test_revisions_survive_dispose_and_reopen(tmp_path) -> None:
    """Immutable revision history persists through a full database close/reopen."""
    database_url = str(tmp_path / "ava.sqlite3")
    first = SqliteDatabase(database_url)
    revision_repository = RelationalDocumentRevisionRepository(database=first)
    revision_repository.append(
        "doc-1", revision_id="revision-1", title="T", content="<p>one</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )
    revision_repository.append(
        "doc-1", revision_id="revision-2", title="T", content="<p>two</p>",
        content_format=ContentFormat.HTML, created_at=STAMP,
    )
    first.dispose()

    second = SqliteDatabase(database_url)
    reopened = RelationalDocumentRevisionRepository(database=second)
    try:
        assert [r.revision_id for r in reopened.list_for_document("doc-1")] == [
            "revision-1",
            "revision-2",
        ]
        assert reopened.get("doc-1", "revision-2").created_at == STAMP  # type: ignore[union-attr]
    finally:
        second.dispose()


# ============================================================
# END: Durability across reopen
# ============================================================