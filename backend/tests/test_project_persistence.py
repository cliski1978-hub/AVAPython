"""Phase 5.57 Project repository, migration, and durability tests."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ava.configuration.settings import Settings
from ava.infrastructure.composition import create_application_persistence
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.migrations.runner import MigrationRunner
from ava.infrastructure.persistence.migrations.versions import default_registry
from ava.repositories.project import ProjectRecord


def _project(
    project_id: str,
    name: str,
    *,
    created_at: datetime | None = None,
    description: str | None = None,
    instructions: str | None = None,
    is_archived: bool = False,
) -> ProjectRecord:
    created = created_at or datetime(2026, 10, 1, tzinfo=UTC)
    return ProjectRecord(
        id=project_id,
        name=name,
        created_at=created,
        updated_at=created,
        description=description,
        instructions=instructions,
        is_archived=is_archived,
    )


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_project_repository_create_get_list_update_and_not_found(provider: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(
        Settings(persistence_provider=provider, persistence_database_url=str(tmp_path / f"{provider}.sqlite3"))
    )
    repository = persistence.project_repository
    first = _project("p-1", "Beta", description=None, instructions=None)
    second = _project(
        "p-2",
        "beta",
        created_at=datetime(2026, 9, 30, tzinfo=UTC),
        description="",
        instructions="Keep this text",
    )
    third = _project("p-3", "Alpha", is_archived=True)
    fourth = _project("p-4", "Gamma", instructions="Project-only data")
    try:
        assert repository.create(first) == first
        assert repository.create(second) == second
        assert repository.create(third) == third
        assert repository.create(fourth) == fourth
        with pytest.raises(ValueError, match="already exists"):
            repository.create(first)

        assert repository.get(first.id) == first
        assert repository.get("missing") is None
        assert [item.id for item in repository.list()] == ["p-2", "p-1", "p-4", "p-3"]
        assert repository.update(_project("missing", "Unknown")) is None

        updated_at = datetime(2026, 10, 3, tzinfo=UTC)
        updated = replace(
            first,
            name="Omega",
            description="",
            instructions="Preserved exactly",
            is_archived=True,
            updated_at=updated_at,
        )
        assert repository.update(updated) == updated
        assert repository.get(first.id) == updated
        assert updated.created_at == first.created_at
        assert repository.get(second.id) == second  # empty description and text instructions are unchanged
    finally:
        persistence.dispose()


def test_memory_and_sqlite_project_repository_parity(tmp_path: Path) -> None:
    settings = [
        Settings(persistence_provider="memory"),
        Settings(persistence_provider="relational", persistence_database_url=str(tmp_path / "parity.sqlite3")),
    ]
    repositories = [create_application_persistence(item) for item in settings]
    fixtures = [
        _project("p-b", "Beta", instructions=""),
        _project("p-a", "beta", created_at=datetime(2026, 9, 30, tzinfo=UTC), description=""),
        _project(
            "p-z",
            "Alpha",
            instructions="Use UTF-8. Prefer → over =>. 日本語 test\n- Keep this line.",
            is_archived=True,
        ),
    ]
    try:
        for persistence in repositories:
            repository = persistence.project_repository
            for project in fixtures:
                repository.create(project)
        memory, relational = (item.project_repository for item in repositories)

        assert list(memory.list()) == list(relational.list())
        for project in fixtures:
            assert memory.get(project.id) == relational.get(project.id) == project
        assert memory.get("missing") is relational.get("missing") is None
        assert [item.id for item in memory.list()] == ["p-a", "p-b", "p-z"]

        updated = replace(
            fixtures[0],
            name="Beta updated",
            description="Now present",
            instructions=(
                "You are working on AVA.\n\nRules:\n- Preserve architecture boundaries.\n- Keep indentation:   exact."
            ),
            is_archived=True,
            updated_at=datetime(2026, 10, 4, tzinfo=UTC),
        )
        assert memory.update(updated) == relational.update(updated) == updated
        assert memory.get(updated.id) == relational.get(updated.id) == updated
        assert list(memory.list()) == list(relational.list())

        assert memory.delete(updated.id) is relational.delete(updated.id) is True
        assert memory.delete(updated.id) is relational.delete(updated.id) is False
        assert memory.get(updated.id) is relational.get(updated.id) is None
        assert list(memory.list()) == list(relational.list())
        assert [item.id for item in memory.list()] == ["p-a", "p-z"]
    finally:
        for persistence in repositories:
            persistence.dispose()


@pytest.mark.parametrize(
    "instructions",
    [None, "", "First line\n  - indented\n\nLast line", "→ 日本語 — café"],
)
def test_project_instruction_values_round_trip_and_match_direct_sqlite_values(
    instructions: str | None, tmp_path: Path
) -> None:
    memory = create_application_persistence(Settings(persistence_provider="memory"))
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(
            tmp_path / f"instructions-{instructions is None}-{len(instructions or '')}.sqlite3"
        ),
    )
    relational = create_application_persistence(settings)
    project = _project("instructions", "Instruction values", instructions=instructions)
    try:
        assert memory.project_repository.create(project) == project
        assert relational.project_repository.create(project) == project
        assert memory.project_repository.get(project.id) == relational.project_repository.get(project.id) == project
        with relational.database.connect() as connection:  # type: ignore[union-attr]
            row = connection.execute("SELECT instructions FROM projects WHERE id = ?", (project.id,)).fetchone()
            assert row[0] == instructions
    finally:
        memory.dispose()
        relational.dispose()


def test_sqlite_project_create_and_update_survive_restart(tmp_path: Path) -> None:
    database_path = str(tmp_path / "project-restart.sqlite3")
    settings = Settings(persistence_provider="relational", persistence_database_url=database_path)
    created = _project(
        "p-durable",
        "Durable Project",
        description="",
        instructions="Stored, not executed",
        is_archived=True,
    )
    persistence = create_application_persistence(settings)
    try:
        persistence.project_repository.create(created)
        with persistence.database.connect() as connection:  # type: ignore[union-attr]
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (created.id,)).fetchone()
            assert tuple(row) == (
                created.id,
                created.name,
                "",
                created.instructions,
                1,
                created.created_at.isoformat(),
                created.updated_at.isoformat(),
                None,
                None,
            )
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        persistence.dispose()

    reopened = create_application_persistence(settings)
    try:
        assert reopened.project_repository.get(created.id) == created

        updated_at = datetime(2026, 10, 5, tzinfo=UTC)
        updated = replace(
            created,
            name="Renamed Durable Project",
            description="Description update",
            instructions=None,
            is_archived=False,
            updated_at=updated_at,
        )
        assert reopened.project_repository.update(updated) == updated
    finally:
        reopened.dispose()

    after_update = create_application_persistence(settings)
    try:
        assert after_update.project_repository.get(created.id) == updated
        assert after_update.project_repository.get(created.id).created_at == created.created_at  # type: ignore[union-attr]
    finally:
        after_update.dispose()


def test_sqlite_project_instruction_update_and_clear_survive_restart(tmp_path: Path) -> None:
    database_path = str(tmp_path / "project-instructions-restart.sqlite3")
    settings = Settings(persistence_provider="relational", persistence_database_url=database_path)
    original_text = "Initial instructions"
    updated_text = "Use UTF-8 →\n\nRules:\n  - 日本語\n  - Preserve spaces."
    created = _project(
        "p-instructions-durable",
        "Instructions Project",
        description="Keep description",
        instructions=original_text,
        is_archived=True,
    )
    first = create_application_persistence(settings)
    try:
        assert first.project_repository.create(created) == created
        update = replace(created, instructions=updated_text, updated_at=datetime(2026, 10, 5, tzinfo=UTC))
        assert first.project_repository.update(update) == update
        with first.database.connect() as connection:  # type: ignore[union-attr]
            assert (
                connection.execute("SELECT instructions FROM projects WHERE id = ?", (created.id,)).fetchone()[0]
                == updated_text
            )
    finally:
        first.dispose()

    reopened = create_application_persistence(settings)
    try:
        assert reopened.project_repository.get(created.id) == update
        cleared = replace(update, instructions=None, updated_at=datetime(2026, 10, 6, tzinfo=UTC))
        assert reopened.project_repository.update(cleared) == cleared
    finally:
        reopened.dispose()

    after_clear = create_application_persistence(settings)
    try:
        assert after_clear.project_repository.get(created.id) == cleared
        with after_clear.database.connect() as connection:  # type: ignore[union-attr]
            assert (
                connection.execute("SELECT instructions FROM projects WHERE id = ?", (created.id,)).fetchone()[0]
                is None
            )
    finally:
        after_clear.dispose()


def test_v0012_migrates_legacy_v0011_data_and_repeated_startup_is_safe(tmp_path: Path) -> None:
    database_path = str(tmp_path / "legacy-v11.sqlite3")
    database = SqliteDatabase(database_path, auto_migrate=False)
    pre_project = MigrationRegistry()
    for migration in default_registry():
        if migration.version <= 11:
            pre_project.register(migration)
    runner = MigrationRunner(database, pre_project)
    assert runner.migrate() == list(range(1, 12))
    assert runner.current_version() == 11
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO conversation_folders (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("folder-old", "Existing folder", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO conversations (conversation_id, title, created_at, updated_at, folder_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "conversation-old",
                "Existing conversation",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "folder-old",
            ),
        )
    database.dispose()

    settings = Settings(persistence_provider="relational", persistence_database_url=database_path)
    for _ in range(2):
        persistence = create_application_persistence(settings)
        try:
            assert persistence.project_repository.list() == []
            assert persistence.conversation_repository.get("conversation-old") is not None
            assert persistence.conversation_folder_repository.get("folder-old") is not None
            migrated = MigrationRunner(persistence.database, default_registry())  # type: ignore[arg-type]
            assert migrated.current_version() == 25
            assert migrated.migrate() == []
            with persistence.database.connect() as connection:  # type: ignore[union-attr]
                conversation_row = connection.execute(
                    "SELECT title, folder_id, project_id FROM conversations WHERE conversation_id = ?",
                    ("conversation-old",),
                ).fetchone()
                assert conversation_row[:] == ("Existing conversation", "folder-old", None)
                folder_row = connection.execute(
                    "SELECT name FROM conversation_folders WHERE id = ?", ("folder-old",)
                ).fetchone()
                assert folder_row[0] == "Existing folder"
                columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(projects)")}
                assert list(columns) == [
                    "id",
                    "name",
                    "description",
                    "instructions",
                    "is_archived",
                    "created_at",
                    "updated_at",
                    "default_runtime_key",
                    "default_model_id",
                ]
                assert columns["is_archived"]["type"] == "INTEGER"
                assert columns["is_archived"]["notnull"] == 1
                assert columns["is_archived"]["dflt_value"] == "0"
                assert columns["id"]["pk"] == 1
                assert columns["name"]["type"] == "TEXT" and columns["name"]["notnull"] == 1
                for name in ("description", "instructions"):
                    assert columns[name]["type"] == "TEXT" and columns[name]["notnull"] == 0
                for name in ("created_at", "updated_at"):
                    assert columns[name]["type"] == "TEXT" and columns[name]["notnull"] == 1
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            persistence.dispose()
