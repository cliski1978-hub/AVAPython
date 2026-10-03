"""Phase 5.61 conversation/Project membership behavior across adapters."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ava.api.routes.conversations import set_conversation_project
from ava.configuration.settings import Settings
from ava.contracts.conversations import SetConversationProjectRequest
from ava.contracts.responses import RunStatus
from ava.infrastructure.composition import create_application_persistence
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.errors import PersistenceError
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.migrations.runner import MigrationRunner
from ava.infrastructure.persistence.migrations.versions import default_registry
from ava.services.conversation_service import ConversationService
from ava.services.project_service import ProjectService


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_assignment_move_unassign_preserve_folder_activity_and_other_metadata(provider: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}.sqlite3"))
    )
    conversations = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        run_repository=persistence.run_repository,
        project_repository=persistence.project_repository,
    )
    projects = ProjectService(project_repository=persistence.project_repository)
    try:
        first_project = projects.create_project(name="Project A")
        second_project = projects.create_project(name="Project B")
        conversation = conversations.create_conversation(title="Metadata stays")
        # Folder assignment uses the normal folder service contract at the adapter boundary.
        from ava.services.conversation_folder_service import ConversationFolderService

        folders = ConversationFolderService(
            folder_repository=persistence.conversation_folder_repository,
            conversation_repository=persistence.conversation_repository,
        )
        folder_record = folders.create_folder("Folder A")
        folder_b = folders.create_folder("Folder B")
        conversations.set_pinned(conversation.conversation_id, True)
        conversations.set_archived(conversation.conversation_id, True)
        folders.set_conversation_folder(conversation.conversation_id, folder_record.id)
        before = persistence.conversation_repository.get(conversation.conversation_id)
        assert before is not None
        active = persistence.run_repository.create(
            "project-assignment-run", conversation_id=conversation.conversation_id
        )
        assert active.status is RunStatus.PENDING

        assigned_a = conversations.set_project(conversation.conversation_id, first_project.id)
        assert assigned_a is not None
        assert assigned_a.project_id == first_project.id
        assert assigned_a.folder_id == folder_record.id
        assert assigned_a.updated_at == before.updated_at
        assert assigned_a.title == before.title
        assert assigned_a.is_pinned is True and assigned_a.is_archived is True
        assert persistence.run_repository.get(active.run_id) == active

        assigned_b = conversations.set_project(conversation.conversation_id, second_project.id)
        assert assigned_b is not None and assigned_b.project_id == second_project.id
        assert assigned_b.updated_at == before.updated_at
        direct = persistence.conversation_repository.get(conversation.conversation_id)
        assert direct is not None and direct.project_id == second_project.id

        # Cross-Folder and ungrouped writes preserve the independent Project reference.
        moved_folder = folders.set_conversation_folder(conversation.conversation_id, folder_b.id)
        assert moved_folder.folder_id == folder_b.id
        assert moved_folder.project_id == second_project.id
        folders.set_conversation_folder(conversation.conversation_id, None)
        after_folder_clear = persistence.conversation_repository.get(conversation.conversation_id)
        assert after_folder_clear is not None
        assert after_folder_clear.folder_id is None
        assert after_folder_clear.project_id == second_project.id

        renamed = conversations.update_title(conversation.conversation_id, "Renamed while assigned")
        assert renamed is not None and renamed.project_id == second_project.id
        unpinned = conversations.set_pinned(conversation.conversation_id, False)
        assert unpinned is not None and unpinned.project_id == second_project.id
        restored = conversations.set_archived(conversation.conversation_id, False)
        assert restored is not None and restored.project_id == second_project.id
        before_unassign = persistence.conversation_repository.get(conversation.conversation_id)
        assert before_unassign is not None

        unassigned = conversations.set_project(conversation.conversation_id, None)
        assert unassigned is not None and unassigned.project_id is None
        assert unassigned.folder_id is None
        assert unassigned.updated_at == before_unassign.updated_at
        # Repeating unassignment is idempotent.
        assert conversations.set_project(conversation.conversation_id, None) == unassigned
    finally:
        persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_assignment_rejects_missing_project_and_missing_conversation(provider: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}-missing.sqlite3"))
    )
    conversations = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        project_repository=persistence.project_repository,
    )
    try:
        existing = conversations.create_conversation(title="Existing")
        assert conversations.set_project("missing", None) is None
        from ava.services.project_service import ProjectNotFoundError

        with pytest.raises(ProjectNotFoundError, match="Unknown Project"):
            conversations.set_project(existing.conversation_id, "missing-project")
    finally:
        persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_archive_and_delete_preserve_conversation_membership_safely(provider: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}-delete.sqlite3"))
    )
    projects = ProjectService(project_repository=persistence.project_repository)
    conversations = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        project_repository=persistence.project_repository,
    )
    try:
        project = projects.create_project(name="Workspace")
        conversation = conversations.create_conversation(title="Keep me")
        conversations.append_message(conversation.conversation_id, content="Message stays")
        conversations.set_project(conversation.conversation_id, project.id)
        conversations.set_archived(conversation.conversation_id, True)
        archived = projects.set_archived(project.id, True)
        assert archived.is_archived is True
        assert persistence.conversation_repository.get(conversation.conversation_id).project_id == project.id  # type: ignore[union-attr]

        projects.delete_project(project.id)
        retained = persistence.conversation_repository.get(conversation.conversation_id)
        assert retained is not None
        assert retained.conversation_id == conversation.conversation_id
        assert retained.project_id is None
        assert retained.is_archived is True
        assert [item.content for item in conversations.list_messages(conversation.conversation_id).messages] == [
            "Message stays"
        ]
        assert persistence.project_repository.get(project.id) is None
    finally:
        persistence.dispose()


def test_relational_project_delete_cleanup_rolls_back_atomically_on_failure(tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider="relational", persistence_database_url=str(tmp_path / "rollback.sqlite3"))
    )
    projects = ProjectService(project_repository=persistence.project_repository)
    conversations = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        project_repository=persistence.project_repository,
    )
    try:
        project = projects.create_project(name="Rollback")
        conversation = conversations.create_conversation(title="Still assigned")
        conversations.set_project(conversation.conversation_id, project.id)
        assert persistence.database is not None
        with persistence.database.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER fail_project_delete BEFORE DELETE ON projects "
                "BEGIN SELECT unregistered_project_delete_failure(); END"
            )
        with pytest.raises(PersistenceError):
            projects.delete_project(project.id)
        assert persistence.project_repository.get(project.id) == project
        restored = persistence.conversation_repository.get(conversation.conversation_id)
        assert restored is not None and restored.project_id == project.id
    finally:
        persistence.dispose()


def test_project_assignment_move_and_unassign_survive_relational_restarts(tmp_path: Path) -> None:
    settings = Settings(persistence_provider="relational", persistence_database_url=str(tmp_path / "restart.sqlite3"))
    first = create_application_persistence(settings)
    projects = ProjectService(project_repository=first.project_repository)
    conversations = ConversationService(
        conversation_repository=first.conversation_repository,
        message_repository=first.message_repository,
        project_repository=first.project_repository,
    )
    project_a = projects.create_project(name="A")
    project_b = projects.create_project(name="B")
    conversation = conversations.create_conversation(title="Durable relationship")
    conversations.set_project(conversation.conversation_id, project_a.id)
    conversations.set_project(conversation.conversation_id, project_b.id)
    first.dispose()

    second = create_application_persistence(settings)
    try:
        loaded = second.conversation_repository.get(conversation.conversation_id)
        assert loaded is not None and loaded.project_id == project_b.id
        second_service = ConversationService(
            conversation_repository=second.conversation_repository,
            message_repository=second.message_repository,
            project_repository=second.project_repository,
        )
        second_service.set_project(conversation.conversation_id, None)
        with second.database.connect() as connection:  # type: ignore[union-attr]
            row = connection.execute(
                "SELECT project_id FROM conversations WHERE conversation_id = ?",
                (conversation.conversation_id,),
            ).fetchone()
            assert row["project_id"] is None
    finally:
        second.dispose()

    third = create_application_persistence(settings)
    try:
        loaded = third.conversation_repository.get(conversation.conversation_id)
        assert loaded is not None and loaded.project_id is None
    finally:
        third.dispose()


def test_project_delete_cleanup_survives_relational_restart_without_deleting_conversation(tmp_path: Path) -> None:
    settings = Settings(
        persistence_provider="relational", persistence_database_url=str(tmp_path / "delete-restart.sqlite3")
    )
    first = create_application_persistence(settings)
    projects = ProjectService(project_repository=first.project_repository)
    conversations = ConversationService(
        conversation_repository=first.conversation_repository,
        message_repository=first.message_repository,
        project_repository=first.project_repository,
    )
    project = projects.create_project(name="Delete with membership")
    conversation = conversations.create_conversation(title="Survives project delete")
    conversations.set_project(conversation.conversation_id, project.id)
    projects.delete_project(project.id)
    first.dispose()

    second = create_application_persistence(settings)
    try:
        loaded = second.conversation_repository.get(conversation.conversation_id)
        assert loaded is not None and loaded.project_id is None
        assert second.project_repository.get(project.id) is None
        with second.database.connect() as connection:  # type: ignore[union-attr]
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        second.dispose()


def test_v0013_migrates_existing_v0012_conversations_without_changing_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "v12.sqlite3"
    database = SqliteDatabase(str(database_path), auto_migrate=False)
    through_12 = MigrationRegistry()
    for migration in default_registry():
        if migration.version <= 12:
            through_12.register(migration)
    assert MigrationRunner(database, through_12).migrate() == list(range(1, 13))
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO conversation_folders (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("folder-old", "Existing folder", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("project-old", "Existing project", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO conversations "
            "(conversation_id, title, created_at, updated_at, is_pinned, is_archived, folder_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "conversation-old",
                "Existing conversation",
                "2026-01-01T00:00:00+00:00",
                "2026-01-02T00:00:00+00:00",
                1,
                1,
                "folder-old",
            ),
        )
        connection.execute(
            "INSERT INTO messages (message_id, conversation_id, role, status, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "message-old",
                "conversation-old",
                "user",
                "complete",
                "preserve me",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("run-old", "completed", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO run_events (event_id, run_id, event_type, seq, timestamp, payload, contract_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("event-old", "run-old", "run_started", 0, "2026-01-01T00:00:00+00:00", "{}", "v1"),
        )
        connection.execute(
            "INSERT INTO attachments "
            "(attachment_id, file_name, media_type, size_bytes, storage_key, owner_type, owner_id, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "attachment-old",
                "old.txt",
                "text/plain",
                4,
                "storage-old",
                "conversation",
                "conversation-old",
                "available",
                "2026-01-01T00:00:00+00:00",
            ),
        )
    assert MigrationRunner(database, default_registry()).migrate() == [13, 14, 15, 16, 17, 18]
    assert MigrationRunner(database, default_registry()).migrate() == []
    with database.connect() as connection:
        row = connection.execute(
            "SELECT title, created_at, updated_at, is_pinned, is_archived, folder_id, project_id "
            "FROM conversations WHERE conversation_id = ?",
            ("conversation-old",),
        ).fetchone()
        assert row[:] == (
            "Existing conversation",
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
            1,
            1,
            "folder-old",
            None,
        )
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM runs WHERE run_id = 'run-old'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM run_events WHERE event_id = 'event-old'").fetchone()[0] == 1
        attachment_count = connection.execute(
            "SELECT COUNT(*) FROM attachments WHERE attachment_id = 'attachment-old'"
        ).fetchone()[0]
        assert attachment_count == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            connection.execute("SELECT name FROM conversation_folders WHERE id = 'folder-old'").fetchone()[0]
            == "Existing folder"
        )
        assert (
            connection.execute("SELECT name FROM projects WHERE id = 'project-old'").fetchone()[0] == "Existing project"
        )
    database.dispose()


def test_assignment_route_returns_typed_relationship_and_errors(tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider="relational", persistence_database_url=str(tmp_path / "api.sqlite3"))
    )
    project_service = ProjectService(project_repository=persistence.project_repository)
    conversation_service = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        project_repository=persistence.project_repository,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(conversation_service=conversation_service)))
    try:
        project = project_service.create_project(name="API project")
        conversation = conversation_service.create_conversation(title="API conversation")
        path_id = conversation.conversation_id
        assigned = asyncio.run(
            set_conversation_project(request, path_id, SetConversationProjectRequest(project_id=project.id))
        )
        assert assigned.project_id == project.id
        assert assigned.folder_id is None
        missing_project = asyncio.run(
            set_conversation_project(request, path_id, SetConversationProjectRequest(project_id="missing"))
        )
        assert missing_project.status_code == 404
        assert json.loads(missing_project.body)["error_code"] == "project_not_found"
        unassigned = asyncio.run(
            set_conversation_project(request, path_id, SetConversationProjectRequest(project_id=None))
        )
        assert unassigned.project_id is None
        missing_conversation = asyncio.run(
            set_conversation_project(request, "missing", SetConversationProjectRequest(project_id=None))
        )
        assert missing_conversation.status_code == 404
        assert json.loads(missing_conversation.body)["error_code"] == "conversation_not_found"
    finally:
        persistence.dispose()
