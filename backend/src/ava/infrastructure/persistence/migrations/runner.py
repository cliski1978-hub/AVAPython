"""Schema migration runner (Step 4.7).

The runner owns schema evolution end to end:

* it maintains the ``ava_schema_migrations`` metadata table (infrastructure-
  only; never exposed through repository ports);
* it inspects the database's applied migration history on every call;
* it fails closed when the database carries versions the application does not
  know (database newer than code — downgrades are never attempted);
* it recognizes a fresh empty database (run pending migrations) versus a
  Step 4.6 legacy database (no metadata, existing five-table schema — validate
  the exact expected structure, then stamp version 1 without touching data);
* it applies each pending migration inside its own transaction
  (``BEGIN IMMEDIATE … migrate … record success … COMMIT``) so a failed
  migration rolls back completely and the database remains at its prior valid
  version;
* it is idempotent: ``migrate()`` on an already-current database applies
  nothing and changes nothing.

The runner is engine-neutral by design (it drives the ``SqliteDatabase``
lifecycle seam), so a future SQLAlchemy/MSSQL swap reuses the same versioned
registry and metadata vocabulary.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.migrations.migration import (
    Migration,
    MigrationError,
    SchemaValidationError,
    UnsupportedSchemaVersionError,
)
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.migrations.validation import table_columns, table_exists

#: Infrastructure-only schema version record. Never exposed via repository ports.
_METADATA_TABLE = "ava_schema_migrations"
_EXPECTED_METADATA_COLUMNS = ("version", "name", "applied_at")

_INSERT_APPLIED_SQL = f"INSERT INTO {_METADATA_TABLE} (version, name, applied_at) VALUES (?, ?, ?)"


def _now_iso() -> str:
    """Render the current instant as an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


# ============================================================
# BEGIN: Applied migration
# ============================================================


@dataclass(frozen=True)
class AppliedMigration:
    """A migration already recorded as successfully applied."""

    version: int
    name: str
    applied_at: str


# ============================================================
# END: Applied migration
# ============================================================


# ============================================================
# BEGIN: Migration runner
# ============================================================


class MigrationRunner:
    """Applies and verifies the versioned schema migrations for a database.

    Args:
        database: The ``SqliteDatabase`` lifecycle seam to run against.
        registry: The ordered migration registry (the application's default
            registry, or a test-only registry for isolated machinery tests).
    """

    def __init__(self, database: SqliteDatabase, registry: MigrationRegistry) -> None:
        self._database = database
        self._registry = registry

    def current_version(self) -> int:
        """Return the highest successfully applied schema version (0 if none)."""
        self._registry.verify()
        with self._database.connect() as connection:
            applied = _read_applied(connection)
        return max((entry.version for entry in applied), default=0)

    def applied_migrations(self) -> list[AppliedMigration]:
        """Return the successfully applied migrations in ascending version order."""
        self._registry.verify()
        with self._database.connect() as connection:
            return _read_applied(connection)

    def pending_migrations(self) -> list[Migration]:
        """Return migrations the database still needs, in ascending order.

        Raises ``UnsupportedSchemaVersionError`` when the database is at a
        version newer than the registry supports.
        """
        self._registry.verify()
        with self._database.connect() as connection:
            _applied, current, unknown = self._state(connection)
        _reject_inconsistent(unknown, self._registry.max_version())
        return [migration for migration in self._registry if migration.version > current]

    def migrate(self) -> list[int]:
        """Bring the database to the latest supported schema version.

        Returns the versions applied during this call (``[]`` when the
        database was already current). A Step 4.6 legacy database is adopted
        by validating its exact structure and stamping version 1, preserving
        all existing data.
        """
        self._registry.verify()
        with self._database.connect() as connection:
            return self._migrate_on(connection)

    # ------------------------------------------------------------------
    # Internal flow
    # ------------------------------------------------------------------

    def _migrate_on(self, connection: sqlite3.Connection) -> list[int]:
        _applied, current, unknown = self._state(connection)
        _reject_inconsistent(unknown, self._registry.max_version())

        adopted = False
        if current == 0:
            adopted = self._adopt_legacy_if_applicable(connection)
            if adopted:
                current = 1
        if current:
            self._verify_current_schema(connection, current)

        applied_now: list[int] = [1] if adopted else []
        for migration in self._registry:
            if migration.version <= current:
                continue
            try:
                with self._database.transaction() as connection:
                    _ensure_metadata_table(connection)
                    migration.up(connection)
                    connection.execute(
                        _INSERT_APPLIED_SQL,
                        (migration.version, migration.name, _now_iso()),
                    )
            except MigrationError:
                raise
            except Exception as exc:  # noqa: BLE001 - driver/migration failures are wrapped with context
                raise MigrationError(f"migration {migration.version:04d} ({migration.name}) failed: {exc}") from exc
            applied_now.append(migration.version)
        return applied_now

    def _state(self, connection: sqlite3.Connection) -> tuple[list[AppliedMigration], int, set[int]]:
        """Inspect applied history, current version, and versions unknown to the registry.

        The applied history must be an exact prefix of the registry's sorted
        version sequence; any mismatch (a gap, or an extra unknown version)
        fails closed rather than guessing at ordering.
        """
        applied = _read_applied(connection)
        applied_versions = {entry.version for entry in applied}
        known = self._registry.versions()
        unknown = applied_versions - set(known)
        current = max(applied_versions, default=0)
        if not unknown and applied_versions:
            prefix = known[: len(applied_versions)]
            missing = sorted(set(prefix) - applied_versions)
            if missing or applied_versions - set(prefix):
                raise MigrationError(
                    f"schema migration history is missing version(s) {missing}; "
                    "refusing to migrate an out-of-order history"
                )
        return applied, current, unknown

    def _adopt_legacy_if_applicable(self, connection: sqlite3.Connection) -> bool:
        """Adopt a Step 4.6 legacy database (five-table schema, no metadata).

        Recognition: no applied migrations and some initial-schema tables
        already present. Adoption validates the exact expected structure and
        stamps version 1 — data is never recreated or destroyed. Any mismatch
        raises ``SchemaValidationError``.
        """
        initial = self._registry.get(1)
        if initial is None or not initial.expected_tables:
            return False
        if not any(table_exists(connection, table) for table in initial.expected_tables):
            return False  # fresh empty database: normal migration path
        if initial.verify is None:
            raise MigrationError("cannot adopt a legacy database without a migration-1 structure validator")
        initial.verify(connection)
        with self._database.transaction() as connection:
            _ensure_metadata_table(connection)
            connection.execute(_INSERT_APPLIED_SQL, (1, initial.name, _now_iso()))
        return True

    def _verify_current_schema(self, connection: sqlite3.Connection, current: int) -> None:
        """Verify the database still matches the schema expectations at ``current``."""
        migration = self._registry.get(current)
        if migration is None or migration.verify is None:
            return
        try:
            migration.verify(connection)
        except SchemaValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - unknown verification failures are wrapped
            raise MigrationError(f"schema verification at version {current} failed: {exc}") from exc


# ============================================================
# END: Migration runner
# ============================================================


def _reject_inconsistent(unknown: set[int], latest_known: int) -> None:
    """Fail closed when the database records versions the code does not know.

    A recorded version beyond the latest known one means the database was
    migrated by a newer application build: ``UnsupportedSchemaVersionError``
    and never a downgrade. A recorded version inside the known range that is
    simply absent from the registered sequence is an inconsistent history.
    """
    if not unknown:
        return
    newest = max(unknown)
    if newest > latest_known:
        raise UnsupportedSchemaVersionError(
            f"database schema version {newest} is newer than this application supports "
            f"(latest known: {latest_known}); automatic downgrade is never performed"
        )
    raise MigrationError(
        f"schema migration history records version(s) {sorted(unknown)} "
        "that are not in the registered sequence; refusing to proceed"
    )


def _ensure_metadata_table(connection: sqlite3.Connection) -> None:
    """Create the schema version metadata table (idempotent, infrastructure-only)."""
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ava_schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "applied_at TEXT NOT NULL)"
        )
    except sqlite3.Error as exc:
        raise MigrationError(f"could not create migration metadata table: {exc}") from exc


def _read_applied(connection: sqlite3.Connection) -> list[AppliedMigration]:
    """Read the applied migration history in ascending version order.

    A missing metadata table means no migrations have ever been applied. An
    existing but malformed metadata table fails closed with
    ``SchemaValidationError``.
    """
    if not table_exists(connection, _METADATA_TABLE):
        return []
    columns = table_columns(connection, _METADATA_TABLE)
    if columns != list(_EXPECTED_METADATA_COLUMNS):
        raise SchemaValidationError(
            f"migration metadata table {_METADATA_TABLE!r} has an unexpected structure: columns {columns}"
        )
    rows = connection.execute(f'SELECT version, name, applied_at FROM "{_METADATA_TABLE}" ORDER BY version').fetchall()
    return [
        AppliedMigration(
            version=cast(int, row["version"]),
            name=cast(str, row["name"]),
            applied_at=cast(str, row["applied_at"]),
        )
        for row in rows
    ]
