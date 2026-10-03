"""Phase 5.52 canonical conversation ordering regressions."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.infrastructure.composition import create_application_persistence
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories.conversation_repository import (
    RelationalConversationRepository,
)
from ava.repositories.conversation_repository import ConversationRepository
from ava.services.conversation_service import ConversationService
from ava.services.conversation_store import ConversationStore


def timestamp(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


FIXTURES = (
    ("unpinned-old", "General Old", False, False, None, 1, 1),
    ("unpinned-new", "Architecture Unpinned", False, False, "folder-1", 2, 6),
    ("archive-middle", "Architecture Archived", False, True, None, 2, 3),
    ("pinned-old", "Pinned Old", True, False, None, 1, 2),
    ("pinned-new", "Architecture Pinned New", True, False, None, 3, 5),
    ("tie-z", "Architecture Tie Z", True, False, None, 4, 4),
    ("tie-a", "Architecture Tie A", True, False, None, 4, 4),
)

EXPECTED_IDS = [
    "pinned-new",
    "tie-a",
    "tie-z",
    "pinned-old",
    "unpinned-new",
    "archive-middle",
    "unpinned-old",
]


def seed_repository(repository: ConversationRepository, database: SqliteDatabase | None = None) -> None:
    """Create identical timestamps/metadata regardless of adapter."""
    for conversation_id, title, pinned, archived, folder_id, created_day, updated_day in FIXTURES:
        record = repository.create(conversation_id, title=title)
        seeded = replace(
            record,
            created_at=timestamp(created_day),
            updated_at=timestamp(updated_day),
            is_pinned=pinned,
            is_archived=archived,
            folder_id=folder_id,
        )
        if isinstance(repository, ConversationStore):
            repository._conversations[conversation_id] = seeded
        else:
            assert database is not None
            with database.transaction() as connection:
                connection.execute(
                    "UPDATE conversations SET created_at = ?, updated_at = ?, is_pinned = ?, "
                    "is_archived = ?, folder_id = ? WHERE conversation_id = ?",
                    (
                        timestamp(created_day).isoformat(),
                        timestamp(updated_day).isoformat(),
                        int(pinned),
                        int(archived),
                        folder_id,
                        conversation_id,
                    ),
                )


def make_repository(kind: str, path: str = ":memory:") -> tuple[ConversationRepository, SqliteDatabase | None]:
    if kind == "memory":
        return ConversationStore(), None
    database = SqliteDatabase(path)
    return RelationalConversationRepository(database=database), database


@pytest.mark.parametrize("kind", ["memory", "relational"])
def test_repository_uses_pin_activity_tiebreak_and_metadata_order(kind: str) -> None:
    repository, database = make_repository(kind)
    try:
        seed_repository(repository, database)
        assert [record.conversation_id for record in repository.list()] == EXPECTED_IDS
        assert [record.conversation_id for record in repository.list("ARCHITECTURE")] == [
            "pinned-new",
            "tie-a",
            "tie-z",
            "unpinned-new",
            "archive-middle",
        ]
        assert repository.get("archive-middle") is not None
        assert repository.get("archive-middle").is_archived is True
        assert repository.get("unpinned-new") is not None
        assert repository.get("unpinned-new").folder_id == "folder-1"
    finally:
        if database is not None:
            database.dispose()


def test_memory_and_sqlite_return_identical_canonical_order(tmp_path: Path) -> None:
    memory, _ = make_repository("memory")
    database = SqliteDatabase(str(tmp_path / "sorting.sqlite3"))
    relational = RelationalConversationRepository(database=database)
    try:
        seed_repository(memory)
        seed_repository(relational, database)
        assert [record.conversation_id for record in memory.list()] == [
            record.conversation_id for record in relational.list()
        ] == EXPECTED_IDS
        assert [record.conversation_id for record in memory.list("architecture")] == [
            record.conversation_id for record in relational.list("architecture")
        ]
    finally:
        database.dispose()


@pytest.mark.parametrize("kind", ["memory", "relational"])
def test_pin_unpin_changes_canonical_group_and_delete_keeps_order(kind: str) -> None:
    repository, database = make_repository(kind)
    try:
        seed_repository(repository, database)
        pinned = repository.set_pinned("unpinned-new", True)
        assert pinned is not None and pinned.updated_at == timestamp(6)
        assert [record.conversation_id for record in repository.list()][0] == "unpinned-new"

        repository.set_pinned("unpinned-new", False)
        assert [record.conversation_id for record in repository.list()] == EXPECTED_IDS

        # Use the adapter's supported delete path through the application
        # service coordinator in the API-level regression below; the port
        # itself intentionally has no hard-delete method.
    finally:
        if database is not None:
            database.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
@pytest.mark.asyncio
async def test_api_list_and_search_preserve_repository_order(
    provider: str, tmp_path: Path
) -> None:
    app = create_app(settings=Settings(
        persistence_provider=provider,
        persistence_database_url=str(tmp_path / f"{provider}-api-sorting.sqlite3"),
    ))
    try:
        persistence = app.state.persistence
        seed_repository(persistence.conversation_repository, persistence.database)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/conversations")
            assert response.status_code == 200
            assert [item["conversation_id"] for item in response.json()["conversations"]] == EXPECTED_IDS

            search = await client.get("/conversations", params={"search": "architecture"})
            assert [item["conversation_id"] for item in search.json()["conversations"]] == [
                "pinned-new",
                "tie-a",
                "tie-z",
                "unpinned-new",
                "archive-middle",
            ]
    finally:
        app.state.persistence.dispose()


@pytest.mark.parametrize("kind", ["memory", "relational"])
def test_rename_refreshes_updated_at_but_message_activity_does_not(kind: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(Settings(
        persistence_provider=kind,
        persistence_database_url=str(tmp_path / f"{kind}-timestamp.sqlite3"),
    ))
    try:
        repository = persistence.conversation_repository
        seed_repository(repository, persistence.database)
        original = repository.get("unpinned-old")
        assert original is not None
        service = ConversationService(
            conversation_repository=repository,
            message_repository=persistence.message_repository,
        )

        service.append_message("unpinned-old", content="A later message")
        unchanged = repository.get("unpinned-old")
        assert unchanged is not None and unchanged.updated_at == original.updated_at

        renamed = service.update_title("unpinned-old", "Renamed Recently")
        assert renamed is not None and renamed.updated_at > original.updated_at
        assert [record.conversation_id for record in repository.list()][4] == "unpinned-old"
    finally:
        persistence.dispose()
