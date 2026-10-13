"""Phase 5.68 explicit assignment state, target validation, and cleanup."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from ava.contracts.core_prompts import CreateCorePromptRequest
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.migrations.runner import MigrationRunner
from ava.infrastructure.persistence.migrations.versions import default_registry
from ava.infrastructure.persistence.repositories.conversation_folder_repository import (
    RelationalConversationFolderRepository,
)
from ava.infrastructure.persistence.repositories.conversation_hard_delete_coordinator import (
    RelationalConversationHardDeleteCoordinator,
)
from ava.infrastructure.persistence.repositories.conversation_repository import RelationalConversationRepository
from ava.infrastructure.persistence.repositories.core_prompt_assignment_repository import (
    RelationalCorePromptAssignmentRepository,
)
from ava.infrastructure.persistence.repositories.core_prompt_repository import RelationalCorePromptRepository
from ava.infrastructure.persistence.repositories.project_repository import RelationalProjectRepository
from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.repositories.core_prompt import CorePromptCategory
from ava.repositories.core_prompt_assignment import CorePromptScopeType
from ava.repositories.project import ProjectRecord
from ava.services.attachment_store import InMemoryAttachmentRepository
from ava.services.conversation_folder_store import ConversationFolderStore
from ava.services.conversation_hard_delete_coordinator import InMemoryConversationHardDeleteCoordinator
from ava.services.conversation_store import ConversationStore
from ava.services.core_prompt_assignment_service import CorePromptAssignmentError, CorePromptAssignmentService
from ava.services.core_prompt_assignment_store import CorePromptAssignmentStore
from ava.services.core_prompt_service import CorePromptService
from ava.services.core_prompt_store import CorePromptStore
from ava.services.message_store import MessageStore
from ava.services.project_store import ProjectStore
from ava.services.run_event_store import RunEventStore
from ava.services.run_store import RunStore


@pytest.fixture(params=["memory", "sqlite"])
def domain(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "memory":
        assignments = CorePromptAssignmentStore()
        conversations = ConversationStore()
        prompts = CorePromptStore(assignments)
        projects = ProjectStore(conversations, assignments)
        folders = ConversationFolderStore(conversations, assignments)
        yield (
            CorePromptAssignmentService(
                assignments=assignments,
                prompts=prompts,
                projects=projects,
                folders=folders,
                conversations=conversations,
                runtime_ids=("native",),
            ),
            CorePromptService(core_prompt_repository=prompts),
            assignments,
            projects,
            folders,
            conversations,
            None,
        )
        return
    database = SqliteDatabase(str(tmp_path / "assignments.sqlite3"))
    assignments = RelationalCorePromptAssignmentRepository(database=database)
    prompts = RelationalCorePromptRepository(database=database)
    projects = RelationalProjectRepository(database=database)
    folders = RelationalConversationFolderRepository(database=database)
    conversations = RelationalConversationRepository(database=database)
    yield (
        CorePromptAssignmentService(
            assignments=assignments,
            prompts=prompts,
            projects=projects,
            folders=folders,
            conversations=conversations,
            runtime_ids=("native",),
        ),
        CorePromptService(core_prompt_repository=prompts),
        assignments,
        projects,
        folders,
        conversations,
        database,
    )
    database.dispose()


def _prompt(service: CorePromptService) -> str:
    return service.create_core_prompt(
        CreateCorePromptRequest(
            name="Rules",
            prompt_text="Keep it exact",
            category=CorePromptCategory.ENGINEERING,
        )
    ).id


def test_enable_disable_inherit_global_idempotency_and_restart_parity(domain) -> None:
    assignments, prompts = domain[:2]
    repo = domain[6]
    record = _prompt(prompts)
    enabled = assignments.set_assignment(record, CorePromptScopeType.GLOBAL, None, "enable")
    assert enabled and enabled.mode.value == "enable"
    assert UUID(enabled.id).version == 4
    assert assignments.get_assignment(record, CorePromptScopeType.GLOBAL, None) == enabled
    assert enabled.id == assignments.set_assignment(record, CorePromptScopeType.GLOBAL, None, "enable").id
    assert (
        enabled.updated_at == assignments.set_assignment(record, CorePromptScopeType.GLOBAL, None, "enable").updated_at
    )
    disabled = assignments.set_assignment(record, CorePromptScopeType.GLOBAL, None, "disable")
    assert disabled and disabled.mode.value == "disable" and disabled.id == enabled.id
    assert disabled.created_at == enabled.created_at and disabled.updated_at > enabled.updated_at
    enabled_again = assignments.set_assignment(record, CorePromptScopeType.GLOBAL, None, "enable")
    assert enabled_again and enabled_again.id == enabled.id and enabled_again.created_at == enabled.created_at
    assert enabled_again.updated_at > disabled.updated_at
    assert len(assignments.list_for_prompt(record)) == 1
    assert assignments.set_assignment(record, CorePromptScopeType.GLOBAL, None, "inherit") is None
    assert assignments.set_assignment(record, CorePromptScopeType.GLOBAL, None, "inherit") is None
    assert assignments.list_for_prompt(record) == []
    if repo is not None:
        with repo.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM core_prompt_assignments").fetchone()[0] == 0
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_target_validation_and_supported_scope_listing(domain) -> None:
    assignments, prompts, _, projects, folders, conversations, _ = domain
    prompt = _prompt(prompts)
    with pytest.raises(CorePromptAssignmentError) as missing_prompt:
        assignments.set_assignment("missing-prompt", CorePromptScopeType.GLOBAL, None, "enable")
    assert missing_prompt.value.error_code == "core_prompt_not_found"
    for scope in (CorePromptScopeType.PROJECT, CorePromptScopeType.FOLDER, CorePromptScopeType.CONVERSATION):
        with pytest.raises(CorePromptAssignmentError) as missing:
            assignments.set_assignment(prompt, scope, "missing", "enable")
        assert missing.value.error_code in {
            "project_not_found",
            "conversation_folder_not_found",
            "conversation_not_found",
        }
    project_id, folder_id = "prj-1", "fld-1"
    if domain[-1] is None:
        from datetime import UTC, datetime

        from ava.repositories.conversation_folder import ConversationFolderRecord
        from ava.repositories.project import ProjectRecord

        now = datetime.now(UTC)
        projects.create(ProjectRecord(project_id, "Project", now, now))
        folders.create(ConversationFolderRecord(folder_id, "Folder", now, now))
        conversations.create("cnv-1", title="Conversation")
    else:
        from datetime import UTC, datetime

        from ava.repositories.conversation_folder import ConversationFolderRecord
        from ava.repositories.project import ProjectRecord

        now = datetime.now(UTC)
        projects.create(ProjectRecord(project_id, "Project", now, now))
        folders.create(ConversationFolderRecord(folder_id, "Folder", now, now))
        conversations.create("cnv-1", title="Conversation")
    for scope, identity in (
        (CorePromptScopeType.PROJECT, project_id),
        (CorePromptScopeType.FOLDER, folder_id),
        (CorePromptScopeType.CONVERSATION, "cnv-1"),
    ):
        assignments.set_assignment(prompt, scope, identity, "enable")
        assert len(assignments.list_for_scope(scope, identity)) == 1
    assignments.set_assignment(prompt, CorePromptScopeType.RUNTIME, "native", "enable")
    assignments.set_assignment(prompt, CorePromptScopeType.CAPABILITY, "runs", "disable")
    for scope in (CorePromptScopeType.APPLICATION, CorePromptScopeType.MODEL_COMPATIBILITY):
        with pytest.raises(CorePromptAssignmentError) as unsupported:
            assignments.set_assignment(prompt, scope, "invented", "enable")
        assert unsupported.value.error_code == "core_prompt_scope_unsupported"
    with pytest.raises(CorePromptAssignmentError) as unknown_runtime:
        assignments.set_assignment(prompt, CorePromptScopeType.RUNTIME, "fake", "enable")
    assert unknown_runtime.value.error_code == "core_prompt_scope_target_not_found"
    with pytest.raises(CorePromptAssignmentError) as unknown_capability:
        assignments.set_assignment(prompt, CorePromptScopeType.CAPABILITY, "fake", "enable")
    assert unknown_capability.value.error_code == "core_prompt_scope_target_not_found"
    with pytest.raises(CorePromptAssignmentError):
        assignments.set_assignment(prompt, CorePromptScopeType.GLOBAL, "bad", "enable")
    with pytest.raises(CorePromptAssignmentError):
        assignments.set_assignment(prompt, CorePromptScopeType.PROJECT, " ", "enable")
    with pytest.raises(CorePromptAssignmentError):
        assignments.set_assignment(prompt, CorePromptScopeType.PROJECT, None, "enable")


def test_sqlite_project_delete_cleanup_and_rollback(domain) -> None:
    assignment_service, prompt_service, assignment_repo, projects, _, _, database = domain
    if database is None:
        pytest.skip("SQLite transactional rollback is covered by relational adapter only")
    prompt = _prompt(prompt_service)
    from datetime import UTC, datetime

    from ava.repositories.project import ProjectRecord

    now = datetime.now(UTC)
    projects.create(ProjectRecord("p", "Project", now, now))
    assignment_service.set_assignment(prompt, CorePromptScopeType.PROJECT, "p", "disable")
    with database.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER fail_project_delete BEFORE DELETE ON projects BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(ValueError):
        projects.delete("p")
    assert assignment_repo.list_for_scope(CorePromptScopeType.PROJECT, "p")
    assert projects.get("p") is not None
    with database.transaction() as connection:
        connection.execute("DROP TRIGGER fail_project_delete")
    assert projects.delete("p") is True
    assert assignment_repo.list_for_scope(CorePromptScopeType.PROJECT, "p") == []


def test_sqlite_prompt_delete_cascade_is_atomic(domain) -> None:
    assignment_service, prompt_service, assignment_repo, projects, _, _, database = domain
    if database is None:
        pytest.skip("SQLite foreign-key cascade is covered by relational adapter only")
    prompt = _prompt(prompt_service)
    from datetime import UTC, datetime

    from ava.repositories.project import ProjectRecord

    now = datetime.now(UTC)
    projects.create(ProjectRecord("p", "Project", now, now))
    assignment_service.set_assignment(prompt, CorePromptScopeType.PROJECT, "p", "enable")
    with database.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER fail_prompt_delete BEFORE DELETE ON core_prompts BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(ValueError):
        prompt_service.delete_core_prompt(prompt)
    assert assignment_repo.list_for_prompt(prompt)
    assert assignment_repo._database is database
    assert prompt_service.get_core_prompt(prompt).id == prompt


def test_sqlite_global_uniqueness_and_scope_cleanup(domain) -> None:
    assignment_service, prompt_service, assignment_repo, projects, folders, conversations, database = domain
    if database is None:
        pytest.skip("direct SQLite constraints and cleanup are relational only")
    prompt = _prompt(prompt_service)
    assignment_service.set_assignment(prompt, CorePromptScopeType.GLOBAL, None, "enable")
    with database.transaction() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO core_prompt_assignments "
            "(id, core_prompt_id, scope_type, scope_id, mode, created_at, updated_at) "
            "VALUES ('duplicate', ?, 'global', NULL, 'disable', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
            (prompt,),
        )
    from datetime import UTC, datetime

    from ava.repositories.conversation_folder import ConversationFolderRecord
    from ava.repositories.project import ProjectRecord

    now = datetime.now(UTC)
    projects.create(ProjectRecord("p", "P", now, now))
    folders.create(ConversationFolderRecord("f", "F", now, now))
    conversations.create("c", title="C")
    assignment_service.set_assignment(prompt, CorePromptScopeType.FOLDER, "f", "enable")
    assignment_service.set_assignment(prompt, CorePromptScopeType.CONVERSATION, "c", "disable")
    # Archive is reversible state and must leave the explicit override intact.
    conversations.set_archived("c", True)
    assert assignment_repo.list_for_scope(CorePromptScopeType.CONVERSATION, "c")
    assert folders.delete("f") is True
    assert assignment_repo.list_for_scope(CorePromptScopeType.FOLDER, "f") == []
    deleted = RelationalConversationHardDeleteCoordinator(database=database).delete("c")
    assert deleted is not None
    assert assignment_repo.list_for_scope(CorePromptScopeType.CONVERSATION, "c") == []


def test_assignment_state_survives_sqlite_reopen_and_inherit_is_absent(tmp_path: Path) -> None:
    path = str(tmp_path / "assignment-restart.sqlite3")
    database = SqliteDatabase(path)
    prompt_service = CorePromptService(core_prompt_repository=RelationalCorePromptRepository(database=database))
    prompt = _prompt(prompt_service)
    assignments = RelationalCorePromptAssignmentRepository(database=database)
    from datetime import UTC, datetime

    from ava.repositories.project import ProjectRecord

    now = datetime.now(UTC)
    project = RelationalProjectRepository(database=database)
    project.create(ProjectRecord("p", "P", now, now))
    service = CorePromptAssignmentService(
        assignments=assignments,
        prompts=RelationalCorePromptRepository(database=database),
        projects=project,
        folders=RelationalConversationFolderRepository(database=database),
        conversations=RelationalConversationRepository(database=database),
    )
    enabled = service.set_assignment(prompt, CorePromptScopeType.PROJECT, "p", "enable")
    database.dispose()

    reopened = SqliteDatabase(path)
    reopened_assignments = RelationalCorePromptAssignmentRepository(database=reopened)
    reopened_service = CorePromptAssignmentService(
        assignments=reopened_assignments,
        prompts=RelationalCorePromptRepository(database=reopened),
        projects=RelationalProjectRepository(database=reopened),
        folders=RelationalConversationFolderRepository(database=reopened),
        conversations=RelationalConversationRepository(database=reopened),
    )
    disabled = reopened_service.set_assignment(prompt, CorePromptScopeType.PROJECT, "p", "disable")
    assert enabled is not None and disabled is not None
    assert disabled.id == enabled.id and disabled.created_at == enabled.created_at
    reopened.dispose()

    final_db = SqliteDatabase(path)
    final_assignments = RelationalCorePromptAssignmentRepository(database=final_db)
    assert final_assignments.get_explicit(prompt, CorePromptScopeType.PROJECT, "p").mode.value == "disable"
    final_service = CorePromptAssignmentService(
        assignments=final_assignments,
        prompts=RelationalCorePromptRepository(database=final_db),
        projects=RelationalProjectRepository(database=final_db),
        folders=RelationalConversationFolderRepository(database=final_db),
        conversations=RelationalConversationRepository(database=final_db),
    )
    assert final_service.set_assignment(prompt, CorePromptScopeType.PROJECT, "p", "inherit") is None
    final_db.dispose()
    verified = SqliteDatabase(path)
    assert (
        RelationalCorePromptAssignmentRepository(database=verified).get_explicit(
            prompt, CorePromptScopeType.PROJECT, "p"
        )
        is None
    )
    verified.dispose()


def test_prompt_and_target_cleanup_parity(domain) -> None:
    assignment_service, prompt_service, assignment_repo, projects, folders, conversations, database = domain
    now = datetime.now(UTC)
    prompt = _prompt(prompt_service)
    projects.create(ProjectRecord("project", "P", now, now))
    folders.create(ConversationFolderRecord("folder", "F", now, now))
    conversations.create("conversation", title="C")
    assignment_service.set_assignment(prompt, CorePromptScopeType.PROJECT, "project", "enable")
    assignment_service.set_assignment(prompt, CorePromptScopeType.FOLDER, "folder", "disable")
    assignment_service.set_assignment(prompt, CorePromptScopeType.CONVERSATION, "conversation", "enable")
    archived_project = projects.update(replace(projects.get("project"), is_archived=True))
    assert archived_project is not None and archived_project.is_archived
    conversations.set_archived("conversation", True)
    prompt_service.set_enabled(prompt, False)
    assert assignment_repo.list_for_scope(CorePromptScopeType.PROJECT, "project")
    assert assignment_repo.list_for_scope(CorePromptScopeType.CONVERSATION, "conversation")

    assert projects.delete("project")
    assert folders.delete("folder")
    if database is None:
        coordinator = InMemoryConversationHardDeleteCoordinator(
            conversations=conversations,
            messages=MessageStore(),
            runs=RunStore(),
            run_events=RunEventStore(),
            attachments=InMemoryAttachmentRepository(),
            assignments=assignment_repo,
        )
    else:
        coordinator = RelationalConversationHardDeleteCoordinator(database=database)
    assert assignment_repo.list_for_scope(CorePromptScopeType.PROJECT, "project") == []
    assert assignment_repo.list_for_scope(CorePromptScopeType.FOLDER, "folder") == []
    assert coordinator.delete("conversation") is not None
    assert assignment_repo.list_for_scope(CorePromptScopeType.CONVERSATION, "conversation") == []

    projects.create(ProjectRecord("project-2", "P2", now, now))
    folders.create(ConversationFolderRecord("folder-2", "F2", now, now))
    conversations.create("conversation-2", title="C2")
    for scope, target in (
        (CorePromptScopeType.PROJECT, "project-2"),
        (CorePromptScopeType.FOLDER, "folder-2"),
        (CorePromptScopeType.CONVERSATION, "conversation-2"),
    ):
        assignment_service.set_assignment(prompt, scope, target, "enable")
    prompt_service.delete_core_prompt(prompt)
    assert assignment_repo.list_for_prompt(prompt) == []


def test_migration_0016_preserves_populated_schema_15_and_is_idempotent(tmp_path: Path) -> None:
    database = SqliteDatabase(str(tmp_path / "schema-15.sqlite3"), auto_migrate=False)
    through_15 = MigrationRegistry()
    for migration in default_registry():
        if migration.version <= 15:
            through_15.register(migration)
    assert MigrationRunner(database, through_15).migrate() == list(range(1, 16))
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO projects (id, name, is_archived, created_at, updated_at) "
            "VALUES ('p15', 'Existing project', 0, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO conversation_folders (id, name, created_at, updated_at) "
            "VALUES ('f15', 'Existing folder', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO conversations (conversation_id, title, created_at, updated_at, folder_id, project_id) "
            "VALUES ('c15', 'Existing conversation', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00', 'f15', 'p15')"
        )
        connection.execute(
            "INSERT INTO core_prompts (id, name, prompt_text, category, is_enabled, created_at, updated_at) "
            "VALUES ('cp15', 'Existing prompt', 'Exact', 'engineering', 1, "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    assert MigrationRunner(database, default_registry()).migrate() == [16, 17, 18, 19, 20, 21, 22, 23, 24, 25]
    assert MigrationRunner(database, default_registry()).migrate() == []
    assert MigrationRunner(database, default_registry()).current_version() == 25
    with database.connect() as connection:
        assert connection.execute("SELECT name FROM projects WHERE id='p15'").fetchone()[0] == "Existing project"
        assert (
            connection.execute("SELECT name FROM conversation_folders WHERE id='f15'").fetchone()[0]
            == "Existing folder"
        )
        assert (
            connection.execute("SELECT title FROM conversations WHERE conversation_id='c15'").fetchone()[0]
            == "Existing conversation"
        )
        assert connection.execute("SELECT prompt_text FROM core_prompts WHERE id='cp15'").fetchone()[0] == "Exact"
        assert connection.execute("SELECT COUNT(*) FROM core_prompt_assignments").fetchone()[0] == 0
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    database.dispose()
