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
        assert [m.version for m in runner.pending_migrations()] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert runner.migrate() == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert runner.current_version() == 9
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
        assert runner.current_version() == 9
        assert _tables(database) == tables_before
        assert _metadata_versions(database) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
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
        assert len(rows) == 9
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
            columns = [
                row[1] for row in connection.execute('PRAGMA table_info("document_revisions")')
            ]
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
            columns = [
                row[1] for row in connection.execute('PRAGMA table_info("attachments")')
            ]
            indexes = {
                row["name"] for row in connection.execute('PRAGMA index_list("attachments")')
            }
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
            ("attachment-1", "report.pdf", "application/pdf", 10, "k1", "document", "doc-1",
             "available", "2026-01-01T00:00:00+00:00"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("attachment-1", "report.pdf", "application/pdf", 10, "k2", "document", "doc-1",
                 "available", "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("attachment-2", "report.pdf", "application/pdf", 10, "k1", "document", "doc-1",
                 "available", "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("attachment-3", "report.pdf", "application/pdf", 10, "k3", "document", None,
                 "available", "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("attachment-4", "report.pdf", "application/pdf", -1, "k4", None, None,
                 "available", "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO attachments (attachment_id, file_name, media_type, size_bytes, "
                "storage_key, owner_type, owner_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("attachment-5", "report.pdf", "application/pdf", 10, "k5", "document", "doc-1",
                 "unknown", "2026-01-01T00:00:00+00:00"),
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
        assert runner.migrate() == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert runner.current_version() == 9
        assert _metadata_versions(database) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        with database.connect() as connection:
            row = connection.execute("SELECT run_id, status FROM runs").fetchone()
        assert row["run_id"] == "legacy-run"
        assert row["status"] == "completed"
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
        assert runner.migrate() == [3, 4, 5, 6, 7, 8, 9]
        assert _metadata_versions(database) == [1, 2, 3, 4, 5, 6, 7, 8, 9]

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
            assert connection.execute("SELECT COUNT(*) FROM ava_schema_migrations").fetchone()[0] == 9
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
        assert runner.current_version() == 9
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
            assert runner.migrate() == [9]

            with reopened.connect() as connection:
                assert _table_columns(connection, "runs")[-1] == "cancellation_requested_at"
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
                    "run_id", "status", "created_at", "updated_at", "execution_selection",
                    "conversation_id", "source_user_message_id", "assistant_message_id",
                    "cancellation_requested_at",
                )
                assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
                assert connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' "
                    "AND name = 'idx_runs_cancellation_requested'"
                ).fetchone()[0] == 1
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
