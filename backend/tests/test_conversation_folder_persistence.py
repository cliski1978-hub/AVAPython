"""Phase 5.54 folder persistence, assignment, and delete integrity tests."""

from dataclasses import replace
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.events import EventType, RunEvent
from ava.infrastructure.composition import create_application_persistence
from ava.infrastructure.persistence.database import PersistenceError, SqliteDatabase
from ava.infrastructure.persistence.migrations.runner import MigrationRunner
from ava.infrastructure.persistence.migrations.versions import default_registry
from ava.repositories.conversation_folder_repository import ConversationFolderRepository
from ava.repositories.message_repository import MessageRecord
from ava.services.conversation_folder_service import (
    ConversationFolderNotFoundError,
    ConversationFolderService,
    InvalidConversationFolderNameError,
)
from ava.services.conversation_service import ConversationService


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_folder_crud_assignment_and_folder_delete_preserve_conversations(provider: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(
            persistence_provider=provider,
            persistence_database_url=str(tmp_path / f"{provider}.sqlite3"),
        )
    )
    try:
        conversations = persistence.conversation_repository
        folders: ConversationFolderRepository = persistence.conversation_folder_repository
        service = ConversationFolderService(folder_repository=folders, conversation_repository=conversations)
        first = conversations.create("c1", title="First")
        first = conversations.set_pinned("c1", True)
        first = conversations.set_archived("c1", True)
        assert first is not None
        child = MessageRecord(
            message_id="child-message",
            conversation_id="c1",
            role=MessageRole.USER,
            content="Keep me",
            status=MessageStatus.COMPLETE,
            created_at=first.created_at,
            updated_at=first.updated_at,
        )
        persistence.message_repository.append(child)
        conversations.create("c2", title="Second")
        active_run = persistence.run_repository.create("active-run", conversation_id="c1")
        persistence.run_event_repository.append(
            RunEvent(event_id="folder-move-event", run_id=active_run.run_id, event_type=EventType.RUN_STARTED)
        )
        run_events_before_move = list(persistence.run_event_repository.get_events(active_run.run_id))
        created = service.create_folder("  Engineering  ")
        duplicate = service.create_folder("engineering")
        assert created.name == "Engineering" and created.created_at == created.updated_at
        assert created.id != duplicate.id
        listed = service.list_folders()
        assert listed == sorted(listed, key=lambda item: (item.name.casefold(), item.created_at, item.id))
        assert {item.name for item in listed} == {"engineering", "Engineering"}
        assert service.get_folder(created.id) == created
        with pytest.raises(InvalidConversationFolderNameError):
            service.create_folder("  ")

        assigned = service.set_conversation_folder("c1", created.id)
        assert assigned.folder_id == created.id
        assert replace(assigned, folder_id=None) == first
        assert persistence.run_repository.get(active_run.run_id) == active_run
        assert list(persistence.run_event_repository.get_events(active_run.run_id)) == run_events_before_move
        assert persistence.message_repository.get("c1", child.message_id) == child
        renamed = service.rename_folder(created.id, "  Platform  ")
        assert renamed.id == created.id and renamed.created_at == created.created_at
        assert renamed.name == "Platform" and renamed.updated_at >= created.updated_at
        assert conversations.get("c1").folder_id == created.id  # type: ignore[union-attr]
        service.set_conversation_folder("c1", None)
        assert conversations.get("c1").folder_id is None  # type: ignore[union-attr]
        service.set_conversation_folder("c1", created.id)
        service.delete_folder(created.id)
        assert folders.get(created.id) is None
        assert conversations.get("c1") is not None
        assert conversations.get("c1").folder_id is None  # type: ignore[union-attr]
        assert conversations.get("c2").folder_id is None  # type: ignore[union-attr]
        assert persistence.run_repository.get(active_run.run_id) == active_run
        assert persistence.message_repository.get("c1", child.message_id) == child
        with pytest.raises(ConversationFolderNotFoundError):
            service.set_conversation_folder("c1", created.id)
    finally:
        persistence.dispose()


def test_relational_folder_delete_rolls_back_reference_cleanup(tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider="relational", persistence_database_url=str(tmp_path / "rollback.sqlite3"))
    )
    try:
        service = ConversationFolderService(
            folder_repository=persistence.conversation_folder_repository,
            conversation_repository=persistence.conversation_repository,
        )
        folder = service.create_folder("Rollback")
        persistence.conversation_repository.create("c1", title="Keep")
        service.set_conversation_folder("c1", folder.id)
        with persistence.database.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER fail_folder_delete BEFORE DELETE ON conversation_folders "
                "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
            )
        with pytest.raises(PersistenceError):
            service.delete_folder(folder.id)
        assert persistence.conversation_folder_repository.get(folder.id) == folder
        assert persistence.conversation_repository.get("c1").folder_id == folder.id  # type: ignore[union-attr]
    finally:
        persistence.dispose()


def test_restart_preserves_folder_assignment_and_delete(tmp_path: Path) -> None:
    path = str(tmp_path / "restart.sqlite3")
    settings = Settings(persistence_provider="relational", persistence_database_url=path)
    persistence = create_application_persistence(settings)
    service = ConversationFolderService(
        folder_repository=persistence.conversation_folder_repository,
        conversation_repository=persistence.conversation_repository,
    )
    folder = service.create_folder("Durable X")
    folder_y = service.create_folder("Durable Y")
    persistence.conversation_repository.create("c1", title="Durable conversation")
    service.set_conversation_folder("c1", folder.id)
    persistence.dispose()
    reopened = create_application_persistence(settings)
    try:
        assert reopened.conversation_folder_repository.get(folder.id) == folder
        assert reopened.conversation_repository.get("c1").folder_id == folder.id  # type: ignore[union-attr]
        reopened_service = ConversationFolderService(
            folder_repository=reopened.conversation_folder_repository,
            conversation_repository=reopened.conversation_repository,
        )
        reopened_service.set_conversation_folder("c1", folder_y.id)
    finally:
        reopened.dispose()
    reopened = create_application_persistence(settings)
    try:
        assert reopened.conversation_repository.get("c1").folder_id == folder_y.id  # type: ignore[union-attr]
        reopened_service = ConversationFolderService(
            folder_repository=reopened.conversation_folder_repository,
            conversation_repository=reopened.conversation_repository,
        )
        reopened_service.set_conversation_folder("c1", None)
    finally:
        reopened.dispose()
    reopened = create_application_persistence(settings)
    try:
        assert reopened.conversation_folder_repository.get(folder.id) == folder
        assert reopened.conversation_repository.get("c1").folder_id is None  # type: ignore[union-attr]
    finally:
        reopened.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_folder_conversation_creation_is_atomic_and_adapter_consistent(provider: str, tmp_path: Path) -> None:
    database_url = str(tmp_path / f"create-{provider}.sqlite3")
    settings = Settings(persistence_provider=provider, persistence_database_url=database_url)
    persistence = create_application_persistence(settings)
    folder = ConversationFolderService(
        folder_repository=persistence.conversation_folder_repository,
        conversation_repository=persistence.conversation_repository,
    ).create_folder("Atomic create")
    conversations = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        folder_repository=persistence.conversation_folder_repository,
    )
    try:
        created = conversations.create_conversation(folder_id=folder.id)
        ungrouped = conversations.create_conversation()
        assert created.conversation_id
        assert created.project_id is None and created.folder_id == folder.id
        assert ungrouped.project_id is None and ungrouped.folder_id is None
        persisted = persistence.conversation_repository.get(created.conversation_id)
        assert persisted is not None
        assert (persisted.conversation_id, persisted.project_id, persisted.folder_id) == (
            created.conversation_id, None, folder.id
        )
        if provider == "relational":
            persistence.dispose()
            persistence = create_application_persistence(settings)
            persisted_after_restart = persistence.conversation_repository.get(created.conversation_id)
            assert persisted_after_restart is not None
            assert (persisted_after_restart.conversation_id, persisted_after_restart.project_id,
                    persisted_after_restart.folder_id) == (created.conversation_id, None, folder.id)
    finally:
        persistence.dispose()


def test_legacy_v10_database_migrates_without_reset(tmp_path: Path) -> None:
    path = str(tmp_path / "legacy.sqlite3")
    db = SqliteDatabase(path, auto_migrate=False)
    registry = default_registry()
    from ava.infrastructure.persistence.migrations.registry import MigrationRegistry

    pre_folder_registry = MigrationRegistry()
    for migration in registry:
        if migration.version <= 10:
            pre_folder_registry.register(migration)
    MigrationRunner(db, pre_folder_registry).migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO conversations (conversation_id, title, created_at, updated_at) "
            "VALUES ('legacy', 'Legacy', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    db.dispose()
    migrated = SqliteDatabase(path)
    try:
        with migrated.connect() as connection:
            folder_id, project_id = connection.execute(
                "SELECT folder_id, project_id FROM conversations WHERE conversation_id = 'legacy'"
            ).fetchone()
            version = connection.execute(
                "SELECT version FROM ava_schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()[0]
            assert folder_id is None and project_id is None and version == 25
            assert connection.execute("SELECT 1 FROM conversation_folders").fetchone() is None
    finally:
        migrated.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
@pytest.mark.asyncio
async def test_folder_crud_and_assignment_api(provider: str, tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider=provider, persistence_database_url=str(tmp_path / f"api-{provider}.sqlite3")
        )
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created_conversation = (await client.post("/conversations", json={"title": "API"})).json()
            created = await client.post("/conversation-folders", json={"name": "  Engineering  "})
            assert created.status_code == 201 and created.json()["name"] == "Engineering"
            folder_id = created.json()["id"]
            created_in_folder = await client.post("/conversations", json={"folder_id": folder_id})
            assert created_in_folder.status_code == 201
            assert created_in_folder.json()["folder_id"] == folder_id
            assert created_in_folder.json()["project_id"] is None
            explicit_ungrouped = await client.post("/conversations", json={"folder_id": None})
            assert explicit_ungrouped.status_code == 201
            assert explicit_ungrouped.json()["folder_id"] is None
            missing_folder_create = await client.post("/conversations", json={"folder_id": "missing"})
            assert missing_folder_create.status_code == 404
            assert missing_folder_create.json()["error_code"] == "conversation_folder_not_found"
            assert (await client.get("/conversation-folders")).json()["folders"][0]["id"] == folder_id
            assert (await client.get(f"/conversation-folders/{folder_id}")).status_code == 200
            renamed = await client.patch(f"/conversation-folders/{folder_id}", json={"name": "Platform"})
            assert renamed.json()["name"] == "Platform"
            assigned = await client.patch(
                f"/conversations/{created_conversation['conversation_id']}/folder", json={"folder_id": folder_id}
            )
            assert assigned.status_code == 200 and assigned.json()["folder_id"] == folder_id
            unassigned = await client.patch(
                f"/conversations/{created_conversation['conversation_id']}/folder", json={"folder_id": None}
            )
            assert unassigned.json()["folder_id"] is None
            missing = await client.patch(
                f"/conversations/{created_conversation['conversation_id']}/folder", json={"folder_id": "missing"}
            )
            assert missing.status_code == 404 and missing.json()["error_code"] == "conversation_folder_not_found"
            missing_conversation = await client.patch("/conversations/missing/folder", json={"folder_id": folder_id})
            assert missing_conversation.status_code == 404
            assert missing_conversation.json()["error_code"] == "conversation_not_found"
            blank_name = await client.post("/conversation-folders", json={"name": "   "})
            assert blank_name.status_code == 422
            deleted = await client.delete(f"/conversation-folders/{folder_id}")
            assert deleted.status_code == 204 and deleted.content == b""
            assert (await client.delete("/conversation-folders/missing")).json()[
                "error_code"
            ] == "conversation_folder_not_found"
    finally:
        app.state.persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
@pytest.mark.asyncio
async def test_move_api_atomically_replaces_folder_and_project_membership(provider: str, tmp_path: Path) -> None:
    app = create_app(settings=Settings(
        persistence_provider=provider,
        persistence_database_url=str(tmp_path / f"move-{provider}.sqlite3"),
    ))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            folder_a = (await client.post("/conversation-folders", json={"name": "Folder A"})).json()["id"]
            folder_b = (await client.post("/conversation-folders", json={"name": "Folder B"})).json()["id"]
            project_a = (await client.post("/projects", json={"name": "Project A"})).json()["id"]
            project_b = (await client.post("/projects", json={"name": "Project B"})).json()["id"]
            conversation = (
                await client.post("/conversations", json={"title": "Move test", "folder_id": folder_a})
            ).json()
            conversation_id = conversation["conversation_id"]
            # Seed the prior Project relationship to prove the move clears stale dual membership.
            app.state.conversation_service.set_project(conversation_id, project_a)

            async def move(destination_type: str, destination_id: str | None = None) -> dict[str, object]:
                response = await client.patch(f"/conversations/{conversation_id}/move", json={
                    "destination_type": destination_type,
                    "destination_id": destination_id,
                })
                assert response.status_code == 200
                result = response.json()
                persisted = app.state.persistence.conversation_repository.get(conversation_id)
                assert persisted is not None
                assert (persisted.folder_id, persisted.project_id) == (result["folder_id"], result["project_id"])
                return result

            moved = await move("folder", folder_b)
            assert (moved["folder_id"], moved["project_id"]) == (folder_b, None)
            moved = await move("project", project_b)
            assert (moved["folder_id"], moved["project_id"]) == (None, project_b)
            moved = await move("project", project_a)
            assert (moved["folder_id"], moved["project_id"]) == (None, project_a)
            moved = await move("ungrouped")
            assert (moved["folder_id"], moved["project_id"]) == (None, None)
            moved = await move("project", project_b)
            assert (moved["folder_id"], moved["project_id"]) == (None, project_b)
            moved = await move("folder", folder_a)
            assert (moved["folder_id"], moved["project_id"]) == (folder_a, None)
            moved = await move("ungrouped")
            assert (moved["folder_id"], moved["project_id"]) == (None, None)
            active = (await client.get("/conversations")).json()["conversations"]
            active_item = next(item for item in active if item["conversation_id"] == conversation_id)
            assert (active_item["folder_id"], active_item["project_id"]) == (None, None)
            project_a_items = (await client.get(f"/projects/{project_a}/conversations")).json()["conversations"]
            project_b_items = (await client.get(f"/projects/{project_b}/conversations")).json()["conversations"]
            assert conversation_id not in {item["conversation_id"] for item in project_a_items}
            assert conversation_id not in {item["conversation_id"] for item in project_b_items}
    finally:
        app.state.persistence.dispose()
