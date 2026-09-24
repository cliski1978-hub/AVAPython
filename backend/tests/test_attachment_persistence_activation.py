"""Attachment persistence activation tests (Step 4.14.C).

Verify the application-persistence wiring for the attachment metadata port:

* memory mode selects ``InMemoryAttachmentRepository``;
* relational mode selects ``RelationalAttachmentRepository`` on the shared
  ``SqliteDatabase`` and survives a full application persistence reopen;
* the content store stays OUT of metadata persistence selection: physical
  content composition (Step 4.14.D) lives in the dedicated
  ``create_attachment_content_store`` seam, never inside the metadata
  persistence bundle.
"""

from datetime import UTC, datetime

import ava.infrastructure.composition as composition
import ava.infrastructure.persistence.composition as relational_composition
from ava.configuration.settings import Settings
from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.infrastructure.composition import ApplicationPersistence, create_application_persistence
from ava.infrastructure.persistence.composition import PersistenceRepositories
from ava.infrastructure.persistence.repositories import RelationalAttachmentRepository
from ava.repositories import AttachmentRecord
from ava.services.attachment_store import InMemoryAttachmentRepository


def _sample(attachment_id: str, owner_id: str = "doc-1") -> AttachmentRecord:
    return AttachmentRecord(
        attachment_id=attachment_id,
        file_name="report.pdf",
        media_type="application/pdf",
        size_bytes=1024,
        storage_key=f"attachments/{attachment_id}/source.pdf",
        owner_type=AttachmentOwnerType.DOCUMENT,
        owner_id=owner_id,
        status=AttachmentStatus.AVAILABLE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_memory_mode_selects_the_in_memory_attachment_repository() -> None:
    persistence = create_application_persistence(Settings())
    try:
        assert isinstance(persistence.attachment_repository, InMemoryAttachmentRepository)
        assert persistence.database is None
    finally:
        persistence.dispose()


def test_relational_mode_selects_the_relational_attachment_repository() -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider="relational", persistence_database_url=":memory:")
    )
    try:
        assert isinstance(persistence.attachment_repository, RelationalAttachmentRepository)
        assert persistence.attachment_repository._database is persistence.database
    finally:
        persistence.dispose()


def test_attachment_metadata_survives_application_persistence_reopen(tmp_path) -> None:
    """Metadata created through the composed port is restored after reopen."""
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "ava.sqlite3"),
    )
    first = create_application_persistence(settings)
    try:
        first.attachment_repository.create(
            _sample("attachment-1", owner_id="doc-1")
        )
        first.attachment_repository.create(
            _sample("attachment-2", owner_id="doc-2")
        )
    finally:
        first.dispose()

    second = create_application_persistence(settings)
    try:
        restored = second.attachment_repository.get("attachment-1")
        assert restored is not None
        assert restored.file_name == "report.pdf"
        assert restored.owner_type == AttachmentOwnerType.DOCUMENT
        assert restored.owner_id == "doc-1"
        assert restored.status == AttachmentStatus.AVAILABLE
        assert restored.created_at == datetime(2026, 1, 1, tzinfo=UTC)
        assert restored.created_at.utcoffset() == UTC.utcoffset(None)
        assert [
            record.attachment_id
            for record in second.attachment_repository.list_for_owner(AttachmentOwnerType.DOCUMENT, "doc-2")
        ] == ["attachment-2"]
    finally:
        second.dispose()


def test_content_store_is_not_wired_into_metadata_persistence_selection() -> None:
    """Metadata persistence composes repositories only; content wiring is separate."""
    fields = {field for field in ApplicationPersistence.__dataclass_fields__}
    assert "attachment_repository" in fields
    assert "attachment_content_store" not in fields
    assert "attachment_content_store" not in {
        field for field in PersistenceRepositories.__dataclass_fields__
    }

    persistence = create_application_persistence(
        Settings(persistence_provider="relational", persistence_database_url=":memory:")
    )
    try:
        assert persistence.attachment_repository is not None
        assert not hasattr(persistence, "attachment_content_store")
    finally:
        persistence.dispose()

    assert "attachment_content_store" not in composition.create_application_persistence.__code__.co_names
    assert "attachment_content_store" not in relational_composition.create_relational_repositories.__code__.co_names
    seam_names = composition.create_attachment_content_store.__code__.co_names
    assert "InMemoryAttachmentContentStore" in seam_names
    assert "LocalAttachmentContentStore" in seam_names