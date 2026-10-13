"""Phase 5.43 storage, migration, restart, and public read regressions."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.migrations.runner import MigrationRunner
from ava.infrastructure.persistence.migrations.versions import default_registry
from ava.infrastructure.persistence.repositories.conversation_repository import RelationalConversationRepository
from ava.infrastructure.persistence.serialization import row_to_conversation_record
from ava.repositories.conversation_repository import ConversationRecord
from ava.services.conversation_store import ConversationStore


def assert_metadata(record: ConversationRecord | None, pinned: bool, archived: bool, folder: str | None) -> None:
    assert record is not None
    assert (record.is_pinned, record.is_archived, record.folder_id) == (pinned, archived, folder)


@pytest.mark.parametrize("mode", ["memory", "relational"])
@pytest.mark.parametrize("metadata", [(True, True, "folder-123"), (True, False, None), (False, True, "folder-x")])
def test_repository_defaults_round_trip_and_rename(mode: str, metadata: tuple[bool, bool, str | None]) -> None:
    database = SqliteDatabase()
    store = ConversationStore()
    repository = store if mode == "memory" else RelationalConversationRepository(database=database)
    try:
        first = repository.create("first", title="First")
        created = repository.create("organized", title="Original")
        assert_metadata(created, False, False, None)
        assert_metadata(repository.get("organized"), False, False, None)
        pinned, archived, folder = metadata
        if mode == "memory":
            store._conversations["organized"] = replace(
                created, is_pinned=pinned, is_archived=archived, folder_id=folder
            )
        else:
            with database.transaction() as connection:
                row = connection.execute(
                    "SELECT is_pinned, is_archived, folder_id FROM conversations WHERE conversation_id = 'organized'"
                ).fetchone()
                assert tuple(row) == (0, 0, None)
                # No public organization writer exists yet; seed storage directly.
                connection.execute(
                    "UPDATE conversations SET is_pinned = ?, is_archived = ?, folder_id = ? "
                    "WHERE conversation_id = 'organized'", metadata,
                )
        assert_metadata(repository.get("organized"), *metadata)
        listing = list(repository.list())
        assert [record.conversation_id for record in listing] == ["organized", first.conversation_id]
        assert_metadata(listing[0], *metadata)
        renamed = repository.update_title("organized", "Renamed")
        assert renamed is not None and renamed.title == "Renamed"
        assert_metadata(renamed, *metadata)
        assert_metadata(repository.get("organized"), *metadata)
        assert_metadata(list(repository.list())[0], *metadata)
    finally:
        database.dispose()


def test_restart_and_api_reads_preserve_metadata_and_rename(tmp_path: Path) -> None:
    path = str(tmp_path / "organization.sqlite3")
    database = SqliteDatabase(path)
    repository = RelationalConversationRepository(database=database)
    repository.create("first", title="First")
    repository.create("organized", title="Original")
    with database.transaction() as connection:
        connection.execute(
            "UPDATE conversations SET is_pinned = 1, is_archived = 1, folder_id = 'folder-x' "
            "WHERE conversation_id = 'organized'"
        )
    database.dispose()

    settings = Settings(persistence_provider="relational", persistence_database_url=path)
    with TestClient(create_app(settings=settings)) as client:
        single = client.get("/conversations/organized")
        listing = client.get("/conversations")
        renamed = client.patch("/conversations/organized", json={"title": "Renamed"})
        assert single.status_code == listing.status_code == renamed.status_code == 200
        assert [item["conversation_id"] for item in listing.json()["conversations"]] == ["organized", "first"]
        for body in (single.json(), listing.json()["conversations"][0], renamed.json()):
            assert body["is_pinned"] is True
            assert body["is_archived"] is True
            assert body["folder_id"] == "folder-x"
        assert renamed.json()["title"] == "Renamed"

    reopened = SqliteDatabase(path)
    try:
        loaded = RelationalConversationRepository(database=reopened).get("organized")
        assert_metadata(loaded, True, True, "folder-x")
        assert loaded is not None and loaded.title == "Renamed"
        assert_metadata(RelationalConversationRepository(database=reopened).get("first"), False, False, None)
    finally:
        reopened.dispose()


def test_pre_543_database_migrates_without_reset_and_startup_is_idempotent(tmp_path: Path) -> None:
    path = str(tmp_path / "legacy.sqlite3")
    legacy = SqliteDatabase(path, auto_migrate=False)
    registry = MigrationRegistry()
    for migration in default_registry():
        if migration.version <= 9:
            registry.register(migration)
    MigrationRunner(legacy, registry).migrate()
    with legacy.transaction() as connection:
        assert "is_pinned" not in [row["name"] for row in connection.execute("PRAGMA table_info(conversations)")]
        connection.execute(
            "INSERT INTO conversations (conversation_id, title, created_at, updated_at) "
            "VALUES ('legacy', 'Keep me', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    legacy.dispose()

    for _ in range(2):
        database = SqliteDatabase(path)
        try:
            record = RelationalConversationRepository(database=database).get("legacy")
            assert_metadata(record, False, False, None)
            assert record is not None and record.title == "Keep me" and record.conversation_id == "legacy"
            runner = MigrationRunner(database, default_registry())
            assert runner.current_version() == 25
            assert runner.migrate() == []
            assert [entry.version for entry in runner.applied_migrations()] == list(range(1, 26))
            with database.connect() as connection:
                columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(conversations)")}
                for name in ("is_pinned", "is_archived"):
                    assert columns[name]["type"] == "INTEGER"
                    assert columns[name]["notnull"] == 1
                    assert columns[name]["dflt_value"] == "0"
                assert columns["folder_id"]["type"] == "TEXT"
                assert columns["folder_id"]["notnull"] == 0
                assert connection.execute("PRAGMA foreign_key_list(conversations)").fetchall() == []
                assert tuple(connection.execute(
                    "SELECT is_pinned, is_archived, folder_id FROM conversations"
                ).fetchone()) == (0, 0, None)
        finally:
            database.dispose()


def test_legacy_row_mapper_defaults_missing_fields() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT 'legacy' AS conversation_id, 'Old' AS title, "
            "'2026-01-01T00:00:00+00:00' AS created_at, '2026-01-01T00:00:00+00:00' AS updated_at"
        ).fetchone()
        assert_metadata(row_to_conversation_record(row), False, False, None)
