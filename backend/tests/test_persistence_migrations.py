"""Tests for the Step 4.7 version-controlled schema migration system.

Covers: fresh-database bootstrap, idempotence on already-current databases,
validation-plus-stamping adoption of Step 4.6 legacy databases (data
preserved), fail-closed rejection of unknown/incompatible schemas, transactional
rollback of failed migrations, deterministic version ordering, duplicate
version rejection, database-newer-than-code rejection, metadata tampering, and
durability across reopen.

All test-only migration registries are applied with ``auto_migrate=False``
databases so the runner-under-test, not the default bootstrap, is what changes
the schema.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from ava.infrastructure.persistence import (
    Migration,
    MigrationError,
    MigrationRegistry,
    MigrationRunner,
    SchemaValidationError,
    SqliteDatabase,
    UnsupportedSchemaVersionError,
    create_relational_repositories,
    default_registry,
)
from ava.infrastructure.persistence.migrations.versions.v0001_initial_schema import migrate_up


def _file_database() -> tuple[SqliteDatabase, Path]:
    path = Path(tempfile.mktemp(suffix=".sqlite3"))
    return SqliteDatabase(str(path), auto_migrate=False), path


def _make_legacy_schema(path: Path) -> None:
    """Recreate the Step 4.6 schema exactly: five tables, no migration metadata."""
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_up(connection)
    connection.commit()
    connection.close()


def _tables(database: SqliteDatabase) -> set[str]:
    with database.connect() as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _metadata_versions(database: SqliteDatabase) -> list[int]:
    with database.connect() as connection:
        rows = connection.execute("SELECT version FROM ava_schema_migrations ORDER BY version").fetchall()
    return [row[0] for row in rows]


# ============================================================
# Fresh databases
# ============================================================


def test_migrate_bootstraps_a_fresh_database_with_the_default_migrations() -> None:
    database, path = _file_database()
    try:
        runner = MigrationRunner(database, default_registry())
        assert runner.current_version() == 0
        assert [m.version for m in runner.pending_migrations()] == list(range(1, 29))
        assert runner.migrate() == list(range(1, 29))
        assert runner.current_version() == 28
        assert list(runner.pending_migrations()) == []
        tables = _tables(database)
        assert {
            "runs",
            "run_events",
            "conversations",
            "messages",
            "documents",
            "document_revisions",
            "attachments",
            "provider_connections",
            "model_configurations",
            "runtime_configurations",
            "application_execution_defaults",
        } <= tables
        assert "projects" in tables
        assert "core_prompts" in tables
        assert "ava_schema_migrations" in tables
        applied = runner.applied_migrations()
        assert [(m.version, m.name) for m in applied] == [
            (1, "initial application persistence schema"),
            (2, "document revision history"),
            (3, "attachment metadata"),
            (4, "provider connections"),
            (5, "model configurations"),
            (6, "runtime configurations"),
            (7, "application execution defaults"),
            (8, "durable conversation run relationships"),
            (9, "durable run cancellation request"),
            (10, "conversation organization metadata"),
            (11, "conversation folders"),
            (12, "projects"),
            (13, "conversation Project relationship"),
            (14, "conversation Project lookup index"),
            (15, "CORE prompt definitions"),
            (16, "Scoped CORE prompt assignments"),
            (17, "Project execution defaults"),
            (18, "Project files"),
            (19, "Conversation title ownership"),
            (20, "Run inspection snapshots"),
            (21, "Configured model context windows"),
            (22, "Conversation context summaries"),
            (23, "Project file name uniqueness"),
            (24, "tool feature configuration"),
            (25, "workspace access configuration"),
            (26, "durable tool approvals"),
            (27, "run execution mode"),
            (28, "durable tool invocation reservations"),
        ]
        assert applied[0].applied_at
    finally:
        database.dispose()
        path.unlink()


def test_migrate_is_idempotent_for_an_already_current_database() -> None:
    database, path = _file_database()
    try:
        runner = MigrationRunner(database, default_registry())
        runner.migrate()
        tables_before = _tables(database)
        assert runner.migrate() == []
        assert runner.current_version() == 28
        assert _tables(database) == tables_before
        assert _metadata_versions(database) == list(range(1, 29))
    finally:
        database.dispose()
        path.unlink()


def test_project_file_name_migration_reports_existing_duplicates_without_cleanup() -> None:
    from ava.infrastructure.persistence.migrations.versions.v0023_project_file_name_uniqueness import migrate_up

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE project_files (id TEXT, project_id TEXT, file_name TEXT, content_type TEXT, "
        "size_bytes INTEGER, content_ref TEXT, created_at TEXT, updated_at TEXT)"
    )
    connection.executemany(
        "INSERT INTO project_files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("file-1", "project-a", "SKILL.md", "text/markdown", 1, "blob-1", "now", "now"),
            ("file-2", "project-a", "skill.md ", "text/markdown", 2, "blob-2", "now", "now"),
            ("file-3", "project-b", "SKILL.md", "text/markdown", 3, "blob-3", "now", "now"),
        ],
    )

    with pytest.raises(MigrationError, match="No files or records were changed") as error:
        migrate_up(connection)

    assert "project-a" in str(error.value)
    assert "file-1" in str(error.value) and "file-2" in str(error.value)
    assert connection.execute("SELECT COUNT(*) FROM project_files").fetchone()[0] == 3
    assert "normalized_file_name" not in {row[1] for row in connection.execute("PRAGMA table_info(project_files)")}
    connection.close()


def test_project_file_name_migration_preserves_existing_unique_metadata() -> None:
    database, path = _file_database()
    try:
        through_22 = MigrationRegistry()
        for migration in default_registry():
            if migration.version <= 22:
                through_22.register(migration)
        assert MigrationRunner(database, through_22).migrate() == list(range(1, 23))
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO projects(id,name,created_at,updated_at) VALUES ('project-a','A','now','now')"
            )
            connection.execute(
                "INSERT INTO project_files("
                "id,project_id,file_name,content_type,size_bytes,content_ref,created_at,updated_at) "
                "VALUES ('file-a','project-a','SKILL.md','text/markdown',12,'blob-a','created','updated')"
            )

        assert MigrationRunner(database, default_registry()).migrate() == [23, 24, 25, 26, 27, 28]
        with database.connect() as connection:
            row = connection.execute(
                "SELECT id,project_id,file_name,content_type,size_bytes,content_ref,created_at,updated_at,"
                "normalized_file_name FROM project_files WHERE id='file-a'"
            ).fetchone()
        assert tuple(row) == (
            "file-a",
            "project-a",
            "SKILL.md",
            "text/markdown",
            12,
            "blob-a",
            "created",
            "updated",
            "skill.md",
        )
    finally:
        database.dispose()
        path.unlink()


def test_migration_0019_marks_previously_renamed_conversations() -> None:
    database, path = _file_database()
    try:
        through_18 = MigrationRegistry()
        for migration in default_registry():
            if migration.version <= 18:
                through_18.register(migration)
        assert MigrationRunner(database, through_18).migrate() == list(range(1, 19))
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO conversations(conversation_id,title,created_at,updated_at) "
                "VALUES ('renamed','Custom title','2026-01-01T00:00:00Z','2026-01-01T00:01:00Z')"
            )
            connection.execute(
                "INSERT INTO conversations(conversation_id,title,created_at,updated_at) "
                "VALUES ('untouched','New Conversation','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
            )

        assert MigrationRunner(database, default_registry()).migrate() == [19, 20, 21, 22, 23, 24, 25, 26, 27, 28]
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT conversation_id,is_title_custom FROM conversations ORDER BY conversation_id"
            ).fetchall()
            states = {row["conversation_id"]: row["is_title_custom"] for row in rows}
        assert states == {"renamed": 1, "untouched": 0}
    finally:
        database.dispose()
        path.unlink()


def test_migration_0015_upgrades_version_14_without_resetting_existing_data() -> None:
    database, path = _file_database()
    try:
        registry_through_14 = MigrationRegistry()
        for migration in default_registry():
            if migration.version <= 14:
                registry_through_14.register(migration)
        assert MigrationRunner(database, registry_through_14).migrate() == list(range(1, 15))
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO projects (id, name, description, instructions, is_archived, created_at, updated_at) "
                "VALUES ('existing-project', 'Keep me', NULL, NULL, 0, '2026-01-01T00:00:00+00:00', "
                "'2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO conversations "
                "(conversation_id, title, created_at, updated_at, is_pinned, is_archived, folder_id, project_id) "
                "VALUES ('existing-conversation', 'Keep conversation', "
                "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 0, 0, NULL, 'existing-project')"
            )
        assert MigrationRunner(database, default_registry()).migrate() == [
            15,
            16,
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
            28,
        ]
        assert MigrationRunner(database, default_registry()).migrate() == []
        assert MigrationRunner(database, default_registry()).current_version() == 28
        with database.connect() as connection:
            project_name = connection.execute("SELECT name FROM projects WHERE id='existing-project'").fetchone()[0]
            assert project_name == "Keep me"
            assert (
                connection.execute(
                    "SELECT title FROM conversations WHERE conversation_id='existing-conversation'"
                ).fetchone()[0]
                == "Keep conversation"
            )
            assert connection.execute("SELECT COUNT(*) FROM core_prompts").fetchone()[0] == 0
    finally:
        database.dispose()
        path.unlink()


def test_migration_0017_upgrades_populated_schema_16_additively() -> None:
    database, path = _file_database()
    try:
        before_17 = MigrationRegistry()
        for migration in default_registry():
            if migration.version <= 16:
                before_17.register(migration)
        assert MigrationRunner(database, before_17).migrate() == list(range(1, 17))
        timestamp = "2026-01-01T00:00:00+00:00"
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p1', 'Existing', ?, ?)",
                (timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO conversation_folders (id, name, created_at, updated_at) VALUES ('f1', 'Folder', ?, ?)",
                (timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO conversations (conversation_id, title, created_at, updated_at, folder_id, project_id) "
                "VALUES ('c1', 'Conversation', ?, ?, 'f1', 'p1')",
                (timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO messages (message_id, conversation_id, role, status, content, created_at, updated_at) "
                "VALUES ('m1', 'c1', 'user', 'complete', 'hello', ?, ?)",
                (timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES ('r1', 'completed', ?, ?)",
                (timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO run_events (event_id, run_id, event_type, seq, timestamp, payload, contract_version) "
                "VALUES ('e1', 'r1', 'run_started', 1, ?, '{}', 'v1')",
                (timestamp,),
            )
            connection.execute(
                "INSERT INTO core_prompts (id, name, prompt_text, category, is_enabled, created_at, updated_at) "
                "VALUES ('prompt1', 'Prompt', 'Keep', 'general', 1, ?, ?)",
                (timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO core_prompt_assignments "
                "(id, core_prompt_id, scope_type, scope_id, mode, created_at, updated_at) "
                "VALUES ('assignment1', 'prompt1', 'project', 'p1', 'enable', ?, ?)",
                (timestamp, timestamp),
            )

        runner = MigrationRunner(database, default_registry())
        assert runner.migrate() == [17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]
        assert runner.migrate() == []
        with database.connect() as connection:
            project = connection.execute(
                "SELECT name, default_runtime_key, default_model_id FROM projects WHERE id='p1'"
            ).fetchone()
            assert tuple(project) == ("Existing", None, None)
            for table in (
                "conversations",
                "conversation_folders",
                "messages",
                "runs",
                "run_events",
                "core_prompts",
                "core_prompt_assignments",
            ):
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM project_files").fetchone()[0] == 0
            columns = connection.execute("PRAGMA table_info(project_files)").fetchall()
            assert columns[-1]["name"] == "normalized_file_name"
            index_names = {row["name"] for row in connection.execute("PRAGMA index_list(project_files)")}
            assert "ux_project_files_project_normalized_name" in index_names
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        database.dispose()
        path.unlink()


def test_migration_records_version_and_name_metadata() -> None:
    database, path = _file_database()
    try:
        MigrationRunner(database, default_registry()).migrate()
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT version, name, applied_at FROM ava_schema_migrations ORDER BY version"
            ).fetchall()
        assert len(rows) == 28
        assert [(row["version"], row["name"]) for row in rows] == [
            (1, "initial application persistence schema"),
            (2, "document revision history"),
            (3, "attachment metadata"),
            (4, "provider connections"),
            (5, "model configurations"),
            (6, "runtime configurations"),
            (7, "application execution defaults"),
            (8, "durable conversation run relationships"),
            (9, "durable run cancellation request"),
            (10, "conversation organization metadata"),
            (11, "conversation folders"),
            (12, "projects"),
            (13, "conversation Project relationship"),
            (14, "conversation Project lookup index"),
            (15, "CORE prompt definitions"),
            (16, "Scoped CORE prompt assignments"),
            (17, "Project execution defaults"),
            (18, "Project files"),
            (19, "Conversation title ownership"),
            (20, "Run inspection snapshots"),
            (21, "Configured model context windows"),
            (22, "Conversation context summaries"),
            (23, "Project file name uniqueness"),
            (24, "tool feature configuration"),
            (25, "workspace access configuration"),
            (26, "durable tool approvals"),
            (27, "run execution mode"),
            (28, "durable tool invocation reservations"),
        ]
        assert rows[0]["applied_at"].startswith("20")
        assert rows[1]["applied_at"].startswith("20")
        assert rows[2]["applied_at"].startswith("20")
    finally:
        database.dispose()
        path.unlink()


def test_v2_migration_creates_the_document_revisions_table() -> None:
    """The default registry adds the document revision history table on top of v0001."""
    from ava.infrastructure.persistence.migrations.versions import v0002_document_revisions

    assert v0002_document_revisions.VERSION == 2
    assert v0002_document_revisions.NAME == "document revision history"
    assert v0002_document_revisions.EXPECTED_TABLES == ("document_revisions",)
    statements = " ".join(v0002_document_revisions.STATEMENTS)
    assert statements.count("CREATE TABLE") == 1

    database, path = _file_database()
    try:
        MigrationRunner(database, default_registry()).migrate()
        with database.connect() as connection:
            columns = [row[1] for row in connection.execute('PRAGMA table_info("document_revisions")')]
        assert columns == [
            "id",
            "revision_id",
            "document_id",
            "revision_number",
            "title",
            "content",
            "content_format",
            "created_at",
        ]
    finally:
        database.dispose()
        path.unlink()


def test_v3_migration_creates_the_attachments_table() -> None:
    """The default registry adds the attachment metadata table on top of v0002."""
    from ava.infrastructure.persistence.migrations.versions import v0003_attachments

    assert v0003_attachments.VERSION == 3
    assert v0003_attachments.NAME == "attachment metadata"
    assert v0003_attachments.EXPECTED_TABLES == ("attachments",)
    statements = " ".join(v0003_attachments.STATEMENTS)
    assert statements.count("CREATE TABLE") == 1
    assert statements.count("CREATE INDEX") == 1

    database, path = _file_database()
    try:
        MigrationRunner(database, default_registry()).migrate()
        with database.connect() as connection:
            columns = [row[1] for row in connection.execute('PRAGMA table_info("attachments")')]
            indexes = {row["name"] for row in connection.execute('PRAGMA index_list("attachments")')}
        assert columns == [
            "id",
            "attachment_id",
            "file_name",
            "media_type",
            "size_bytes",
            "storage_key",
            "owner_type",
            "owner_id",
            "status",
            "created_at",
        ]
        assert "idx_attachments_owner" in indexes
    finally:
        database.dispose()
        path.unlink()


def test_v3_attachments_table_enforces_metadata_invariants_at_the_database_level() -> None:
    """Uniqueness, owner-pair, size, and vocabulary checks are database constraints."""
    database = SqliteDatabase(":memory:")
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
            "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "attachment-1",
                "report.pdf",
                "application/pdf",
                10,
                "k1",
                "document",
                "doc-1",
                "available",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "attachment-1",
                    "report.pdf",
                    "application/pdf",
                    10,
                    "k2",
                    "document",
                    "doc-1",
                    "available",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "attachment-2",
                    "report.pdf",
                    "application/pdf",
                    10,
                    "k1",
                    "document",
                    "doc-1",
                    "available",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "attachment-3",
                    "report.pdf",
                    "application/pdf",
                    10,
                    "k3",
                    "document",
                    None,
                    "available",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "attachment-4",
                    "report.pdf",
                    "application/pdf",
                    -1,
                    "k4",
                    None,
                    None,
                    "available",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "attachment-5",
                    "report.pdf",
                    "application/pdf",
                    10,
                    "k5",
                    "document",
                    "doc-1",
                    "unknown",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
    database.dispose()


def test_document_revisions_constraints_enforced_at_the_database_level() -> None:
    """Revision id uniqueness and per-document numbering are database constraints."""
    import sqlite3

    database = SqliteDatabase(":memory:")
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO document_revisions (revision_id, document_id, revision_number, "
            "title, content, content_format, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("revision-1", "doc-1", 1, "T", "<p></p>", "html", "2026-01-01T00:00:00+00:00"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO document_revisions (revision_id, document_id, revision_number, "
                "title, content, content_format, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("revision-1", "doc-2", 1, "T", "<p></p>", "html", "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO document_revisions (revision_id, document_id, revision_number, "
                "title, content, content_format, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("revision-2", "doc-1", 1, "T", "<p></p>", "html", "2026-01-01T00:00:00+00:00"),
            )
    database.dispose()


# ============================================================
# Legacy (Step 4.6 schema, no migration metadata) databases
# ============================================================


def test_migrate_adopts_a_legacy_step4_6_database_without_destroying_data() -> None:
    database, path = _file_database()
    try:
        _make_legacy_schema(path)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES ("
                "'legacy-run', 'completed', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )

        runner = MigrationRunner(database, default_registry())
        assert runner.current_version() == 0
        assert runner.migrate() == list(range(1, 29))
        assert runner.current_version() == 28
        assert _metadata_versions(database) == list(range(1, 29))
        with database.connect() as connection:
            row = connection.execute("SELECT run_id, status, execution_mode FROM runs").fetchone()
        assert row["run_id"] == "legacy-run"
        assert row["status"] == "completed"
        assert row["execution_mode"] == "chat"
        assert "document_revisions" in _tables(database)
        assert "attachments" in _tables(database)
        assert list(runner.pending_migrations()) == []
    finally:
        database.dispose()
        path.unlink()


def test_legacy_v1_v2_database_upgrades_to_v3_without_backfill() -> None:
    """A valid pre-v3 (v0001+v0002) database upgrades without touching data.

    Only the attachment table is added; existing documents, revisions,
    conversations, messages, and runs/events are preserved, and no attachment
    rows are synthesized from existing entities.
    """
    from ava.infrastructure.persistence.migrations.versions import (
        v0001_initial_schema,
        v0002_document_revisions,
    )

    database, path = _file_database()
    try:
        pre_v3 = MigrationRegistry()
        for version_module in (v0001_initial_schema, v0002_document_revisions):
            pre_v3.register(
                Migration(
                    version=version_module.VERSION,
                    name=version_module.NAME,
                    up=version_module.migrate_up,
                    verify=version_module.verify_structure,
                    expected_tables=version_module.EXPECTED_TABLES,
                )
            )
        MigrationRunner(database, pre_v3).migrate()
        database.dispose()

        with sqlite3.connect(path) as connection:
            connection.execute(
                "INSERT INTO documents (document_id, title, content, content_format, created_at, updated_at) "
                "VALUES ('doc-1', 'T', '<p>x</p>', 'html', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO conversations (conversation_id, title, created_at, updated_at) VALUES "
                "('conv-1', 'C', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO messages (message_id, conversation_id, role, status, content, created_at, updated_at) "
                "VALUES ('msg-1', 'conv-1', 'user', 'complete', 'hello', "
                "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES "
                "('run-1', 'completed', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
        before = _tables(database)
        assert "attachments" not in before
        assert "document_revisions" in before

        runner = MigrationRunner(database, default_registry())
        assert runner.migrate() == list(range(3, 29))
        assert _metadata_versions(database) == list(range(1, 29))

        with database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM document_revisions").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
            row = connection.execute("SELECT title FROM conversations WHERE conversation_id = 'conv-1'").fetchone()
        assert row["title"] == "C"
        assert "attachments" in _tables(database)
    finally:
        database.dispose()
        path.unlink()


def test_create_relational_repositories_adopts_a_legacy_database_usable_through_ports() -> None:
    path = Path(tempfile.mktemp(suffix=".sqlite3"))
    try:
        _make_legacy_schema(path)
        repositories = create_relational_repositories(str(path))
        assert repositories.run_repository.get("maybe-absent") is None
        repositories.run_repository.create("via-port")
        assert repositories.run_repository.get("via-port") is not None
        repositories.dispose()
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM ava_schema_migrations").fetchone()[0] == 28
    finally:
        path.unlink()


def test_unknown_legacy_database_is_rejected_without_destructive_rewrite() -> None:
    database, path = _file_database()
    try:
        _make_legacy_schema(path)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE future_unknown_table (id INTEGER PRIMARY KEY)")
        tables_before = _tables(database)

        runner = MigrationRunner(database, default_registry())
        with pytest.raises(SchemaValidationError, match="unexpected tables"):
            runner.migrate()
        assert runner.current_version() == 0
        assert _tables(database) == tables_before
        assert "ava_schema_migrations" not in tables_before
    finally:
        database.dispose()
        path.unlink()


# ============================================================
# Transactionality and rollback
# ============================================================


def _registry_v1_v2_with_v3_failing() -> MigrationRegistry:
    registry = MigrationRegistry()

    def v1_up(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE mtest_v1 (id INTEGER PRIMARY KEY)")

    def v2_up(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE mtest_v2 (id INTEGER PRIMARY KEY)")

    def v3_up(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE mtest_v3 (id INTEGER PRIMARY KEY)")
        raise RuntimeError("boom")

    registry.register(Migration(version=3, name="v3", up=v3_up))
    registry.register(Migration(version=1, name="v1", up=v1_up))
    registry.register(Migration(version=2, name="v2", up=v2_up))
    return registry


def test_failed_migration_rolls_back_to_the_previous_version() -> None:
    database, path = _file_database()
    try:
        runner = MigrationRunner(database, _registry_v1_v2_with_v3_failing())
        with pytest.raises(MigrationError, match=r"v3\) failed"):
            runner.migrate()
        assert runner.current_version() == 2
        assert _metadata_versions(database) == [1, 2]
        tables = _tables(database)
        assert {"mtest_v1", "mtest_v2"} <= tables
        assert "mtest_v3" not in tables
    finally:
        database.dispose()
        path.unlink()


def test_migrations_apply_deterministically_in_explicit_version_order() -> None:
    database, path = _file_database()
    try:
        runner = MigrationRunner(database, _registry_v1_v2_with_v3_failing())
        with pytest.raises(MigrationError):
            runner.migrate()
        assert runner.current_version() == 2
        assert _metadata_versions(database) == [1, 2]
    finally:
        database.dispose()
        path.unlink()


def test_a_successful_retry_applies_only_the_pending_migration() -> None:
    database, path = _file_database()
    try:
        failed_runner = MigrationRunner(database, _registry_v1_v2_with_v3_failing())
        with pytest.raises(MigrationError):
            failed_runner.migrate()

        registry = MigrationRegistry()

        def v1_up(connection: sqlite3.Connection) -> None:
            connection.execute("CREATE TABLE mtest_v1 (id INTEGER PRIMARY KEY)")

        def v2_up(connection: sqlite3.Connection) -> None:
            connection.execute("CREATE TABLE mtest_v2 (id INTEGER PRIMARY KEY)")

        def v3_up(connection: sqlite3.Connection) -> None:
            connection.execute("CREATE TABLE mtest_v3 (id INTEGER PRIMARY KEY)")

        registry.register(Migration(version=3, name="v3", up=v3_up))
        registry.register(Migration(version=1, name="v1", up=v1_up))
        registry.register(Migration(version=2, name="v2", up=v2_up))
        retry_runner = MigrationRunner(database, registry)
        assert [m.version for m in retry_runner.pending_migrations()] == [3]
        assert retry_runner.migrate() == [3]
        assert retry_runner.current_version() == 3
        assert _metadata_versions(database) == [1, 2, 3]
    finally:
        database.dispose()
        path.unlink()


# ============================================================
# Registration rules
# ============================================================


def test_duplicate_version_registration_is_rejected() -> None:
    registry = MigrationRegistry()
    registry.register(Migration(version=1, name="v1", up=lambda c: None))
    with pytest.raises(MigrationError, match="duplicate migration version 1"):
        registry.register(Migration(version=1, name="v1-dup", up=lambda c: None))


def test_non_positive_versions_are_rejected() -> None:
    registry = MigrationRegistry()
    with pytest.raises(MigrationError, match="positive"):
        registry.register(Migration(version=0, name="v0", up=lambda c: None))
    with pytest.raises(MigrationError, match="positive"):
        registry.register(Migration(version=-1, name="v-1", up=lambda c: None))


def test_registry_iterates_ascending_and_reports_max_version() -> None:
    registry = MigrationRegistry()
    for version in (3, 1, 2):
        registry.register(Migration(version=version, name=f"v{version}", up=lambda c: None))
    assert [m.version for m in registry] == [1, 2, 3]
    assert registry.versions() == [1, 2, 3]
    assert registry.max_version() == 3
    assert 2 in registry
    assert 4 not in registry


# ============================================================
# Database newer than the code
# ============================================================


def _registry_through_v2() -> MigrationRegistry:
    registry = MigrationRegistry()

    def v1_up(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE newer_v1 (id INTEGER PRIMARY KEY)")

    def v2_up(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE newer_v2 (id INTEGER PRIMARY KEY)")

    registry.register(Migration(version=1, name="v1", up=v1_up))
    registry.register(Migration(version=2, name="v2", up=v2_up))
    return registry


def test_database_newer_than_application_is_rejected_without_downgrade() -> None:
    database, path = _file_database()
    try:
        MigrationRunner(database, _registry_through_v2()).migrate()

        older_registry = MigrationRegistry()
        older_registry.register(Migration(version=1, name="v1", up=lambda c: None))
        older_runner = MigrationRunner(database, older_registry)
        expected = r"version 2 is newer than this application supports.*never performed"
        with pytest.raises(UnsupportedSchemaVersionError, match=expected):
            older_runner.migrate()
        with pytest.raises(UnsupportedSchemaVersionError, match="version 2 is newer"):
            older_runner.pending_migrations()
        assert older_runner.current_version() == 2
        assert _metadata_versions(database) == [1, 2]
    finally:
        database.dispose()
        path.unlink()


def _registry_through_v3() -> MigrationRegistry:
    registry = MigrationRegistry()

    def v1_up(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE newer_v1 (id INTEGER PRIMARY KEY)")

    def v2_up(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE newer_v2 (id INTEGER PRIMARY KEY)")

    def v3_up(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE newer_v3 (id INTEGER PRIMARY KEY)")

    registry.register(Migration(version=1, name="v1", up=v1_up))
    registry.register(Migration(version=2, name="v2", up=v2_up))
    registry.register(Migration(version=3, name="v3", up=v3_up))
    return registry


def test_gap_in_applied_history_is_rejected() -> None:
    database, path = _file_database()
    try:
        with database.connect() as connection:
            connection.execute(
                "CREATE TABLE ava_schema_migrations (version INTEGER PRIMARY KEY, "
                "name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO ava_schema_migrations (version, name, applied_at) VALUES "
                "(1, 'v1', '2026-01-01T00:00:00+00:00'), "
                "(3, 'v3', '2026-01-01T00:00:00+00:00')"
            )

        runner = MigrationRunner(database, _registry_through_v3())
        with pytest.raises(MigrationError, match="missing version"):
            runner.migrate()
    finally:
        database.dispose()
        path.unlink()


def test_malformed_metadata_table_is_rejected() -> None:
    database, path = _file_database()
    try:
        with database.connect() as connection:
            connection.execute("CREATE TABLE ava_schema_migrations (version TEXT)")
        runner = MigrationRunner(database, default_registry())
        with pytest.raises(SchemaValidationError, match="unexpected structure"):
            runner.migrate()
    finally:
        database.dispose()
        path.unlink()


# ============================================================
# Durability across reopen
# ============================================================


def test_migrated_file_database_keeps_schema_and_data_across_reopen() -> None:
    path = Path(tempfile.mktemp(suffix=".sqlite3"))
    try:
        first = SqliteDatabase(str(path), auto_migrate=False)
        MigrationRunner(first, default_registry()).migrate()
        with first.connect() as connection:
            connection.execute(
                "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES ("
                "'durable', 'completed', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
            )
        first.dispose()

        reopened = SqliteDatabase(str(path), auto_migrate=False)
        runner = MigrationRunner(reopened, default_registry())
        assert runner.current_version() == 28
        assert runner.migrate() == []
        with reopened.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        reopened.dispose()
    finally:
        path.unlink()


# ============================================================
# Initial-migration structure verification
# ============================================================


def test_initial_migration_statements_match_the_step_4_6_schema() -> None:
    from ava.infrastructure.persistence.migrations.versions import v0001_initial_schema

    assert v0001_initial_schema.VERSION == 1
    assert v0001_initial_schema.NAME == "initial application persistence schema"
    assert v0001_initial_schema.EXPECTED_TABLES == (
        "runs",
        "run_events",
        "conversations",
        "messages",
        "documents",
    )
    statements = " ".join(v0001_initial_schema.STATEMENTS)
    assert statements.count("CREATE TABLE") == 5
    assert "ava_schema_migrations" not in statements


# ============================================================
# Phase 5.24: durable run cancellation request
# ============================================================


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


def _seed_version_8_run(database: SqliteDatabase, path: Path) -> None:
    """Reduce a database to the pre-5.24 shape and give it two runs."""
    only_through_eight = MigrationRegistry()
    for migration in default_registry():
        if migration.version > 8:
            break
        only_through_eight.register(migration)
    MigrationRunner(database, only_through_eight).migrate()
    database.dispose()

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES ("
            "'old-run', 'completed', '2026-02-03T04:05:06+00:00', '2026-02-03T04:05:06+00:00')"
        )
        connection.execute(
            "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES ("
            "'old-running', 'running', '2026-02-03T04:05:06+00:00', '2026-02-03T04:05:06+00:00')"
        )
        connection.commit()


def test_v9_adds_a_nullable_cancellation_request_column() -> None:
    from ava.infrastructure.persistence.migrations.versions import v0009_run_cancellation_request

    assert v0009_run_cancellation_request.VERSION == 9
    assert v0009_run_cancellation_request.NAME == "durable run cancellation request"
    assert v0009_run_cancellation_request.EXPECTED_COLUMNS[-1] == "cancellation_requested_at"


def test_v9_leaves_existing_runs_with_no_cancellation_request() -> None:
    """Existing rows gain a NULL, which is the truth for pre-5.24 runs.

    There is deliberately no backfill: inventing a request time for a run that
    predates the feature would be fabricating evidence that nobody asked.
    """
    database, path = _file_database()
    try:
        _seed_version_8_run(database, path)
        database.dispose()

        reopened = SqliteDatabase(str(path), auto_migrate=False)
        try:
            runner = MigrationRunner(reopened, default_registry())
            assert runner.current_version() == 8
            assert runner.migrate() == [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]

            with reopened.connect() as connection:
                assert "cancellation_requested_at" in _table_columns(connection, "runs")
                rows = connection.execute(
                    "SELECT run_id, status, cancellation_requested_at FROM runs ORDER BY run_id"
                ).fetchall()
            assert [(row["run_id"], row["status"], row["cancellation_requested_at"]) for row in rows] == [
                ("old-run", "completed", None),
                ("old-running", "running", None),
            ]
        finally:
            reopened.dispose()
    finally:
        Path(path).unlink(missing_ok=True)


def test_v9_preserves_the_existing_runs_table_and_its_rows() -> None:
    database, path = _file_database()
    try:
        _seed_version_8_run(database, path)
        database.dispose()

        reopened = SqliteDatabase(str(path), auto_migrate=False)
        try:
            MigrationRunner(reopened, default_registry()).migrate()
            with reopened.connect() as connection:
                assert tuple(_table_columns(connection, "runs")) == (
                    "run_id",
                    "status",
                    "created_at",
                    "updated_at",
                    "execution_selection",
                    "conversation_id",
                    "source_user_message_id",
                    "assistant_message_id",
                    "cancellation_requested_at",
                    "inspection_snapshot",
                    "execution_mode",
                )
                assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' "
                        "AND name = 'idx_runs_cancellation_requested'"
                    ).fetchone()[0]
                    == 1
                )
        finally:
            reopened.dispose()
    finally:
        Path(path).unlink(missing_ok=True)


def test_a_cancellation_request_written_after_migration_survives_reopen() -> None:
    database, path = _file_database()
    try:
        MigrationRunner(database, default_registry()).migrate()
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO runs (run_id, status, created_at, updated_at, cancellation_requested_at) "
                "VALUES ('run-1', 'running', '2026-02-03T04:05:06+00:00', "
                "'2026-02-03T04:05:06+00:00', '2026-02-03T05:00:00+00:00')"
            )
            connection.commit()
        database.dispose()

        reopened = SqliteDatabase(str(path), auto_migrate=False)
        try:
            with reopened.connect() as connection:
                row = connection.execute(
                    "SELECT status, cancellation_requested_at FROM runs WHERE run_id = 'run-1'"
                ).fetchone()
            assert row["status"] == "running"
            assert row["cancellation_requested_at"] == "2026-02-03T05:00:00+00:00"
        finally:
            reopened.dispose()
    finally:
        Path(path).unlink(missing_ok=True)
