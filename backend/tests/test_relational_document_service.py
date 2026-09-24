"""Relational DocumentService integration tests (Step 4.13.D).

Prove the normal ``DocumentService`` write path, wired to the relational
write coordinator, generates durable revision history:

* ``create`` persists the document *and* revision 1 through the service;
* ``update`` advances the current state and appends exactly one next revision
  (a combined title+content update stays a single revision);
* the latest revision snapshot equals the final current state;
* history survives a full database close/reopen;
* a Step 4.6 legacy document (adopted without backfill) receives revision 1
  on its first service update;
* the transactional write path is proven through the service: a failing
  revision append rolls the whole write back (create leaves nothing behind,
  update restores state A) — forced through the narrowest existing seam, the
  repository-append connection seam, using real ``sqlite3`` driver errors.
"""

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from ava.configuration.settings import Settings
from ava.contracts.documents import ContentFormat
from ava.infrastructure.composition import create_application_persistence
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.migrations.versions.v0001_initial_schema import migrate_up
from ava.infrastructure.persistence.repositories import (
    RelationalDocumentRepository,
    RelationalDocumentRevisionRepository,
    RelationalDocumentWriteCoordinator,
)
from ava.services.document_service import DocumentService, DuplicateDocumentError


def relational_settings(database_url: str) -> Settings:
    """Build relational settings pointed at one SQLite database."""
    return Settings(persistence_provider="relational", persistence_database_url=database_url)


def make_service(persistence) -> DocumentService:
    """Build a DocumentService over a composed application persistence bundle."""
    return DocumentService(
        document_repository=persistence.document_repository,
        document_revision_repository=persistence.document_revision_repository,
        document_write_coordinator=persistence.document_write_coordinator,
    )


def linked_fields(record) -> tuple[str, str, ContentFormat]:
    """Return the snapshot fields compared across current/revision states."""
    return record.title, record.content, record.content_format


class _FailingRelationalRevisionRepository(RelationalDocumentRevisionRepository):
    """Test double: ``_append_on`` always trips the real UNIQUE(revision_id) constraint."""

    def _append_on(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        *,
        revision_id: str,
        title: str,
        content: str,
        content_format: ContentFormat,
        created_at: datetime,
    ):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: document_revisions.revision_id")


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
# BEGIN: Service create / update history
# ============================================================


def test_create_persists_revision_one_through_the_service(tmp_path) -> None:
    persistence = create_application_persistence(relational_settings(str(tmp_path / "ava.sqlite3")))
    try:
        service = make_service(persistence)
        created = service.create_document(title="My Doc", content="<p>body</p>")

        revisions = persistence.document_revision_repository.list_for_document(created.document_id)
        assert len(revisions) == 1
        revision = revisions[0]
        assert revision.revision_number == 1
        assert revision.title == created.title
        assert revision.content == created.content
        assert revision.content_format == created.content_format
    finally:
        persistence.dispose()


def test_update_persists_the_next_revision_through_the_service(tmp_path) -> None:
    persistence = create_application_persistence(relational_settings(str(tmp_path / "ava.sqlite3")))
    try:
        service = make_service(persistence)
        created = service.create_document(title="Before", content="<p>first</p>")

        updated = service.update_document(created.document_id, title="After", content="<p>second</p>")
        assert updated is not None

        revisions = persistence.document_revision_repository.list_for_document(created.document_id)
        assert [revision.revision_number for revision in revisions] == [1, 2]
        latest = persistence.document_revision_repository.get_latest(created.document_id)
        assert latest is not None
        assert linked_fields(latest) == linked_fields(updated)
        stored = persistence.document_repository.get(created.document_id)
        assert stored is not None
        assert linked_fields(stored) == linked_fields(updated)
        assert stored.created_at == updated.created_at
        assert stored.updated_at == updated.updated_at
    finally:
        persistence.dispose()


def test_combined_title_and_content_update_persists_exactly_one_revision(tmp_path) -> None:
    persistence = create_application_persistence(relational_settings(str(tmp_path / "ava.sqlite3")))
    try:
        service = make_service(persistence)
        created = service.create_document(title="Old", content="<p>first</p>")

        updated = service.update_document(created.document_id, title="New Title", content="<p>deep</p>")
        assert updated is not None

        listed = persistence.document_revision_repository.list_for_document(created.document_id)
        assert len(listed) == 2
        assert listed[1].revision_number == 2
        assert linked_fields(listed[1]) == linked_fields(updated)
    finally:
        persistence.dispose()


def test_history_survives_dispose_and_reopen(tmp_path) -> None:
    database_url = str(tmp_path / "ava.sqlite3")
    first = create_application_persistence(relational_settings(database_url))
    try:
        service = make_service(first)
        created = service.create_document(title="Durable", content="<p>one</p>")
        updated = service.update_document(created.document_id, title="Durable", content="<p>two</p>")
        assert updated is not None
    finally:
        first.dispose()

    second = create_application_persistence(relational_settings(database_url))
    try:
        revisions = second.document_revision_repository.list_for_document(created.document_id)
        assert [revision.revision_number for revision in revisions] == [1, 2]
        assert revisions[1].content == "<p>two</p>"
        restored = second.document_repository.get(created.document_id)
        assert restored is not None
        assert restored.content == "<p>two</p>"
    finally:
        second.dispose()


# ============================================================
# BEGIN: Revision read integration through the service (Step 4.13.E)
# ============================================================


def test_relational_service_read_path_observes_revisions_immediately(tmp_path) -> None:
    """list/get revisions through the service reflect writes instantly."""
    persistence = create_application_persistence(relational_settings(str(tmp_path / "ava.sqlite3")))
    try:
        service = make_service(persistence)
        created = service.create_document(title="My Doc", content="<p>original</p>")
        updated = service.update_document(created.document_id, title="My Doc", content="<p>revised</p>")
        assert updated is not None

        history = service.list_revisions(created.document_id)
        assert history is not None
        assert history.document_id == created.document_id
        assert [revision.revision_number for revision in history.revisions] == [1, 2]

        first, second = history.revisions
        assert first.revision_number == 1
        assert first.title == "My Doc"
        assert first.content == "<p>original</p>"
        assert second.revision_number == 2
        assert second.content == "<p>revised</p>"

        rev_one = service.get_revision(created.document_id, first.revision_id)
        rev_two = service.get_revision(created.document_id, second.revision_id)
        assert rev_one is not None and rev_one.content == "<p>original</p>"
        assert rev_two is not None and rev_two.content == "<p>revised</p>"
        assert service.get_revision(created.document_id, "missing") is None
    finally:
        persistence.dispose()


def test_relational_revision_reads_survive_dispose_and_reopen(tmp_path) -> None:
    """Revision read durability: reopen sees the same list/get results."""
    database_url = str(tmp_path / "ava.sqlite3")
    first = create_application_persistence(relational_settings(database_url))
    try:
        service = make_service(first)
        created = service.create_document(title="Durable", content="<p>one</p>")
        service.update_document(created.document_id, title="Durable", content="<p>two</p>")
    finally:
        first.dispose()

    second = create_application_persistence(relational_settings(database_url))
    try:
        service = make_service(second)
        history = service.list_revisions(created.document_id)
        assert history is not None
        assert [revision.revision_number for revision in history.revisions] == [1, 2]
        assert [revision.content for revision in history.revisions] == ["<p>one</p>", "<p>two</p>"]

        second_revision = service.get_revision(created.document_id, history.revisions[1].revision_id)
        assert second_revision is not None
        assert second_revision.revision_number == 2
        assert second_revision.content == "<p>two</p>"
        assert second_revision.created_at == history.revisions[1].created_at
    finally:
        second.dispose()


# ============================================================
# END: Revision read integration through the service (Step 4.13.E)
# ============================================================


# ============================================================
# END: Service create / update history
# ============================================================

# ============================================================
# BEGIN: Legacy no-backfill
# ============================================================


def test_legacy_document_gets_revision_one_on_first_service_update() -> None:
    """A pre-v2 document (no backfill) numbers its first service update 1."""
    path = Path(tempfile.mktemp(suffix=".sqlite3"))
    try:
        _make_legacy_schema_with_document(path)
        persistence = create_application_persistence(relational_settings(str(path)))
        try:
            service = make_service(persistence)
            assert service.get_document("legacy-doc") is not None
            revisions = persistence.document_revision_repository.list_for_document("legacy-doc")
            assert revisions == []

            updated = service.update_document(
                "legacy-doc", title="Now Versioned", content="<p>first write</p>"
            )
            assert updated is not None
            assert updated.title == "Now Versioned"

            listed = persistence.document_revision_repository.list_for_document("legacy-doc")
            assert [revision.revision_number for revision in listed] == [1]
            assert listed[0].title == "Now Versioned"
            assert listed[0].content == "<p>first write</p>"
        finally:
            persistence.dispose()
    finally:
        path.unlink()


# ============================================================
# END: Legacy no-backfill
# ============================================================

# ============================================================
# BEGIN: Atomicity through the service
# ============================================================


def test_create_rolls_back_through_the_service_on_failed_revision_append() -> None:
    database = SqliteDatabase(":memory:", auto_migrate=True)
    database.ensure_schema()
    document_repository = RelationalDocumentRepository(database=database)
    failing_revisions = _FailingRelationalRevisionRepository(database=database)
    try:
        coordinator = RelationalDocumentWriteCoordinator(
            database=database,
            document_repository=document_repository,
            revision_repository=failing_revisions,
        )
        service = DocumentService(
            document_repository=document_repository,
            document_revision_repository=failing_revisions,
            document_write_coordinator=coordinator,
        )

        with pytest.raises(DuplicateDocumentError, match="Revision already exists"):
            service.create_document(content="<p>body</p>")

        assert document_repository.list() == []
        assert failing_revisions.list_for_document("none") == []
    finally:
        database.dispose()


def test_update_rolls_back_to_state_a_through_the_service_on_failed_append() -> None:
    database = SqliteDatabase(":memory:", auto_migrate=True)
    database.ensure_schema()
    document_repository = RelationalDocumentRepository(database=database)
    try:
        good_revisions = RelationalDocumentRevisionRepository(database=database)
        good_coordinator = RelationalDocumentWriteCoordinator(
            database=database,
            document_repository=document_repository,
            revision_repository=good_revisions,
        )
        service = DocumentService(
            document_repository=document_repository,
            document_revision_repository=good_revisions,
            document_write_coordinator=good_coordinator,
        )
        created = service.create_document(title="State A", content="<p>first</p>")

        failing_revisions = _FailingRelationalRevisionRepository(database=database)
        failing_coordinator = RelationalDocumentWriteCoordinator(
            database=database,
            document_repository=document_repository,
            revision_repository=failing_revisions,
        )
        failing_service = DocumentService(
            document_repository=document_repository,
            document_revision_repository=good_revisions,
            document_write_coordinator=failing_coordinator,
        )

        with pytest.raises(ValueError, match="Revision already exists"):
            failing_service.update_document(created.document_id, title="State B", content="<p>second</p>")

        stored = document_repository.get(created.document_id)
        assert stored is not None
        assert stored.title == "State A"
        assert stored.content == "<p>first</p>"
        listed = good_revisions.list_for_document(created.document_id)
        assert [revision.revision_number for revision in listed] == [1]
        assert listed[0].title == "State A"

        recovered = service.update_document(created.document_id, title="State B", content="<p>second</p>")
        assert recovered is not None
        assert recovered.title == "State B"
        final = good_revisions.list_for_document(created.document_id)
        assert [revision.revision_number for revision in final] == [1, 2]
    finally:
        database.dispose()


# ============================================================
# END: Atomicity through the service
# ============================================================