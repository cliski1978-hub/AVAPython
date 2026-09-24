"""Document persistence activation tests (Step 4.10).

These tests exercise the application-persistence selection and the existing
DocumentService boundary. API restart coverage remains in the route tests but
is blocked locally by the known FastAPI TestClient context-entry deadlock.
"""

from datetime import UTC, datetime

import pytest

from ava.configuration.settings import Settings
from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.documents import ContentFormat
from ava.contracts.events import EventType, RunEvent
from ava.infrastructure.composition import create_application_persistence
from ava.infrastructure.persistence.repositories import RelationalDocumentRepository
from ava.repositories import MessageRecord
from ava.services.conversation_service import ConversationService
from ava.services.document_service import DocumentService, InvalidDocumentContentError
from ava.services.document_store import DocumentStore


def relational_settings(database_url: str) -> Settings:
    """Build relational settings pointed at one temporary SQLite database."""
    return Settings(persistence_provider="relational", persistence_database_url=database_url)


def test_memory_mode_keeps_document_store() -> None:
    """The default continues to select the first-class in-memory document store."""
    persistence = create_application_persistence(Settings())
    assert isinstance(persistence.document_repository, DocumentStore)
    assert persistence.database is None


def test_memory_mode_shares_one_document_and_revision_store() -> None:
    """The memory coordinator and repositories observe the same store instances."""
    from ava.services.document_revision_store import InMemoryDocumentRevisionStore
    from ava.services.document_write_coordinator import InMemoryDocumentWriteCoordinator

    persistence = create_application_persistence(Settings())
    assert isinstance(persistence.document_revision_repository, InMemoryDocumentRevisionStore)
    assert isinstance(persistence.document_write_coordinator, InMemoryDocumentWriteCoordinator)
    assert persistence.document_write_coordinator._documents is persistence.document_repository
    assert persistence.document_write_coordinator._revisions is persistence.document_revision_repository


def test_relational_mode_selects_document_adapter_over_shared_database(tmp_path) -> None:
    """The document adapters use the same resource as every other domain."""
    persistence = create_application_persistence(relational_settings(str(tmp_path / "ava.sqlite3")))
    try:
        assert isinstance(persistence.document_repository, RelationalDocumentRepository)
        database = persistence.database
        assert database is not None
        assert persistence.run_repository._database is database
        assert persistence.run_event_repository._database is database
        assert persistence.conversation_repository._database is database
        assert persistence.message_repository._database is database
        assert persistence.document_repository._database is database
        assert persistence.document_revision_repository._database is database
        coordinator = persistence.document_write_coordinator
        assert coordinator._database is database
        assert coordinator._document_repository is persistence.document_repository
        assert coordinator._revision_repository is persistence.document_revision_repository
    finally:
        persistence.dispose()


def test_document_survives_application_restart_through_api(tmp_path) -> None:
    """The API create/update/read path is durable across application recreation.

    This intentionally uses the normal FastAPI lifespan path. It is retained
    even though this host's known TestClient context-entry deadlock prevents
    executing it locally.
    """
    from fastapi.testclient import TestClient

    from ava.api.app import create_app

    settings = relational_settings(str(tmp_path / "ava.sqlite3"))
    with TestClient(create_app(settings=settings)) as client:
        created = client.post(
            "/documents", json={"title": "Before", "content": "<p>original</p>"}
        ).json()
        document_id = created["document_id"]
        updated = client.patch(
            f"/documents/{document_id}",
            json={"title": "After", "content": "<h2>durable</h2>"},
        ).json()

    with TestClient(create_app(settings=settings)) as client:
        restored = client.get(f"/documents/{document_id}")
        assert restored.status_code == 200
        assert restored.json() == {
            **updated,
            "created_at": created["created_at"],
        }


def test_document_create_update_and_restart_round_trip(tmp_path) -> None:
    """Service-created HTML documents retain identity, content, and UTC times."""
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))
    first = create_application_persistence(settings)
    try:
        service = DocumentService(
            document_repository=first.document_repository,
            document_revision_repository=first.document_revision_repository,
            document_write_coordinator=first.document_write_coordinator,
        )
        created = service.create_document(title="Before", content="<p>original</p>")
        renamed = service.rename_document(created.document_id, "After")
        assert renamed is not None
        updated = service.update_document_content(
            created.document_id,
            content="<h2>durable</h2><p>exact HTML</p>",
        )
        assert updated is not None
        assert updated.created_at == created.created_at
        assert updated.updated_at >= renamed.updated_at
    finally:
        first.dispose()

    second = create_application_persistence(settings)
    try:
        restored = DocumentService(
            document_repository=second.document_repository,
            document_revision_repository=second.document_revision_repository,
            document_write_coordinator=second.document_write_coordinator,
        ).get_document(
            created.document_id
        )
        assert restored is not None
        assert restored.document_id == created.document_id
        assert restored.title == "After"
        assert restored.content == "<h2>durable</h2><p>exact HTML</p>"
        assert restored.content_format is ContentFormat.HTML
        assert restored.created_at == created.created_at
        assert restored.updated_at == updated.updated_at
        assert restored.created_at.tzinfo is not None
        assert restored.created_at.utcoffset() == UTC.utcoffset(None)
    finally:
        second.dispose()


def test_relational_documents_preserve_list_order_and_unknown_semantics(tmp_path) -> None:
    """List order and unknown-document results match the memory repository port."""
    persistence = create_application_persistence(relational_settings(str(tmp_path / "ava.sqlite3")))
    try:
        service = DocumentService(
            document_repository=persistence.document_repository,
            document_revision_repository=persistence.document_revision_repository,
            document_write_coordinator=persistence.document_write_coordinator,
        )
        first = service.create_document(title="One", content="<p>one</p>")
        second = service.create_document(title="Two", content="<p>two</p>")
        assert [document.document_id for document in service.list_documents().documents] == [
            first.document_id,
            second.document_id,
        ]
        assert service.get_document("missing") is None
        assert service.rename_document("missing", "Nope") is None
        assert service.update_document_content("missing", content="<p>x</p>") is None
    finally:
        persistence.dispose()


def test_relational_document_service_enforces_html_policy_before_storage(tmp_path) -> None:
    """Selecting SQLite cannot bypass the existing service-level HTML policy."""
    persistence = create_application_persistence(relational_settings(str(tmp_path / "ava.sqlite3")))
    try:
        service = DocumentService(
            document_repository=persistence.document_repository,
            document_revision_repository=persistence.document_revision_repository,
            document_write_coordinator=persistence.document_write_coordinator,
        )
        with pytest.raises(InvalidDocumentContentError):
            service.create_document(content="<script>alert(1)</script>")
        assert service.list_documents().documents == []
    finally:
        persistence.dispose()


def test_all_five_domains_survive_one_application_persistence_restart(tmp_path) -> None:
    """One relational composition persists every activated Phase 4 domain."""
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))
    first = create_application_persistence(settings)
    try:
        first.run_repository.create("run-1")
        first.run_event_repository.append(
            RunEvent(event_id="event-1", run_id="run-1", event_type=EventType.RUN_STARTED)
        )
        conversation = ConversationService(
            conversation_repository=first.conversation_repository,
            message_repository=first.message_repository,
        ).create_conversation(title="Conversation")
        now = datetime.now(UTC)
        first.message_repository.append(
            MessageRecord(
                message_id="message-1",
                conversation_id=conversation.conversation_id,
                role=MessageRole.USER,
                content="hello",
                status=MessageStatus.COMPLETE,
                created_at=now,
                updated_at=now,
            )
        )
        document = DocumentService(
            document_repository=first.document_repository,
            document_revision_repository=first.document_revision_repository,
            document_write_coordinator=first.document_write_coordinator,
        ).create_document(
            title="Document", content="<p>durable</p>"
        )
    finally:
        first.dispose()

    second = create_application_persistence(settings)
    try:
        assert second.run_repository.get("run-1") is not None
        assert [event.event_id for event in second.run_event_repository.get_events("run-1")] == ["event-1"]
        assert second.conversation_repository.get(conversation.conversation_id) is not None
        messages = second.message_repository.list_for_conversation(conversation.conversation_id)
        assert [message.message_id for message in messages] == ["message-1"]
        restored = DocumentService(
            document_repository=second.document_repository,
            document_revision_repository=second.document_revision_repository,
            document_write_coordinator=second.document_write_coordinator,
        ).get_document(document.document_id)
        assert restored is not None
        assert restored.content == "<p>durable</p>"
    finally:
        second.dispose()
