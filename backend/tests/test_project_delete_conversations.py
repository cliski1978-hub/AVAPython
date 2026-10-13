"""Optional Project conversation deletion reuses the conversation hard-delete lifecycle."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ava.api.routes.projects import delete_project as delete_project_route
from ava.configuration.settings import Settings
from ava.infrastructure.composition import create_application_persistence, create_conversation_hard_delete_coordinator
from ava.services.conversation_folder_service import ConversationFolderService
from ava.services.conversation_service import ConversationService
from ava.services.project_service import ProjectService


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_delete_preserves_conversations_by_default_and_preserves_folder_links(
    provider: str, tmp_path: Path
) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}.sqlite3"))
    )
    conversations = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
        hard_delete_coordinator=create_conversation_hard_delete_coordinator(persistence),
        project_repository=persistence.project_repository,
        folder_repository=persistence.conversation_folder_repository,
    )
    projects = ProjectService(
        project_repository=persistence.project_repository,
        delete_project_conversations=conversations.delete_project_conversations,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(project_service=projects)))
    try:
        project = projects.create_project(name="Keep conversations")
        empty_project = projects.create_project(name="Empty Project")
        folder_service = ConversationFolderService(
            folder_repository=persistence.conversation_folder_repository,
            conversation_repository=persistence.conversation_repository,
        )
        folder = folder_service.create_folder("Keep this Folder")
        kept = conversations.create_conversation_in_project(project.id, title="Keep me")
        folder_service.set_conversation_folder(kept.conversation_id, folder.id)
        deleted_project = projects.create_project(name="Delete conversations")
        removed = conversations.create_conversation_in_project(deleted_project.id, title="Remove me")
        folder_service.set_conversation_folder(removed.conversation_id, folder.id)
        unrelated = conversations.create_conversation(title="Unrelated")

        default_response = asyncio.run(delete_project_route(request, project.id))
        assert default_response.status_code == 204
        empty_response = asyncio.run(delete_project_route(request, empty_project.id, delete_conversations=True))
        assert empty_response.status_code == 200
        assert json.loads(empty_response.body)["deleted_conversation_ids"] == []
        assert persistence.project_repository.get(empty_project.id) is None
        kept_after = persistence.conversation_repository.get(kept.conversation_id)
        assert kept_after is not None and kept_after.project_id is None and kept_after.folder_id == folder.id
        assert persistence.conversation_folder_repository.get(folder.id) == folder

        response = asyncio.run(delete_project_route(request, deleted_project.id, delete_conversations=True))
        assert response.status_code == 200
        assert json.loads(response.body)["deleted_conversation_ids"] == [removed.conversation_id]
        assert persistence.project_repository.get(deleted_project.id) is None
        assert persistence.conversation_repository.get(removed.conversation_id) is None
        assert persistence.conversation_repository.get(unrelated.conversation_id) is not None
        assert persistence.conversation_folder_repository.get(folder.id) == folder
    finally:
        persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_delete_with_active_project_conversation_fails_without_deleting_either(
    provider: str, tmp_path: Path
) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}.sqlite3"))
    )
    conversations = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
        hard_delete_coordinator=create_conversation_hard_delete_coordinator(persistence),
        project_repository=persistence.project_repository,
    )
    projects = ProjectService(
        project_repository=persistence.project_repository,
        delete_project_conversations=conversations.delete_project_conversations,
    )
    try:
        project = projects.create_project(name="Busy Project")
        chat = conversations.create_conversation_in_project(project.id, title="Active")
        first = conversations.create_conversation_in_project(project.id, title="Would otherwise be removed first")
        persistence.run_repository.create("active-project-run", conversation_id=chat.conversation_id)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(project_service=projects)))
        response = asyncio.run(delete_project_route(request, project.id, delete_conversations=True))
        assert response.status_code == 409
        assert json.loads(response.body)["error_code"] == "conversation_run_active"
        assert persistence.project_repository.get(project.id) is not None
        assert persistence.conversation_repository.get(first.conversation_id) is not None
        assert persistence.conversation_repository.get(chat.conversation_id) is not None
    finally:
        persistence.dispose()
