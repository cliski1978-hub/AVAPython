"""Conversation title ownership across API writes and database reopen."""

import asyncio
from pathlib import Path

import httpx

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories.conversation_repository import RelationalConversationRepository
from ava.infrastructure.persistence.repositories.message_repository import RelationalMessageRepository
from ava.services.conversation_service import ConversationService


def make_service(database: SqliteDatabase) -> ConversationService:
    return ConversationService(
        conversation_repository=RelationalConversationRepository(database=database),
        message_repository=RelationalMessageRepository(database=database),
    )


def test_manual_title_survives_first_message_later_activity_and_reload(tmp_path: Path) -> None:
    database_path = str(tmp_path / "manual-title.sqlite3")
    database = SqliteDatabase(database_path)
    service = make_service(database)
    created = service.create_conversation()
    conversation_id = created.conversation_id
    renamed = service.update_title(conversation_id, "My Custom Title")
    assert renamed is not None and renamed.is_title_custom is True
    database.dispose()

    reopened_database = SqliteDatabase(database_path)
    try:
        reloaded_service = make_service(reopened_database)
        manual_title = reloaded_service.get_conversation(conversation_id)
        assert manual_title is not None and manual_title.is_title_custom is True
        reloaded_service.append_message(conversation_id, content="Explain dependency injection")
        reloaded_service.append_message(conversation_id, content="Give me a small example")
        current = reloaded_service.get_conversation(conversation_id)
        assert current is not None and current.title == "My Custom Title"
    finally:
        reopened_database.dispose()

    after_activity_database = SqliteDatabase(database_path)
    try:
        after_activity = make_service(after_activity_database).get_conversation(conversation_id)
        assert after_activity is not None
        assert after_activity.title == "My Custom Title"
        assert after_activity.is_title_custom is True
    finally:
        after_activity_database.dispose()


def test_untouched_conversation_is_auto_titled_by_first_message_and_reload(tmp_path: Path) -> None:
    database_path = str(tmp_path / "automatic-title.sqlite3")
    database = SqliteDatabase(database_path)
    service = make_service(database)
    created = service.create_conversation()
    conversation_id = created.conversation_id

    service.append_message(conversation_id, content="  Explain   dependency injection  ")
    titled = service.get_conversation(conversation_id)
    assert titled is not None
    assert titled.title == "Explain dependency injection"
    assert titled.is_title_custom is False

    service.append_message(conversation_id, content="Give me a small example")
    database.dispose()

    reopened_database = SqliteDatabase(database_path)
    try:
        reloaded = make_service(reopened_database).get_conversation(conversation_id)
        assert reloaded is not None
        assert reloaded.title == "Explain dependency injection"
        assert reloaded.is_title_custom is False
    finally:
        reopened_database.dispose()


def test_api_keeps_a_manual_title_when_the_first_message_is_posted() -> None:
    async def exercise_api() -> None:
        app = create_app(settings=Settings(persistence_provider="memory"))
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://ava.test"
            ) as client:
                created = await client.post("/conversations", json={})
                assert created.status_code == 201
                conversation_id = created.json()["conversation_id"]

                renamed = await client.patch(
                    f"/conversations/{conversation_id}", json={"title": "My Custom Title"}
                )
                assert renamed.status_code == 200
                assert renamed.json()["is_title_custom"] is True

                posted = await client.post(
                    f"/conversations/{conversation_id}/messages",
                    json={"content": "Explain dependency injection"},
                )
                assert posted.status_code == 201
                reloaded = await client.get(f"/conversations/{conversation_id}")
                assert reloaded.json()["title"] == "My Custom Title"
                assert reloaded.json()["is_title_custom"] is True
        finally:
            app.state.persistence.dispose()

    asyncio.run(exercise_api())
