"""Backward-compatibility certification against real SQLite migration prefixes.

These tests create historical databases with the production migration registry,
seed rows in the historical schema, and then reopen them through the production
current-schema bootstrap. No schema is recreated or mocked in the tests.
"""

import sqlite3
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest

from ava.configuration.settings import Settings
from ava.infrastructure.composition import create_application_persistence, create_conversation_hard_delete_coordinator
from ava.infrastructure.persistence import (
    MigrationRegistry,
    MigrationRunner,
    SqliteDatabase,
    create_relational_repositories,
    default_registry,
)
from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.repositories.core_prompt import CorePromptCategory, CorePromptRecord
from ava.repositories.core_prompt_assignment import (
    CorePromptAssignmentMode,
    CorePromptAssignmentRecord,
    CorePromptScopeType,
)
from ava.repositories.project import ProjectExecutionDefaults
from ava.services.attachment_content_store import InMemoryAttachmentContentStore
from ava.services.conversation_service import ConversationService
from ava.services.project_file_content_store import InMemoryProjectFileContentStore
from ava.services.project_file_service import ProjectFileService
from ava.services.project_service import ProjectService

EXPECTED_MIGRATIONS = [
    "initial application persistence schema",
    "document revision history",
    "attachment metadata",
    "provider connections",
    "model configurations",
    "runtime configurations",
    "application execution defaults",
    "durable conversation run relationships",
    "durable run cancellation request",
    "conversation organization metadata",
    "conversation folders",
    "projects",
    "conversation Project relationship",
    "conversation Project lookup index",
    "CORE prompt definitions",
    "Scoped CORE prompt assignments",
    "Project execution defaults",
    "Project files",
    "Conversation title ownership",
    "Run inspection snapshots",
    "Configured model context windows",
    "Conversation context summaries",
    "Project file name uniqueness",
    "tool feature configuration",
    "workspace access configuration",
    "durable tool approvals",
    "run execution mode",
]


def _registry_through(version: int) -> MigrationRegistry:
    registry = MigrationRegistry()
    for migration in default_registry():
        if migration.version > version:
            break
        registry.register(migration)
    return registry


def _new_db() -> tuple[SqliteDatabase, Path]:
    path = Path(tempfile.mktemp(suffix=".sqlite3"))
    return SqliteDatabase(str(path), auto_migrate=False), path


def _run_through(database: SqliteDatabase, version: int) -> None:
    assert MigrationRunner(database, _registry_through(version)).migrate() == list(range(1, version + 1))


def test_migration_registry_is_a_contiguous_documented_history_through_27() -> None:
    migrations = list(default_registry())
    assert [migration.version for migration in migrations] == list(range(1, 28))
    assert [migration.name for migration in migrations] == EXPECTED_MIGRATIONS


def test_fresh_install_and_current_phase_five_constraints_are_valid() -> None:
    database, path = _new_db()
    try:
        runner = MigrationRunner(database, default_registry())
        assert runner.migrate() == list(range(1, 28))
        assert runner.current_version() == 27
        with database.connect() as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {
                "conversation_folders",
                "projects",
                "core_prompts",
                "core_prompt_assignments",
                "project_files",
            } <= table_names
            assert not any("knowledge" in table.lower() or "embedding" in table.lower() for table in table_names)

            project_model_fk = connection.execute("PRAGMA foreign_key_list(projects)").fetchall()
            assert any(
                row["from"] == "default_model_id"
                and row["table"] == "model_configurations"
                and row["on_delete"] == "SET NULL"
                for row in project_model_fk
            )
            project_file_fk = connection.execute("PRAGMA foreign_key_list(project_files)").fetchall()
            assert any(
                row["from"] == "project_id" and row["table"] == "projects" and row["on_delete"] == "CASCADE"
                for row in project_file_fk
            )
            assignment_fk = connection.execute("PRAGMA foreign_key_list(core_prompt_assignments)").fetchall()
            assert any(
                row["from"] == "core_prompt_id" and row["table"] == "core_prompts" and row["on_delete"] == "CASCADE"
                for row in assignment_fk
            )

            project_model_id = connection.execute("PRAGMA table_info(projects)").fetchall()
            defaults = {row["name"]: row["dflt_value"] for row in project_model_id}
            assert defaults["default_runtime_key"] is None and defaults["default_model_id"] is None
            conversation_columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(conversations)")}
            assert conversation_columns["is_pinned"]["notnull"] == 1
            assert conversation_columns["is_pinned"]["dflt_value"] == "0"
            assert conversation_columns["is_archived"]["notnull"] == 1
            assert conversation_columns["is_archived"]["dflt_value"] == "0"
            assert conversation_columns["folder_id"]["notnull"] == 0
            assert conversation_columns["folder_id"]["dflt_value"] is None
            assert conversation_columns["project_id"]["notnull"] == 0
            assert conversation_columns["project_id"]["dflt_value"] is None

            connection.execute(
                "INSERT INTO core_prompts(id,name,prompt_text,category,created_at,updated_at) "
                "VALUES ('p1','prompt','text','raw-category','created','updated')"
            )
            connection.execute(
                "INSERT INTO core_prompt_assignments(id,core_prompt_id,scope_type,scope_id,mode,created_at,updated_at) "
                "VALUES ('global-1','p1','global',NULL,'enable','created','updated')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO core_prompt_assignments("
                    "id,core_prompt_id,scope_type,scope_id,mode,created_at,updated_at) "
                    "VALUES ('global-2','p1','global',NULL,'disable','created','updated')"
                )
            connection.execute(
                "INSERT INTO core_prompt_assignments("
                "id,core_prompt_id,scope_type,scope_id,mode,created_at,updated_at) "
                "VALUES ('project-1','p1','project','project-1','enable','created','updated')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO core_prompt_assignments("
                    "id,core_prompt_id,scope_type,scope_id,mode,created_at,updated_at) "
                    "VALUES ('project-2','p1','project','project-1','disable','created','updated')"
                )
            connection.execute(
                "INSERT INTO projects(id,name,is_archived,created_at,updated_at) "
                "VALUES ('p','Project',0,'created','updated')"
            )
            connection.execute(
                "INSERT INTO model_configurations("
                "model_id,provider_connection_id,provider_model_name,display_name,hosting_mode,capabilities,enabled) "
                "VALUES ('model-fk','provider-ref','native-model','Model','local','[]',1)"
            )
            connection.execute("UPDATE projects SET default_model_id='model-fk' WHERE id='p'")
            connection.execute("DELETE FROM model_configurations WHERE model_id='model-fk'")
            assert connection.execute("SELECT default_model_id FROM projects WHERE id='p'").fetchone()[0] is None
            connection.execute(
                "INSERT INTO project_files("
                "id,project_id,file_name,size_bytes,content_ref,created_at,updated_at,normalized_file_name) "
                "VALUES ('file-1','p','same.txt',0,'opaque-ref','created','updated','same.txt')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO project_files("
                    "id,project_id,file_name,size_bytes,content_ref,created_at,updated_at,normalized_file_name) "
                    "VALUES ('file-2','p','SAME.txt',0,'other-ref','created','updated','same.txt')"
                )
            connection.execute("DELETE FROM projects WHERE id='p'")
            assert connection.execute("SELECT COUNT(*) FROM project_files WHERE id='file-1'").fetchone()[0] == 0
            connection.execute("DELETE FROM core_prompts WHERE id='p1'")
            assert (
                connection.execute("SELECT COUNT(*) FROM core_prompt_assignments WHERE core_prompt_id='p1'").fetchone()[
                    0
                ]
                == 0
            )
    finally:
        database.dispose()
        path.unlink(missing_ok=True)


def test_pre_project_file_database_upgrade_preserves_existing_project() -> None:
    # A separately-created v17 database is the direct pre-Project-File
    # baseline. The already-existing Project upgrades without recreation.
    database, path = _new_db()
    try:
        _run_through(database, 17)
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO projects("
                "id,name,description,instructions,is_archived,created_at,updated_at,"
                "default_runtime_key,default_model_id) "
                "VALUES ('pre-files-project','Existing Project',NULL,NULL,0,"
                "'2024-01-01T00:00:00Z','2024-01-02T00:00:00Z',NULL,NULL)"
            )
        database.dispose()
        current = SqliteDatabase(str(path), auto_migrate=False)
        try:
            assert MigrationRunner(current, default_registry()).migrate() == [18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
            with current.connect() as connection:
                row = connection.execute(
                    "SELECT id,name,created_at,updated_at,default_runtime_key,default_model_id FROM projects"
                ).fetchone()
                assert tuple(row) == (
                    "pre-files-project",
                    "Existing Project",
                    "2024-01-01T00:00:00Z",
                    "2024-01-02T00:00:00Z",
                    None,
                    None,
                )
                assert connection.execute("SELECT COUNT(*) FROM project_files").fetchone()[0] == 0
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            current.dispose()
    finally:
        database.dispose()
        path.unlink(missing_ok=True)


def test_pre_folder_project_database_upgrade_preserves_legacy_conversation_graph() -> None:
    database, path = _new_db()
    try:
        _run_through(database, 9)
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO conversations(conversation_id,title,created_at,updated_at) "
                "VALUES ('legacy-c','Legacy · 測試','2024-01-02T03:04:05Z','2024-01-03T03:04:05Z')"
            )
            connection.execute(
                "INSERT INTO messages("
                "message_id,conversation_id,role,status,content,source_run_id,created_at,updated_at) "
                "VALUES ('legacy-m','legacy-c','user','completed','keep this transcript',NULL,"
                "'2024-01-02T03:05:00Z','2024-01-02T03:05:00Z')"
            )
            connection.execute(
                "INSERT INTO runs(run_id,status,created_at,updated_at,conversation_id,source_user_message_id) "
                "VALUES ('legacy-r','completed','2024-01-02T03:05:01Z','2024-01-02T03:05:02Z','legacy-c','legacy-m')"
            )
            connection.execute(
                'INSERT INTO run_events(event_id,run_id,event_type,seq,"timestamp",payload,contract_version) '
                "VALUES ('legacy-e','legacy-r','run_started',1,'2024-01-02T03:05:01Z','{}','1')"
            )
            connection.execute(
                "INSERT INTO attachments("
                "attachment_id,file_name,media_type,size_bytes,storage_key,owner_type,owner_id,status,created_at) "
                "VALUES ('legacy-a','photo.png','image/png',0,'opaque:legacy','conversation','legacy-c',"
                "'available','2024-01-02T03:04:00Z')"
            )
            connection.execute(
                "INSERT INTO provider_connections("
                "provider_connection_id,provider_id,display_name,endpoint,enabled,credential_reference) "
                "VALUES ('provider-stable','openai-compatible','Provider 名',NULL,1,'credential-ref')"
            )
            connection.execute(
                "INSERT INTO model_configurations("
                "model_id,provider_connection_id,provider_model_name,display_name,hosting_mode,capabilities,enabled) "
                "VALUES ('model-stable','provider-stable','model-native','Model 名','external','[]',1)"
            )
            connection.execute(
                "INSERT INTO runtime_configurations(runtime_configuration_id,runtime_type,display_name,enabled) "
                "VALUES ('runtime-stable','native','Runtime 名',1)"
            )
            connection.execute(
                "INSERT INTO application_execution_defaults("
                "id,default_provider_connection_id,default_model_id,default_runtime_configuration_id) "
                "VALUES (1,'provider-stable','model-stable','runtime-stable')"
            )
        database.dispose()

        upgraded = SqliteDatabase(str(path), auto_migrate=False)
        try:
            assert MigrationRunner(upgraded, default_registry()).migrate() == list(range(10, 28))
            with upgraded.connect() as connection:
                conversation = connection.execute(
                    "SELECT conversation_id,title,created_at,updated_at,is_pinned,is_archived,folder_id,project_id "
                    "FROM conversations WHERE conversation_id='legacy-c'"
                ).fetchone()
                assert tuple(conversation) == (
                    "legacy-c",
                    "Legacy · 測試",
                    "2024-01-02T03:04:05Z",
                    "2024-01-03T03:04:05Z",
                    0,
                    0,
                    None,
                    None,
                )
                assert tuple(connection.execute("SELECT message_id,content FROM messages").fetchone()) == (
                    "legacy-m",
                    "keep this transcript",
                )
                assert tuple(connection.execute("SELECT run_id,status,conversation_id FROM runs").fetchone()) == (
                    "legacy-r",
                    "completed",
                    "legacy-c",
                )
                assert tuple(connection.execute("SELECT event_id,run_id,payload FROM run_events").fetchone()) == (
                    "legacy-e",
                    "legacy-r",
                    "{}",
                )
                assert tuple(
                    connection.execute("SELECT attachment_id,storage_key,owner_id FROM attachments").fetchone()
                ) == ("legacy-a", "opaque:legacy", "legacy-c")
                assert tuple(
                    connection.execute(
                        "SELECT provider_connection_id,display_name,credential_reference FROM provider_connections"
                    ).fetchone()
                ) == ("provider-stable", "Provider 名", "credential-ref")
                assert tuple(
                    connection.execute(
                        "SELECT model_id,provider_connection_id,provider_model_name FROM model_configurations"
                    ).fetchone()
                ) == ("model-stable", "provider-stable", "model-native")
                assert tuple(
                    connection.execute(
                        "SELECT runtime_configuration_id,runtime_type FROM runtime_configurations"
                    ).fetchone()
                ) == ("runtime-stable", "native")
                assert tuple(
                    connection.execute(
                        "SELECT default_provider_connection_id,default_model_id,default_runtime_configuration_id "
                        "FROM application_execution_defaults WHERE id=1"
                    ).fetchone()
                ) == ("provider-stable", "model-stable", "runtime-stable")
                assert connection.execute("SELECT COUNT(*) FROM core_prompt_assignments").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM core_prompts").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM conversation_folders").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM project_files").fetchone()[0] == 0
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            upgraded.dispose()
    finally:
        database.dispose()
        path.unlink(missing_ok=True)


def test_pre_core_assignment_and_project_file_boundaries_upgrade_without_fabrication() -> None:
    # v15 has prompt definitions but no assignment table. Existing definitions
    # must survive and the new assignment table must represent INHERIT as empty.
    database, path = _new_db()
    try:
        _run_through(database, 15)
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO core_prompts(id,name,description,prompt_text,category,is_enabled,created_at,updated_at) "
                "VALUES ('prompt-old','提示 Legacy',NULL,'exact prompt text — Ω','general',0,"
                "'2024-01-01T00:00:00Z','2024-01-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO core_prompts(id,name,prompt_text,category,is_enabled,created_at,updated_at) "
                "VALUES ('prompt-inherit','Inherited prompt','inherited global baseline','general',1,"
                "'2024-01-03T00:00:00Z','2024-01-04T00:00:00Z')"
            )
        database.dispose()
        current = SqliteDatabase(str(path), auto_migrate=False)
        try:
            assert MigrationRunner(current, default_registry()).migrate() == list(range(16, 28))
            with current.connect() as connection:
                row = connection.execute("SELECT * FROM core_prompts WHERE id='prompt-old'").fetchone()
                assert (
                    row["name"],
                    row["description"],
                    row["prompt_text"],
                    row["category"],
                    row["is_enabled"],
                    row["created_at"],
                    row["updated_at"],
                ) == (
                    "提示 Legacy",
                    None,
                    "exact prompt text — Ω",
                    "general",
                    0,
                    "2024-01-01T00:00:00Z",
                    "2024-01-02T00:00:00Z",
                )
                assert connection.execute("SELECT COUNT(*) FROM core_prompt_assignments").fetchone()[0] == 0
            current.dispose()
            repos = create_relational_repositories(str(path))
            try:
                from ava.services.effective_prompt_resolver import (
                    EffectivePromptResolver,
                    PromptResolutionContext,
                )

                resolved = EffectivePromptResolver(
                    prompts=repos.core_prompt_repository,
                    assignments=repos.core_prompt_assignment_repository,
                    conversations=repos.conversation_repository,
                    runtime_ids=("native",),
                ).resolve(PromptResolutionContext())
                assert [item.core_prompt_id for item in resolved.enabled_prompts] == ["prompt-inherit"]
                assert resolved.enabled_prompts[0].reason == "inherited_global"
                assert resolved.enabled_prompts[0].winning_assignment_id is None
            finally:
                repos.dispose()
        finally:
            current.dispose()
    finally:
        database.dispose()
        path.unlink(missing_ok=True)

    # v16 contains Projects before execution defaults are added. Existing rows
    # must receive NULL at v17, then remain metadata-only at v18.
    database, path = _new_db()
    try:
        _run_through(database, 16)
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO projects(id,name,description,instructions,is_archived,created_at,updated_at) "
                "VALUES ('legacy-p','Old Project','',NULL,0,'project-created','project-updated')"
            )
        database.dispose()
        current = SqliteDatabase(str(path), auto_migrate=False)
        try:
            assert MigrationRunner(current, default_registry()).migrate() == [
                17,
                18,
                19,
                20,
                21,
                22,
                23,
                24,
                25,
                26,
                27,
            ]
            with current.connect() as connection:
                project = connection.execute("SELECT * FROM projects WHERE id='legacy-p'").fetchone()
                assert (
                    project["description"],
                    project["instructions"],
                    project["default_runtime_key"],
                    project["default_model_id"],
                ) == ("", None, None, None)
                assert connection.execute("SELECT COUNT(*) FROM project_files").fetchone()[0] == 0
                project_file_ddl = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='project_files'"
                ).fetchone()[0]
                assert "content_ref" in project_file_ddl and "BLOB" not in project_file_ddl.upper()
                assert "ON DELETE CASCADE" in project_file_ddl.upper()
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            current.dispose()
    finally:
        database.dispose()
        path.unlink(missing_ok=True)


def test_real_app_persistence_composition_reads_upgraded_database_and_is_idempotent() -> None:
    database, path = _new_db()
    try:
        _run_through(database, 14)
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO conversation_folders(id,name,created_at,updated_at) VALUES "
                "('folder-old','Old Folder','2024-01-01T00:00:00Z','2024-01-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO projects(id,name,description,instructions,is_archived,created_at,updated_at) VALUES "
                "('project-old','Old Project',NULL,'  ',0,'2024-01-01T00:00:00Z','2024-01-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO conversations("
                "conversation_id,title,created_at,updated_at,is_pinned,is_archived,folder_id,project_id) "
                "VALUES ('conversation-old','Old Conversation','2024-01-01T00:00:00Z',"
                "'2024-01-02T00:00:00Z',1,1,'folder-old','project-old')"
            )
        database.dispose()

        repos = create_relational_repositories(str(path))
        try:
            conversation = repos.conversation_repository.get("conversation-old")
            assert conversation is not None
            assert conversation.title == "Old Conversation"
            assert conversation.is_pinned is True and conversation.is_archived is True
            assert conversation.folder_id == "folder-old" and conversation.project_id == "project-old"
            project = repos.project_repository.get("project-old")
            assert project is not None and project.instructions == "  "
            now = datetime.now(UTC)
            repos.conversation_folder_repository.create(
                ConversationFolderRecord("folder-new", "Folder after upgrade", now, now)
            )
            moved = repos.conversation_repository.set_folder("conversation-old", "folder-new")
            assert moved is not None and moved.folder_id == "folder-new" and moved.project_id == "project-old"
            assert repos.conversation_repository.set_pinned("conversation-old", False) is not None
            assert repos.conversation_repository.set_archived("conversation-old", False) is not None
            assert repos.conversation_repository.set_archived("conversation-old", True) is not None
            repos.project_repository.update(
                replace(
                    project,
                    instructions="Edited after upgrade",
                    execution_defaults=ProjectExecutionDefaults("native", None),
                )
            )
            updated_project = repos.project_repository.get("project-old")
            assert updated_project is not None
            assert updated_project.instructions == "Edited after upgrade"
            assert updated_project.execution_defaults.runtime_key == "native"
            repos.conversation_repository.create(
                "conversation-created-after-upgrade",
                title="New conversation",
                folder_id="folder-new",
                project_id="project-old",
            )
            with repos.database.connect() as connection:
                metadata_before = [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT version,name,applied_at FROM ava_schema_migrations ORDER BY version"
                    )
                ]
                snapshot_before = tuple(
                    connection.execute(
                        "SELECT conversation_id,title,updated_at,is_pinned,is_archived,folder_id,project_id "
                        "FROM conversations WHERE conversation_id='conversation-old'"
                    ).fetchone()
                )
            assert MigrationRunner(repos.database, default_registry()).migrate() == []
            with repos.database.connect() as connection:
                assert metadata_before == [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT version,name,applied_at FROM ava_schema_migrations ORDER BY version"
                    )
                ]
                assert snapshot_before == tuple(
                    connection.execute(
                        "SELECT conversation_id,title,updated_at,is_pinned,is_archived,folder_id,project_id "
                        "FROM conversations WHERE conversation_id='conversation-old'"
                    ).fetchone()
                )
                assert connection.execute("SELECT COUNT(*) FROM core_prompts").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM core_prompt_assignments").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM project_files").fetchone()[0] == 0
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            repos.dispose()
        second_startup = create_relational_repositories(str(path))
        try:
            second_runner = MigrationRunner(second_startup.database, default_registry())
            assert second_runner.current_version() == 27
            assert second_runner.migrate() == []
            with second_startup.database.connect() as connection:
                assert metadata_before == [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT version,name,applied_at FROM ava_schema_migrations ORDER BY version"
                    )
                ]
                assert snapshot_before == tuple(
                    connection.execute(
                        "SELECT conversation_id,title,updated_at,is_pinned,is_archived,folder_id,project_id "
                        "FROM conversations WHERE conversation_id='conversation-old'"
                    ).fetchone()
                )
        finally:
            second_startup.dispose()
    finally:
        database.dispose()
        path.unlink(missing_ok=True)


def test_largeish_unicode_duplicate_name_graph_keeps_ids_and_ordering_fields() -> None:
    database, path = _new_db()
    try:
        _run_through(database, 14)
        with database.connect() as connection:
            connection.executemany(
                "INSERT INTO conversation_folders(id,name,created_at,updated_at) "
                "VALUES (?,?,'2024-01-01T00:00:00Z','2024-01-02T00:00:00Z')",
                [(f"folder-{i}", "同じ名前" if i < 2 else f"Folder {i}") for i in range(10)],
            )
            connection.executemany(
                "INSERT INTO projects(id,name,description,instructions,is_archived,created_at,updated_at) "
                "VALUES (?,?,'',?,0,'2024-01-01T00:00:00Z','2024-01-02T00:00:00Z')",
                [
                    (f"project-{i}", "同じ Project" if i < 2 else f"Project {i}", "説明 🌱" if i == 0 else None)
                    for i in range(10)
                ],
            )
            conversation_rows = [
                (
                    f"conversation-{i:03d}",
                    "重複 title" if i < 3 else f"Conversation {i}",
                    "2024-01-01T00:00:00Z",
                    f"2024-01-{(i % 28) + 1:02d}T00:00:00Z",
                    int(i % 2 == 0),
                    int(i % 7 == 0),
                    None if i % 10 == 0 else f"folder-{i % 10}",
                    None if i % 10 == 0 else f"project-{i % 10}",
                )
                for i in range(100)
            ]
            connection.executemany(
                "INSERT INTO conversations("
                "conversation_id,title,created_at,updated_at,is_pinned,is_archived,folder_id,project_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                conversation_rows,
            )
            message_rows = [
                (
                    f"message-{i}-{j}",
                    f"conversation-{i:03d}",
                    "user",
                    "completed",
                    f"body {i} {j} — Ω",
                    None,
                    "2024-01-01T00:00:00Z",
                    "2024-01-01T00:00:00Z",
                )
                for i in range(100)
                for j in range(3)
            ]
            connection.executemany(
                "INSERT INTO messages("
                "message_id,conversation_id,role,status,content,source_run_id,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                message_rows,
            )
            before_ids = [
                row[0]
                for row in connection.execute("SELECT conversation_id FROM conversations ORDER BY conversation_id")
            ]
            before_counts = (
                connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM conversation_folders").fetchone()[0],
            )
        database.dispose()
        upgraded = SqliteDatabase(str(path), auto_migrate=False)
        try:
            assert MigrationRunner(upgraded, default_registry()).migrate() == list(range(15, 28))
            with upgraded.connect() as connection:
                assert before_ids == [
                    row[0]
                    for row in connection.execute("SELECT conversation_id FROM conversations ORDER BY conversation_id")
                ]
                assert before_counts == (
                    connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                    connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                    connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                    connection.execute("SELECT COUNT(*) FROM conversation_folders").fetchone()[0],
                )
                assert (
                    connection.execute("SELECT instructions FROM projects WHERE id='project-0'").fetchone()[0]
                    == "説明 🌱"
                )
                assert (
                    connection.execute(
                        "SELECT title FROM conversations WHERE conversation_id='conversation-000'"
                    ).fetchone()[0]
                    == "重複 title"
                )
                assert connection.execute("SELECT COUNT(*) FROM project_files").fetchone()[0] == 0
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            upgraded.dispose()
    finally:
        database.dispose()
        path.unlink(missing_ok=True)


def test_delete_cleanup_services_operate_on_an_upgraded_historical_database() -> None:
    database, path = _new_db()
    persistence = None
    try:
        _run_through(database, 14)
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO conversation_folders(id,name,created_at,updated_at) VALUES "
                "('folder-old','Old Folder','2024-01-01T00:00:00Z','2024-01-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO projects(id,name,is_archived,created_at,updated_at) "
                "VALUES ('project-old','Old Project',0,'2024-01-01T00:00:00Z','2024-01-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO conversations(conversation_id,title,created_at,updated_at,folder_id,project_id) "
                "VALUES ('conversation-old','Old Conversation','2024-01-01T00:00:00Z',"
                "'2024-01-02T00:00:00Z','folder-old','project-old')"
            )
        database.dispose()

        # This is the normal application persistence bootstrap: it advances the
        # old database before handing any repositories to current services.
        persistence = create_application_persistence(
            Settings(persistence_provider="relational", persistence_database_url=str(path))
        )
        now = datetime.now(UTC)
        persistence.core_prompt_repository.create(
            CorePromptRecord(
                "prompt-after-upgrade", "Prompt", None, "Prompt body", CorePromptCategory.GENERAL, True, now, now
            )
        )
        persistence.core_prompt_assignment_repository.upsert_explicit(
            CorePromptAssignmentRecord(
                "assignment-after-upgrade",
                "prompt-after-upgrade",
                CorePromptScopeType.CONVERSATION,
                "conversation-old",
                CorePromptAssignmentMode.ENABLE,
                now,
                now,
            )
        )
        content = InMemoryProjectFileContentStore()
        file_service = ProjectFileService(
            projects=persistence.project_repository,
            files=persistence.project_file_repository,
            content=content,
        )
        file_record = file_service.create(
            "project-old", file_name="same.txt", content_type="text/plain", source=BytesIO(b"after upgrade")
        )
        assert content.exists(file_record.content_ref)

        conversation_service = ConversationService(
            conversation_repository=persistence.conversation_repository,
            message_repository=persistence.message_repository,
            run_repository=persistence.run_repository,
            run_event_repository=persistence.run_event_repository,
            hard_delete_coordinator=create_conversation_hard_delete_coordinator(persistence),
            attachment_content_store=InMemoryAttachmentContentStore(),
            project_repository=persistence.project_repository,
            folder_repository=persistence.conversation_folder_repository,
        )
        assert conversation_service.delete_conversation("conversation-old") is True
        assert persistence.conversation_repository.get("conversation-old") is None
        assert (
            persistence.core_prompt_assignment_repository.list_for_scope(
                CorePromptScopeType.CONVERSATION, "conversation-old"
            )
            == []
        )
        file_service.delete("project-old", file_record.id)
        assert persistence.project_file_repository.get(file_record.id) is None
        assert not content.exists(file_record.content_ref)
        assert persistence.core_prompt_repository.delete("prompt-after-upgrade") is True
        assert persistence.core_prompt_assignment_repository.list_for_prompt("prompt-after-upgrade") == []
        assert persistence.conversation_folder_repository.delete("folder-old") is True
        assert (
            ProjectService(
                project_repository=persistence.project_repository,
                project_file_service=file_service,
            ).delete_project("project-old")
            is None
        )
        assert persistence.project_repository.get("project-old") is None
        with persistence.database.connect() as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert connection.execute("SELECT COUNT(*) FROM project_files").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM core_prompt_assignments").fetchone()[0] == 0
    finally:
        if persistence is not None:
            persistence.dispose()
        database.dispose()
        path.unlink(missing_ok=True)
