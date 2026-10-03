"""Title-only conversation search parity and public API coverage."""

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories.conversation_repository import (
    RelationalConversationRepository,
)
from ava.repositories.conversation_repository import ConversationRepository
from ava.services.conversation_store import ConversationStore


@pytest.mark.parametrize("repository_kind", ["memory", "relational"])
def test_title_search_filters_case_insensitively_and_preserves_order(repository_kind: str) -> None:
    database = SqliteDatabase()
    repository: ConversationRepository = (
        ConversationStore()
        if repository_kind == "memory"
        else RelationalConversationRepository(database=database)
    )
    try:
        repository.create("first", title="Architecture Review")
        repository.create("second", title="Planning architecture changes")
        repository.create("third", title="Unrelated")
        repository.create("fourth", title="An ARCHITECTURE guide")

        assert [record.conversation_id for record in repository.list(" architecture ")] == [
            "fourth",
            "second",
            "first",
        ]
        assert [record.conversation_id for record in repository.list("REVIEW")] == ["first"]
        assert repository.list("absent") == []
        assert [record.conversation_id for record in repository.list()] == [
            "fourth",
            "third",
            "second",
            "first",
        ]
        assert repository.list("") == repository.list("   ") == repository.list()
    finally:
        database.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_search_api_is_title_only_keeps_metadata_and_reflects_renames(
    provider: str, tmp_path: Path
) -> None:
    settings = Settings(
        persistence_provider=provider,
        persistence_database_url=str(tmp_path / f"{provider}.sqlite3"),
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        created = [
            client.post("/conversations", json={"title": title}).json()
            for title in (
                "Architecture Review",
                "Planning architecture changes",
                "Unrelated",
                "Message only",
                "Delete me later",
                "Café & Tea?",
            )
        ]
        first, second, _, message_only, deleted, encoded = created

        assert client.patch(
            f"/conversations/{first['conversation_id']}/pin", json={"is_pinned": True}
        ).status_code == 200
        assert client.patch(
            f"/conversations/{first['conversation_id']}/archive", json={"is_archived": True}
        ).status_code == 200

        if provider == "memory":
            repository = app.state.persistence.conversation_repository
            repository._conversations[second["conversation_id"]] = replace(
                repository.get(second["conversation_id"]), folder_id="folder-7"
            )
        else:
            with app.state.persistence.database.transaction() as connection:
                connection.execute(
                    "UPDATE conversations SET folder_id = 'folder-7' WHERE conversation_id = ?",
                    (second["conversation_id"],),
                )

        assert client.post(
            f"/conversations/{message_only['conversation_id']}/messages",
            json={"content": "Architecture appears in this message, not the title"},
        ).status_code == 201
        assert client.delete(f"/conversations/{deleted['conversation_id']}").status_code == 204

        all_items = client.get("/conversations").json()["conversations"]
        assert client.get("/conversations?search=").json()["conversations"] == all_items
        assert client.get("/conversations?search=%20%20").json()["conversations"] == all_items

        response = client.get("/conversations", params={"search": " ARCHITECTURE "})
        assert response.status_code == 200
        matches = response.json()["conversations"]
        assert [item["conversation_id"] for item in matches] == [
            first["conversation_id"],
            second["conversation_id"],
        ]
        assert matches[0]["is_pinned"] is True
        assert matches[0]["is_archived"] is True
        assert matches[1]["folder_id"] == "folder-7"
        assert all(
            {
                "conversation_id",
                "title",
                "created_at",
                "updated_at",
                "is_pinned",
                "is_archived",
                "folder_id",
                "contract_version",
            }
            <= item.keys()
            for item in matches
        )
        assert client.get("/conversations?search=message").json()["conversations"] == [
            item for item in all_items if item["conversation_id"] == message_only["conversation_id"]
        ]
        assert client.get("/conversations?search=Delete%20me").json()["conversations"] == []
        assert client.patch(
            f"/conversations/{first['conversation_id']}", json={"title": "Renamed Architecture"}
        ).status_code == 200
        assert client.get("/conversations?search=Review").json()["conversations"] == []
        assert len(client.get("/conversations?search=Renamed").json()["conversations"]) == 1
        encoded_result = client.get("/conversations", params={"search": "fé & tea?"})
        assert [item["conversation_id"] for item in encoded_result.json()["conversations"]] == [
            encoded["conversation_id"]
        ]
