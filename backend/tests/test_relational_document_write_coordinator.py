"""RelationalDocumentWriteCoordinator tests (Step 4.13.C).

Prove the SQLite-backed write coordinator advances document current state and
immutable revision history as one atomic transaction:

* ``create`` persists the document and appends exactly revision 1;
* ``update`` advances the current state and appends exactly one next revision
  (a combined title+content save stays one revision) while earlier revisions
  remain untouched;
* the single ``BEGIN IMMEDIATE`` transaction makes any failure atomic: a
  revision append that trips the database's ``UNIQUE(revision_id)`` constraint
  rolls the current-state write back, leaving no trace;
* an unknown-document update is a ``ValueError`` that leaves nothing behind;
* a Step 4.6 legacy document (adopted through v0002 with no revisions) gets
  its first coordinator update numbered 1 instead of being backfilled;
* history survives dispose/reopen against a file-backed database.

The rollback proofs use real database constraints (globally-unique
``revision_id``), not injected failure switches.
"""

import sqlite3
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ava.contracts.documents import ContentFormat
from ava.infrastructure.persistence import SqliteDatabase, create_relational_repositories
from ava.infrastructure.persistence.migrations.versions.v0001_initial_schema import migrate_up
from ava.infrastructure.persistence.repositories import (
    RelationalDocumentRepository,
    RelationalDocumentRevisionRepository,
    RelationalDocumentWriteCoordinator,
)
from ava.repositories import DocumentRecord

STAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
NEXT_STAMP = datetime(2026, 1, 1, 12, 30, 0, tzinfo=UTC)

# ============================================================
# BEGIN: Fixtures
# ============================================================


def sample_record(
    document_id: str = "doc-1",
    *,
    title: str = "Untitled Document",
    content: str = "<p>body</p>",
) -> DocumentRecord:
    """Create a fully prepared current-state record for coordinator writes."""
    return DocumentRecord(
        document_id=document_id,
        title=title,
        content=content,
        content_format=ContentFormat.HTML,
        created_at=STAMP,
        updated_at=STAMP,
    )


@pytest.fixture()
def coordinator() -> tuple[RelationalDocumentWriteCoordinator, SqliteDatabase]:
    repositories = create_relational_repositories(":memory:", run_migrations=True)
    try:
        yield repositories.document_write_coordinator, repositories.database
    finally:
        repositories.dispose()


def _make_legacy_schema_with_document(path: Path) -> None:
    """Create a Step 4.6 schema (v0001) plus one document row, no history."""
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_up(connection)
    connection.execute(
        "INSERT INTO documents (document_id, title, content, content_format, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "legacy-doc",
            "Legacy",
            "<p>before revisions</p>",
            "html",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()


# ============================================================
# END: Fixtures
# ============================================================

# ============================================================
# BEGIN: Create
# ============================================================


def test_create_persists_the_document_and_appends_revision_one(
    coordinator: tuple[RelationalDocumentWriteCoordinator, SqliteDatabase],
) -> None:
    write_coordinator, database = coordinator
    document_repository = RelationalDocumentRepository(database=database)
    revision_repository = RelationalDocumentRevisionRepository(database=database)

    current, revision = write_coordinator.create(
        sample_record(),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )

    assert current.document_id == "doc-1"
    assert document_repository.get("doc-1") == current
    assert revision_repository.list_for_document("doc-1") == [revision]
    assert revision.revision_id == "revision-1"
    assert revision.revision_number == 1
    assert revision.created_at == STAMP
    assert revision_repository.get_latest("doc-1") == revision


def test_create_appends_exactly_one_revision(
    coordinator: tuple[RelationalDocumentWriteCoordinator, SqliteDatabase],
) -> None:
    write_coordinator, database = coordinator
    write_coordinator.create(sample_record(), revision_id="revision-1", revision_created_at=STAMP)
    revision_repository = RelationalDocumentRevisionRepository(database=database)
    assert len(revision_repository.list_for_document("doc-1")) == 1


def test_create_duplicate_document_raises_and_leaves_no_trace(
    coordinator: tuple[RelationalDocumentWriteCoordinator, SqliteDatabase],
) -> None:
    write_coordinator, database = coordinator
    write_coordinator.create(sample_record(), revision_id="revision-1", revision_created_at=STAMP)

    with pytest.raises(ValueError, match="Document already exists: doc-1"):
        write_coordinator.create(
            sample_record(title="Intruder"),
            revision_id="revision-2",
            revision_created_at=STAMP,
        )

    document_repository = RelationalDocumentRepository(database=database)
    revision_repository = RelationalDocumentRevisionRepository(database=database)
    assert document_repository.list()[0].title == "Untitled Document"
    assert [r.revision_id for r in revision_repository.list_for_document("doc-1")] == ["revision-1"]


# ============================================================
# END: Create
# ============================================================

# ============================================================
# BEGIN: Update
# ============================================================


def test_update_advances_state_and_appends_the_next_revision(
    coordinator: tuple[RelationalDocumentWriteCoordinator, SqliteDatabase],
) -> None:
    write_coordinator, database = coordinator
    create_current, _ = write_coordinator.create(
        sample_record(title="Before", content="<p>first</p>"),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )

    updated, revision = write_coordinator.update(
        replace(create_current, title="After", content="<p>second</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )

    assert updated.title == "After"
    assert updated.content == "<p>second</p>"
    assert updated.created_at == create_current.created_at
    assert revision.revision_number == 2
    assert revision.created_at == NEXT_STAMP
    document_repository = RelationalDocumentRepository(database=database)
    revision_repository = RelationalDocumentRevisionRepository(database=database)
    assert document_repository.get("doc-1") == updated
    assert revision_repository.get_latest("doc-1") == revision


def test_combined_title_and_content_save_stays_one_revision(
    coordinator: tuple[RelationalDocumentWriteCoordinator, SqliteDatabase],
) -> None:
    write_coordinator, database = coordinator
    create_current, _ = write_coordinator.create(
        sample_record(title="Old", content="<p>first</p>"),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )
    write_coordinator.update(
        replace(create_current, title="New Title", content="<p>deep</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )
    revision_repository = RelationalDocumentRevisionRepository(database=database)
    assert len(revision_repository.list_for_document("doc-1")) == 2


def test_update_preserves_earlier_revisions_untouched(
    coordinator: tuple[RelationalDocumentWriteCoordinator, SqliteDatabase],
) -> None:
    write_coordinator, database = coordinator
    create_current, first_revision = write_coordinator.create(
        sample_record(title="Version One", content="<p>first</p>"),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )
    write_coordinator.update(
        replace(create_current, title="Version Two", content="<p>second</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )
    revision_repository = RelationalDocumentRevisionRepository(database=database)
    assert revision_repository.get("doc-1", "revision-1") == first_revision
    assert [r.revision_id for r in revision_repository.list_for_document("doc-1")] == [
        "revision-1",
        "revision-2",
    ]


def test_update_on_an_unknown_document_raises_and_leaves_no_trace(
    coordinator: tuple[RelationalDocumentWriteCoordinator, SqliteDatabase],
) -> None:
    write_coordinator, database = coordinator
    with pytest.raises(ValueError, match="Document not found: doc-1"):
        write_coordinator.update(
            sample_record(),
            revision_id="revision-1",
            revision_created_at=STAMP,
        )
    document_repository = RelationalDocumentRepository(database=database)
    revision_repository = RelationalDocumentRevisionRepository(database=database)
    assert document_repository.list() == []
    assert revision_repository.list_for_document("doc-1") == []


# ============================================================
# END: Update
# ============================================================

# ============================================================
# BEGIN: Atomicity (real database constraints)
# ============================================================


def test_create_rolls_back_when_the_revision_append_fails(
    coordinator: tuple[RelationalDocumentWriteCoordinator, SqliteDatabase],
) -> None:
    """A duplicate revision_id after the document insert rolls the whole write back."""
    write_coordinator, database = coordinator
    write_coordinator.create(sample_record("doc-1"), revision_id="revision-1", revision_created_at=STAMP)

    with pytest.raises(ValueError, match="Revision already exists: revision-1"):
        write_coordinator.create(
            sample_record("doc-2"),
            revision_id="revision-1",
            revision_created_at=STAMP,
        )

    document_repository = RelationalDocumentRepository(database=database)
    revision_repository = RelationalDocumentRevisionRepository(database=database)
    assert document_repository.get("doc-2") is None
    assert revision_repository.list_for_document("doc-2") == []


def test_update_rolls_back_state_and_history_when_the_append_fails(
    coordinator: tuple[RelationalDocumentWriteCoordinator, SqliteDatabase],
) -> None:
    """A failed append rolls the document update back to state A, history intact."""
    write_coordinator, database = coordinator
    create_current, _ = write_coordinator.create(
        sample_record(title="State A", content="<p>first</p>"),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )

    with pytest.raises(ValueError, match="Revision already exists: revision-1"):
        write_coordinator.update(
            replace(create_current, title="State B", content="<p>second</p>"),
            revision_id="revision-1",
            revision_created_at=NEXT_STAMP,
        )

    document_repository = RelationalDocumentRepository(database=database)
    revision_repository = RelationalDocumentRevisionRepository(database=database)
    stored = document_repository.get("doc-1")
    assert stored is not None
    assert stored.title == "State A"
    assert stored.content == "<p>first</p>"
    assert [r.revision_id for r in revision_repository.list_for_document("doc-1")] == ["revision-1"]
    assert len(revision_repository.list_for_document("doc-1")) == 1

    updated, recovered = write_coordinator.update(
        replace(create_current, title="State B", content="<p>second</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )
    assert updated.title == "State B"
    assert recovered.revision_number == 2


# ============================================================
# END: Atomicity (real database constraints)
# ============================================================

# ============================================================
# BEGIN: Legacy adoption
# ============================================================


def test_pre_existing_document_gets_revision_one_on_first_coordinator_update() -> None:
    """A legacy v1 document (no backfill) numbers its first write 1."""
    path = Path(tempfile.mktemp(suffix=".sqlite3"))
    try:
        _make_legacy_schema_with_document(path)
        repositories = create_relational_repositories(str(path))
        try:
            assert repositories.document_repository.get("legacy-doc") is not None
            assert repositories.document_revision_repository.list_for_document("legacy-doc") == []

            legacy = repositories.document_repository.get("legacy-doc")
            assert legacy is not None
            updated, revision = repositories.document_write_coordinator.update(
                replace(legacy, title="Now Versioned", content="<p>first write</p>"),
                revision_id="revision-1",
                revision_created_at=NEXT_STAMP,
            )
            assert updated.title == "Now Versioned"
            assert revision.revision_number == 1
            listed = repositories.document_revision_repository.list_for_document("legacy-doc")
            assert [r.revision_number for r in listed] == [1]
        finally:
            repositories.dispose()
    finally:
        path.unlink()


# ============================================================
# END: Legacy adoption
# ============================================================

# ============================================================
# BEGIN: Durability across reopen
# ============================================================


def test_history_survives_dispose_and_reopen(tmp_path) -> None:
    """Coordinator-produced history persists through a full close/reopen."""
    database_url = str(tmp_path / "ava.sqlite3")
    first = create_relational_repositories(database_url)
    created, first_revision = first.document_write_coordinator.create(
        sample_record(title="Durable", content="<p>one</p>"),
        revision_id="revision-1",
        revision_created_at=STAMP,
    )
    first.document_write_coordinator.update(
        replace(created, title="Durable", content="<p>two</p>"),
        revision_id="revision-2",
        revision_created_at=NEXT_STAMP,
    )
    first.dispose()

    second = create_relational_repositories(database_url)
    try:
        listed = second.document_revision_repository.list_for_document("doc-1")
        assert [r.revision_id for r in listed] == ["revision-1", "revision-2"]
        assert listed[0] == first_revision
        assert second.document_repository.get("doc-1").content == "<p>two</p>"  # type: ignore[union-attr]
    finally:
        second.dispose()


# ============================================================
# END: Durability across reopen
# ============================================================