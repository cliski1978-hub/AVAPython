"""Phase 5.62 Project conversation query, creation, and route behavior."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ava.api.routes.projects import create_project_conversation, list_project_conversations
from ava.api.routes.projects import router as project_router
from ava.configuration.settings import Settings
from ava.contracts.conversations import CreateConversationRequest
from ava.infrastructure.composition import create_application_persistence
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.migrations.runner import MigrationRunner
from ava.infrastructure.persistence.migrations.versions import default_registry
from ava.services.conversation_service import ConversationService
from ava.services.project_service import ProjectNotFoundError, ProjectService


def test_project_conversation_routes_are_registered_with_create_status() -> None:
    routes = [route for route in project_router.routes if route.path == "/projects/{project_id}/conversations"]
    assert {method for route in routes for method in route.methods} == {"GET", "POST"}
    create_route = next(route for route in routes if "POST" in route.methods)
    assert create_route.status_code == 201


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_conversation_create_list_and_route_semantics(provider: str, tmp_path: Path) -> None:
    database_path = tmp_path / f"{provider}.sqlite3"
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(database_path))
    )
    projects = ProjectService(project_repository=persistence.project_repository)
    conversations = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        project_repository=persistence.project_repository,
    )
    try:
        project = projects.create_project(name="Workspace")
        other = projects.create_project(name="Other")
        archived_project = projects.set_archived(project.id, True)
        assert archived_project.is_archived

        app = SimpleNamespace(state=SimpleNamespace(project_service=projects, conversation_service=conversations))
        request = SimpleNamespace(app=app)
        missing_list = asyncio.run(list_project_conversations(request, "missing"))
        assert missing_list.status_code == 404
        assert json.loads(missing_list.body)["error_code"] == "project_not_found"
        empty_list = asyncio.run(list_project_conversations(request, other.id))
        assert empty_list.conversations == []
        before_missing_create = len(persistence.conversation_repository.list())
        missing_create = asyncio.run(
            create_project_conversation(request, "missing", CreateConversationRequest(title="Must not exist"))
        )
        assert missing_create.status_code == 404
        assert json.loads(missing_create.body)["error_code"] == "project_not_found"
        assert len(persistence.conversation_repository.list()) == before_missing_create

        created = asyncio.run(
            create_project_conversation(
                request,
                project.id,
                CreateConversationRequest(title="  In project  "),
            )
        )
        # Direct handler invocation is used because this application's startup
        # lifespan can stall under Starlette TestClient in the current test env.
        assert created.title == "In project"
        assert created.project_id == project.id
        assert created.title == "In project"
        assert created.is_pinned is False
        assert created.is_archived is False
        assert created.folder_id is None
        assert created.created_at == created.updated_at

        second = conversations.create_conversation_in_project(project.id, title="Second")
        assert persistence.conversation_repository.set_pinned(second.conversation_id, True) is not None
        assert persistence.conversation_repository.set_archived(created.conversation_id, True) is not None
        assert persistence.conversation_repository.set_folder(created.conversation_id, "folder-kept") is not None
        outsider = conversations.create_conversation_in_project(other.id, title="Other project")
        unassigned = conversations.create_conversation(title="Unassigned")

        result = asyncio.run(list_project_conversations(request, project.id))
        assert [item.conversation_id for item in result.conversations] == [
            second.conversation_id,
            created.conversation_id,
        ]
        by_id = {item.conversation_id: item for item in result.conversations}
        assert by_id[created.conversation_id].is_archived is True
        assert by_id[created.conversation_id].folder_id == "folder-kept"
        assert by_id[created.conversation_id].project_id == project.id
        assert outsider.conversation_id not in by_id
        assert unassigned.conversation_id not in by_id

        # Archived Project listing and creation are supported under the existing
        # informational archive convention.
        assert projects.get_project(project.id).is_archived is True
        assert len(result.conversations) == 2

        if provider == "relational":
            database = SqliteDatabase(str(database_path))
            with database.connect() as connection:
                row = connection.execute(
                    "SELECT project_id FROM conversations WHERE conversation_id = ?",
                    (created.conversation_id,),
                ).fetchone()
            assert row["project_id"] == project.id

        before_count = len(persistence.conversation_repository.list())
        with pytest.raises(ProjectNotFoundError):
            conversations.create_conversation_in_project("missing", "Must not exist")
        assert len(persistence.conversation_repository.list()) == before_count

        projects.delete_project(project.id)
        deleted_project_list = asyncio.run(list_project_conversations(request, project.id))
        assert deleted_project_list.status_code == 404
        assert json.loads(deleted_project_list.body)["error_code"] == "project_not_found"
        # Project deletion preserves conversations and clears their relationship.
        surviving = persistence.conversation_repository.get(created.conversation_id)
        assert surviving is not None and surviving.project_id is None
    finally:
        persistence.dispose()


def test_project_conversation_membership_survives_relational_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "restart.sqlite3"
    settings = Settings(persistence_provider="relational", persistence_database_url=str(database_path))
    first = create_application_persistence(settings)
    project = ProjectService(project_repository=first.project_repository).create_project(name="Durable")
    service = ConversationService(
        conversation_repository=first.conversation_repository,
        message_repository=first.message_repository,
        project_repository=first.project_repository,
    )
    created = service.create_conversation_in_project(project.id)
    conversation_id = created.conversation_id
    assert created.project_id == project.id
    first.dispose()

    restarted = create_application_persistence(settings)
    try:
        loaded = restarted.conversation_repository.get(conversation_id)
        assert loaded is not None
        assert loaded.project_id == project.id
        assert loaded.title == "New Conversation"
    finally:
        restarted.dispose()


def test_project_conversation_routes_work_after_startup_upgrades_schema_12_database(tmp_path: Path) -> None:
    """Reproduce the live DB shape: Project exists, but conversation membership is pre-migration."""
    database_path = tmp_path / "live-schema-12.sqlite3"
    legacy_database = SqliteDatabase(str(database_path), auto_migrate=False)
    through_12 = MigrationRegistry()
    for migration in default_registry():
        if migration.version <= 12:
            through_12.register(migration)
    assert MigrationRunner(legacy_database, through_12).migrate() == list(range(1, 13))
    with legacy_database.transaction() as connection:
        connection.execute(
            "INSERT INTO projects (id, name, description, instructions, is_archived, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("project-live", "Project 1", "Existing project", None, 0, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO conversations "
            "(conversation_id, title, created_at, updated_at, is_pinned, is_archived, folder_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "conversation-pre-relationship",
                "Existing chat",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                0,
                0,
                None,
            ),
        )
    legacy_database.dispose()

    persistence = create_application_persistence(
        Settings(persistence_provider="relational", persistence_database_url=str(database_path))
    )
    projects = ProjectService(project_repository=persistence.project_repository)
    conversations = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        project_repository=persistence.project_repository,
    )
    try:
        app = SimpleNamespace(state=SimpleNamespace(project_service=projects, conversation_service=conversations))
        request = SimpleNamespace(app=app)
        assert projects.get_project("project-live").name == "Project 1"
        preserved = persistence.conversation_repository.get("conversation-pre-relationship")
        assert preserved is not None and preserved.project_id is None

        listed = asyncio.run(list_project_conversations(request, "project-live"))
        assert listed.conversations == []
        created = asyncio.run(
            create_project_conversation(request, "project-live", CreateConversationRequest(title="Recovered chat"))
        )
        assert created.title == "Recovered chat"
        assert created.project_id == "project-live"
        assert created.folder_id is None

        with persistence.database.connect() as connection:
            schema_version = connection.execute("SELECT MAX(version) FROM ava_schema_migrations").fetchone()[0]
            stored_project_id = connection.execute(
                "SELECT project_id FROM conversations WHERE conversation_id = ?",
                (created.conversation_id,),
            ).fetchone()[0]
            old_chat_count = connection.execute(
                "SELECT COUNT(*) FROM conversations WHERE conversation_id = ?",
                ("conversation-pre-relationship",),
            ).fetchone()[0]
        assert schema_version == 21
        assert stored_project_id == "project-live"
        assert old_chat_count == 1
    finally:
        persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_repository_order_matches_canonical_order(provider: str, tmp_path: Path) -> None:
    database_path = tmp_path / f"order-{provider}.sqlite3"
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(database_path))
    )
    try:
        project = ProjectService(project_repository=persistence.project_repository).create_project(name="Ordered")
        other = ProjectService(project_repository=persistence.project_repository).create_project(name="Other")
        records = {
            identity: persistence.conversation_repository.create(
                identity,
                title=identity,
                project_id=project.id,
            )
            for identity in ("pinned-old", "recent-update", "created-new", "created-old", "tie-z", "tie-a")
        }
        persistence.conversation_repository.create("other-project", title="Other", project_id=other.id)
        persistence.conversation_repository.create("unassigned", title="Unassigned")

        timestamps = {
            "pinned-old": ("2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00", True),
            "recent-update": ("2024-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00", False),
            "created-new": ("2025-01-02T00:00:00+00:00", "2025-01-01T00:00:00+00:00", False),
            "created-old": ("2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00", False),
            "tie-z": ("2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00", False),
            "tie-a": ("2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00", False),
        }
        if provider == "relational":
            database = SqliteDatabase(str(database_path))
            with database.transaction() as connection:
                for identity, (created_at, updated_at, pinned) in timestamps.items():
                    connection.execute(
                        "UPDATE conversations SET created_at = ?, updated_at = ?, is_pinned = ? "
                        "WHERE conversation_id = ?",
                        (created_at, updated_at, int(pinned), identity),
                    )
        else:
            for identity, (created_at, updated_at, pinned) in timestamps.items():
                persistence.conversation_repository._conversations[identity] = replace(
                    records[identity],
                    created_at=datetime.fromisoformat(created_at).astimezone(UTC),
                    updated_at=datetime.fromisoformat(updated_at).astimezone(UTC),
                    is_pinned=pinned,
                )

        assert [item.conversation_id for item in persistence.conversation_repository.list_by_project(project.id)] == [
            "pinned-old",
            "recent-update",
            "created-new",
            "created-old",
            "tie-a",
            "tie-z",
        ]
    finally:
        persistence.dispose()
