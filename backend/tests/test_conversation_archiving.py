"""Phase 5.45 archive/restore persistence, preservation, and API regressions."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.contracts.events import EventType, RunEvent
from ava.infrastructure.composition import create_application_persistence
from ava.repositories.attachment_repository import AttachmentRecord
from ava.services.conversation_folder_service import ConversationFolderService
from ava.services.conversation_service import ConversationService
from ava.services.conversation_store import ConversationStore
from ava.services.project_service import ProjectService


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_archive_restore_preserve_everything_except_archive_state(mode: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(Settings(
        persistence_provider=mode, persistence_database_url=str(tmp_path / "archive.sqlite3")
    ))
    try:
        repository = persistence.conversation_repository
        repository.create("first", title="First")
        created = repository.create("target", title="Original")
        folder_service = ConversationFolderService(
            folder_repository=persistence.conversation_folder_repository,
            conversation_repository=repository,
        )
        folder = folder_service.create_folder("Preserved Folder")
        project_service = ProjectService(project_repository=persistence.project_repository)
        project = project_service.create_project(name="Preserved Project")
        if isinstance(repository, ConversationStore):
            repository._conversations["target"] = replace(
                created, is_pinned=True, folder_id=folder.id, project_id=project.id
            )
        else:
            assert persistence.database is not None
            with persistence.database.transaction() as connection:
                connection.execute(
                    "UPDATE conversations SET is_pinned = 1, folder_id = ?, project_id = ? "
                    "WHERE conversation_id = 'target'",
                    (folder.id, project.id),
                )
        service = ConversationService(
            conversation_repository=repository, message_repository=persistence.message_repository,
            run_repository=persistence.run_repository, project_repository=persistence.project_repository,
        )
        message = service.append_message("target", content="Keep me")
        attachment = AttachmentRecord(
            attachment_id="attachment-1", file_name="keep.txt", media_type="text/plain",
            size_bytes=4, storage_key="attachment-1", owner_type=AttachmentOwnerType.CONVERSATION,
            owner_id="target", status=AttachmentStatus.AVAILABLE, created_at=datetime.now(UTC),
        )
        persistence.attachment_repository.create(attachment)
        run = persistence.run_repository.create(
            "run-1", conversation_id="target", source_user_message_id=message.message_id
        )
        event = RunEvent(
            event_id="event-1", run_id=run.run_id, sequence=1, event_type=EventType.RUN_STARTED,
            timestamp=datetime.now(UTC), payload={},
        )
        persistence.run_event_repository.append(event)
        before = repository.get("target")
        messages_before = service.list_messages("target")
        runs_before = persistence.run_repository.get(run.run_id)
        events_before = persistence.run_event_repository.get_events(run.run_id)
        assert before is not None
        assert before.is_pinned and before.folder_id == folder.id and before.project_id == project.id

        for archived in (True, True, False, False):
            result = service.set_archived("target", archived)
            assert result is not None and result.is_archived is archived
            expected = replace(before, is_archived=archived)
            assert repository.get("target") == expected
            assert [record.conversation_id for record in repository.list()] == ["target", "first"]
            assert service.list_messages("target") == messages_before
            assert persistence.run_repository.get(run.run_id) == runs_before
            assert persistence.run_event_repository.get_events(run.run_id) == events_before
            assert list(persistence.attachment_repository.list_for_owner(
                AttachmentOwnerType.CONVERSATION, "target"
            )) == [attachment]
            if persistence.database is not None:
                with persistence.database.connect() as connection:
                    assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 2
                    assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
                    assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
                    assert connection.execute("SELECT COUNT(*) FROM run_events").fetchone()[0] == 1
                    assert connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 1

        assert service.set_archived("target", True) is not None
        renamed = service.update_title("target", "Renamed")
        assert renamed is not None and renamed.is_archived and renamed.is_pinned
        loaded = repository.get("target")
        assert loaded is not None
        assert (loaded.title, loaded.is_archived, loaded.is_pinned, loaded.folder_id, loaded.project_id) == (
            "Renamed", True, True, folder.id, project.id
        )
        assert service.set_archived("missing", True) is None
        assert repository.set_archived("missing", False) is None
    finally:
        persistence.dispose()


def test_http_archive_restore_validation_not_found_and_unfiltered_list(tmp_path: Path) -> None:
    settings = Settings(
        persistence_provider="relational", persistence_database_url=str(tmp_path / "archive-api.sqlite3")
    )
    with TestClient(create_app(settings=settings)) as client:
        first = client.post("/conversations", json={"title": "First"}).json()
        second = client.post("/conversations", json={"title": "Second"}).json()
        path = f"/conversations/{second['conversation_id']}"
        for archived in (True, True, False, False):
            response = client.patch(f"{path}/archive", json={"is_archived": archived})
            assert response.status_code == 200
            assert response.json() == {**second, "is_archived": archived}
            assert client.get(path).json() == response.json()
            listing = client.get("/conversations").json()["conversations"]
            assert [item["conversation_id"] for item in listing] == [
                second["conversation_id"], first["conversation_id"]
            ]
            assert listing[0]["is_archived"] is archived
        for body in ({}, {"is_pinned": True}, {"is_archived": None}, {"is_archived": "true"}, {"is_archived": 1}):
            assert client.patch(f"{path}/archive", json=body).status_code == 422
        missing = client.patch("/conversations/missing/archive", json={"is_archived": True})
        assert missing.status_code == 404
        assert missing.json()["error_code"] == "conversation_not_found"


def test_archive_and_restore_survive_backend_restart(tmp_path: Path) -> None:
    settings = Settings(persistence_provider="relational", persistence_database_url=str(tmp_path / "restart.sqlite3"))
    with TestClient(create_app(settings=settings)) as client:
        created = client.post("/conversations", json={"title": "Durable"}).json()
        path = f"/conversations/{created['conversation_id']}"
        assert client.patch(f"{path}/archive", json={"is_archived": True}).json()["is_archived"] is True
    with TestClient(create_app(settings=settings)) as client:
        assert client.get(path).json()["is_archived"] is True
        assert client.patch(f"{path}/archive", json={"is_archived": False}).json()["is_archived"] is False
    with TestClient(create_app(settings=settings)) as client:
        assert client.get(path).json() == created


def test_sqlite_archive_and_restore_restart_preserve_project_and_folder_without_http(tmp_path: Path) -> None:
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "metadata-restart.sqlite3"),
    )
    persistence = create_application_persistence(settings)
    folder_service = ConversationFolderService(
        folder_repository=persistence.conversation_folder_repository,
        conversation_repository=persistence.conversation_repository,
    )
    folder = folder_service.create_folder("Durable Folder")
    project = ProjectService(project_repository=persistence.project_repository).create_project(name="Durable Project")
    repository = persistence.conversation_repository
    created = repository.create("durable-conversation", title="Durable Conversation")
    service = ConversationService(
        conversation_repository=repository,
        message_repository=persistence.message_repository,
        run_repository=persistence.run_repository,
        project_repository=persistence.project_repository,
    )
    service.set_pinned(created.conversation_id, True)
    folder_service.set_conversation_folder(created.conversation_id, folder.id)
    service.set_project(created.conversation_id, project.id)
    archived = service.set_archived(created.conversation_id, True)
    assert archived is not None
    persistence.dispose()

    reopened = create_application_persistence(settings)
    try:
        stored = reopened.conversation_repository.get(created.conversation_id)
        assert stored is not None
        assert (stored.is_archived, stored.is_pinned, stored.folder_id, stored.project_id) == (
            True, True, folder.id, project.id
        )
        reopened_service = ConversationService(
            conversation_repository=reopened.conversation_repository,
            message_repository=reopened.message_repository,
            run_repository=reopened.run_repository,
            project_repository=reopened.project_repository,
        )
        restored = reopened_service.set_archived(created.conversation_id, False)
        assert restored is not None and not restored.is_archived
    finally:
        reopened.dispose()

    restored_persistence = create_application_persistence(settings)
    try:
        stored = restored_persistence.conversation_repository.get(created.conversation_id)
        assert stored is not None
        assert (stored.is_archived, stored.is_pinned, stored.folder_id, stored.project_id) == (
            False, True, folder.id, project.id
        )
    finally:
        restored_persistence.dispose()
