"""Phase 5.67 memory/SQLite parity and durability coverage."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from ava.contracts.core_prompts import CreateCorePromptRequest, UpdateCorePromptRequest
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories.core_prompt_repository import RelationalCorePromptRepository
from ava.repositories.core_prompt import CorePromptCategory, CorePromptRecord
from ava.services.core_prompt_service import (
    CorePromptNotFoundError,
    CorePromptService,
    InvalidCorePromptTextError,
)
from ava.services.core_prompt_store import CorePromptStore


@pytest.fixture(params=["memory", "sqlite"])
def service(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "memory":
        yield CorePromptService(core_prompt_repository=CorePromptStore())
        return
    database = SqliteDatabase(str(tmp_path / "core-prompts.sqlite3"))
    yield CorePromptService(core_prompt_repository=RelationalCorePromptRepository(database=database))
    database.dispose()


def _create_request(
    *,
    name: str = "  Engineering  ",
    description: str | None = "Optional metadata",
    prompt_text: str = "  # Rules\n\n- Keep  exact spacing\n- 日本語 → 🧭\n",
    category: CorePromptCategory = CorePromptCategory.ENGINEERING,
) -> CreateCorePromptRequest:
    return CreateCorePromptRequest(
        name=name,
        description=description,
        prompt_text=prompt_text,
        category=category,
    )


def test_repository_and_service_crud_validation_nullable_text_and_ordering(service: CorePromptService) -> None:
    first = service.create_core_prompt(_create_request())
    duplicate_name = service.create_core_prompt(
        _create_request(description="", prompt_text="Second prompt", category=CorePromptCategory.CORE)
    )
    assert first.name == "Engineering"
    assert first.prompt_text == "  # Rules\n\n- Keep  exact spacing\n- 日本語 → 🧭\n"
    assert first.description == "Optional metadata"
    assert first.category is CorePromptCategory.ENGINEERING
    assert first.is_enabled is True
    assert UUID(first.id).version == 4
    assert first.created_at == first.updated_at and first.created_at.tzinfo is UTC
    assert duplicate_name.name == first.name
    assert duplicate_name.description == ""
    disabled_duplicate = service.set_enabled(duplicate_name.id, False)
    assert [item.category for item in service.list_core_prompts()] == [
        CorePromptCategory.CORE,
        CorePromptCategory.ENGINEERING,
    ]
    assert service.list_core_prompts()[0].is_enabled is False
    assert service.get_core_prompt(first.id) == first
    assert service.get_core_prompt(duplicate_name.id) == disabled_duplicate

    with pytest.raises(ValidationError, match="name must not be blank"):
        _create_request(name=" \n ")
    with pytest.raises(ValidationError, match="prompt_text must not be blank"):
        _create_request(prompt_text=" \t\n")


def test_update_preserves_identity_creation_enabled_and_omitted_vs_null_description(service: CorePromptService) -> None:
    original = service.create_core_prompt(_create_request())
    omitted_description = UpdateCorePromptRequest(
        name=" Updated ",
        prompt_text="  New\n  body  ",
        category=CorePromptCategory.RESEARCH,
    )
    updated = service.update_core_prompt(original.id, omitted_description)
    assert updated.id == original.id
    assert updated.created_at == original.created_at
    assert updated.is_enabled is True
    assert updated.name == "Updated"
    assert updated.prompt_text == "  New\n  body  "
    assert updated.description == "Optional metadata"
    assert updated.category is CorePromptCategory.RESEARCH
    assert updated.updated_at > original.updated_at

    cleared = service.update_core_prompt(
        original.id,
        UpdateCorePromptRequest(
            name="Updated",
            description=None,
            prompt_text="not blank",
            category=CorePromptCategory.STYLE,
        ),
    )
    assert cleared.description is None
    empty = service.update_core_prompt(
        original.id,
        UpdateCorePromptRequest(
            name="Updated",
            description="",
            prompt_text="not blank",
            category=CorePromptCategory.STYLE,
        ),
    )
    assert empty.description == ""


def test_enable_disable_is_idempotent_and_delete_is_permanent(service: CorePromptService) -> None:
    prompt = service.create_core_prompt(_create_request())
    disabled = service.set_enabled(prompt.id, False)
    assert disabled.is_enabled is False
    assert disabled.updated_at > prompt.updated_at
    repeated_disable = service.set_enabled(prompt.id, False)
    assert repeated_disable == disabled
    assert repeated_disable.updated_at == disabled.updated_at
    enabled = service.set_enabled(prompt.id, True)
    assert enabled.is_enabled is True
    assert enabled.updated_at > disabled.updated_at
    service.delete_core_prompt(prompt.id)
    with pytest.raises(CorePromptNotFoundError):
        service.get_core_prompt(prompt.id)
    with pytest.raises(CorePromptNotFoundError):
        service.delete_core_prompt(prompt.id)
    with pytest.raises(CorePromptNotFoundError):
        service.set_enabled(prompt.id, False)
    with pytest.raises(CorePromptNotFoundError):
        service.update_core_prompt(
            prompt.id,
            UpdateCorePromptRequest(name="Missing", prompt_text="text", category=CorePromptCategory.CORE),
        )


def test_create_and_update_do_not_allow_blank_prompt_text(service: CorePromptService) -> None:
    prompt = service.create_core_prompt(_create_request())
    with pytest.raises(ValidationError):
        service.create_core_prompt(_create_request(prompt_text="\n\t"))
    with pytest.raises(ValidationError):
        UpdateCorePromptRequest(name="Name", prompt_text=" ", category=CorePromptCategory.CORE)
    malformed_create = CreateCorePromptRequest.model_construct(
        name="Name", description=None, prompt_text=" \n ", category=CorePromptCategory.CORE
    )
    with pytest.raises(InvalidCorePromptTextError):
        service.create_core_prompt(malformed_create)
    malformed_update = UpdateCorePromptRequest.model_construct(
        name="Name", description=None, prompt_text=" \n ", category=CorePromptCategory.CORE
    )
    with pytest.raises(InvalidCorePromptTextError):
        service.update_core_prompt(prompt.id, malformed_update)
    assert service.get_core_prompt(prompt.id) == prompt


def test_repository_ordering_uses_casefold_creation_time_then_id(service: CorePromptService) -> None:
    repository = service._prompts
    base = datetime(2026, 1, 2, tzinfo=UTC)
    records = [
        ("z", "Alpha", CorePromptCategory.STYLE, base),
        ("b", "alpha", CorePromptCategory.STYLE, base),
        ("a", "ALPHA", CorePromptCategory.STYLE, base),
        ("earlier", "alpha", CorePromptCategory.STYLE, base.replace(day=1, hour=0)),
        ("core", "Zulu", CorePromptCategory.CORE, base),
    ]
    for prompt_id, name, category, created_at in records:
        repository.create(
            CorePromptRecord(
                id=prompt_id,
                name=name,
                description=None,
                prompt_text="Content",
                category=category,
                is_enabled=True,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    assert [item.id for item in repository.list()] == ["core", "earlier", "a", "b", "z"]


def test_sqlite_direct_rows_and_restart_durability(tmp_path: Path) -> None:
    path = tmp_path / "core-prompt-restart.sqlite3"
    first_database = SqliteDatabase(str(path))
    first_service = CorePromptService(core_prompt_repository=RelationalCorePromptRepository(database=first_database))
    original = first_service.create_core_prompt(_create_request())
    updated = first_service.update_core_prompt(
        original.id,
        UpdateCorePromptRequest(
            name="Renamed",
            description="Metadata\n多言語",
            prompt_text="  ## Exact\n\n- line 1\n    code = True  ",
            category=CorePromptCategory.ARCHITECTURE,
        ),
    )
    disabled = first_service.set_enabled(updated.id, False)
    with first_database.connect() as connection:
        row = connection.execute(
            "SELECT id, name, description, prompt_text, category, is_enabled, created_at, updated_at "
            "FROM core_prompts WHERE id = ?",
            (disabled.id,),
        ).fetchone()
        assert row["name"] == "Renamed"
        assert row["description"] == "Metadata\n多言語"
        assert row["prompt_text"] == "  ## Exact\n\n- line 1\n    code = True  "
        assert row["category"] == "architecture"
        assert row["is_enabled"] == 0
        assert row["created_at"] == original.created_at.isoformat()
        assert row["updated_at"] == disabled.updated_at.isoformat()
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        enabled_column = next(
            item for item in connection.execute("PRAGMA table_info(core_prompts)") if item["name"] == "is_enabled"
        )
        assert enabled_column["dflt_value"] == "1"
        scope_columns = {
            "scope_type",
            "scope_id",
            "project_id",
            "folder_id",
            "conversation_id",
            "application_id",
            "runtime_id",
            "capability_id",
            "provider_id",
            "model_id",
            "priority",
            "inheritance_mode",
        }
        actual_columns = {item["name"] for item in connection.execute("PRAGMA table_info(core_prompts)")}
        assert scope_columns.isdisjoint(actual_columns)
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='core_prompt_assignments'"
            ).fetchone()
            is not None
        )
    first_database.dispose()

    reopened_database = SqliteDatabase(str(path))
    reopened_service = CorePromptService(
        core_prompt_repository=RelationalCorePromptRepository(database=reopened_database)
    )
    reloaded = reopened_service.get_core_prompt(disabled.id)
    assert reloaded == disabled
    reopened_service.delete_core_prompt(disabled.id)
    reopened_database.dispose()

    final_database = SqliteDatabase(str(path))
    final_service = CorePromptService(core_prompt_repository=RelationalCorePromptRepository(database=final_database))
    with pytest.raises(CorePromptNotFoundError):
        final_service.get_core_prompt(disabled.id)
    final_database.dispose()


def test_relational_reader_rejects_unknown_persisted_category(tmp_path: Path) -> None:
    database = SqliteDatabase(str(tmp_path / "invalid-category.sqlite3"))
    repository = RelationalCorePromptRepository(database=database)
    now = datetime.now(UTC).isoformat()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO core_prompts "
            "(id, name, description, prompt_text, category, is_enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("bad-category", "Unknown", None, "Text", "future-value", 1, now, now),
        )
    with pytest.raises(ValueError, match="future-value"):
        repository.get("bad-category")
    database.dispose()
