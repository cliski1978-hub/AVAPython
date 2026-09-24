"""Relational document repository tests (Step 4.6).

Mirror the in-memory ``DocumentStore`` semantics against the SQLite-backed
``RelationalDocumentRepository``: stable insertion-order listing, duplicate
rejection via ``ValueError``, title/content updates that refresh
``updated_at``, unknown-document ``None`` results, and content-format
round-tripping.
"""

from datetime import UTC, datetime

import pytest

from ava.contracts.documents import ContentFormat
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import RelationalDocumentRepository


@pytest.fixture()
def repository() -> tuple[RelationalDocumentRepository, SqliteDatabase]:
    database = SqliteDatabase(":memory:")
    yield RelationalDocumentRepository(database=database), database
    database.dispose()


# ============================================================
# BEGIN: Create / get / list semantics
# ============================================================


def test_create_produces_record(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    record = document_repository.create("d1", title="Notes", content="<p>Hi</p>", content_format=ContentFormat.HTML)
    assert record.document_id == "d1"
    assert record.title == "Notes"
    assert record.content == "<p>Hi</p>"
    assert record.content_format == ContentFormat.HTML
    assert record.created_at.tzinfo is not None
    assert record.updated_at.tzinfo is not None


def test_get_returns_created_record(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    created = document_repository.create("d1", title="Notes", content="<p>Hi</p>", content_format=ContentFormat.HTML)
    stored = document_repository.get("d1")
    assert stored is not None
    assert stored == created


def test_get_unknown_document_is_none(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    assert document_repository.get("ghost") is None


def test_list_reflects_insertion_order(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    for document_id in ("a", "b", "c"):
        document_repository.create(
            document_id, title=f"T-{document_id}", content="<p>x</p>", content_format=ContentFormat.HTML
        )
    assert [r.document_id for r in document_repository.list()] == ["a", "b", "c"]


def test_list_is_empty_when_no_documents(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    assert document_repository.list() == []


def test_duplicate_create_raises_value_error(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    document_repository.create("d1", title="Notes", content="<p>Hi</p>", content_format=ContentFormat.HTML)
    with pytest.raises(ValueError, match="Document already exists: d1"):
        document_repository.create("d1", title="Duplicate", content="<p>x</p>", content_format=ContentFormat.HTML)


# ============================================================
# END: Create / get / list semantics
# ============================================================


# ============================================================
# BEGIN: Update semantics
# ============================================================


def test_update_title_refreshes_record(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    document_repository.create("d1", title="Notes", content="<p>Hi</p>", content_format=ContentFormat.HTML)
    updated = document_repository.update_title("d1", "Renamed")
    assert updated is not None
    assert updated.title == "Renamed"
    assert updated.updated_at >= updated.created_at
    assert document_repository.get("d1") == updated


def test_update_content_refreshes_record(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    document_repository.create("d1", title="Notes", content="<p>Hi</p>", content_format=ContentFormat.HTML)
    updated = document_repository.update_content("d1", content="<p>Bye</p>", content_format=ContentFormat.HTML)
    assert updated is not None
    assert updated.content == "<p>Bye</p>"
    assert updated.content_format == ContentFormat.HTML
    assert updated.updated_at >= updated.created_at
    assert document_repository.get("d1") == updated


def test_update_title_unknown_document_is_none(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    assert document_repository.update_title("ghost", "Renamed") is None


def test_update_content_unknown_document_is_none(
    repository: tuple[RelationalDocumentRepository, SqliteDatabase],
) -> None:
    document_repository, _ = repository
    assert document_repository.update_content("ghost", content="<p>x</p>", content_format=ContentFormat.HTML) is None


# ============================================================
# END: Update semantics
# ============================================================


# ============================================================
# BEGIN: Timestamps
# ============================================================


def test_timestamps_round_trip_as_aware_utc(repository: tuple[RelationalDocumentRepository, SqliteDatabase]) -> None:
    document_repository, _ = repository
    before = datetime.now(UTC)
    document_repository.create("d1", title="Notes", content="<p>Hi</p>", content_format=ContentFormat.HTML)
    stored = document_repository.get("d1")
    assert stored is not None
    after = datetime.now(UTC)
    assert before <= stored.created_at <= after
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset().total_seconds() == 0
    assert stored.updated_at.tzinfo is not None


# ============================================================
# END: Timestamps
# ============================================================