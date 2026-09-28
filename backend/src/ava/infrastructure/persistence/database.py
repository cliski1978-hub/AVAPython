"""SQLite database lifecycle and transaction boundaries (Step 4.6/4.7).

Step 4.7 moves schema ownership to the migration system. The database owns
connections, transactions, and disposal only:

* ``SqliteDatabase`` is the session factory / lifecycle owner. Services never
  receive it; only ``ava.infrastructure.persistence`` adapters and the
  migration runner do.
* Operations use explicit transactions (``BEGIN IMMEDIATE`` →
  ``COMMIT``/``ROLLBACK``) with ``isolation_level=None`` (autocommit) so no
  implicit transaction is opened by the driver.
* By default (``auto_migrate=True``) the first connection brings the schema to
  the latest supported version via the migration runner — the migration system
  is the single authoritative schema owner. ``auto_migrate=False`` defers that
  to an explicit ``ensure_schema()``.
* Driver exceptions never escape: duplicates become ``ValueError`` (the port's
  duplicate semantics) and other failures become ``PersistenceError``.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock

from ava.infrastructure.persistence.errors import PersistenceError

# ============================================================
# BEGIN: Database lifecycle
# ============================================================


class SqliteDatabase:
    """Owns a SQLite connection, auto-migration bootstrap, and transaction boundaries.

    The database is an engine-agnostic lifecycle seam: a parallel backend
    (e.g. SQLAlchemy + PostgreSQL) would offer the same shape — session
    factory, transaction, dispose — while the adapters keep consuming only the
    repository ports.
    """

    def __init__(self, url: str = ":memory:", *, auto_migrate: bool = True) -> None:
        self._url = url
        self._auto_migrate = auto_migrate
        self._connection: sqlite3.Connection | None = None
        self._savepoint_sequence = 0
        self._transaction_lock = RLock()

    @property
    def url(self) -> str:
        """The SQLite database location this instance manages."""
        return self._url

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield the shared connection, opening it (and running migrations) on first use.

        The connection is opened lazily so constructing a ``SqliteDatabase``
        never touches the filesystem or opens a file. Reopening after
        ``dispose()`` starts a fresh connection (a ``:memory:`` database
        restarts empty; a file-backed database reuses its durable content).
        Opening runs the default migration set when ``auto_migrate`` is set, so
        the schema is always at the latest supported version before a consumer
        touches it.
        """
        connection = self._connection
        if connection is None:
            connection = self._open()
            self._connection = connection
        yield connection

    def ensure_schema(self) -> None:
        """Bring the schema to the latest supported version via the migration system.

        Idempotent: on an already-current database this verifies the current
        version and applies nothing. This is the explicit bootstrap entry
        point for callers that construct the database with
        ``auto_migrate=False``.
        """
        from ava.infrastructure.persistence.migrations.runner import MigrationRunner
        from ava.infrastructure.persistence.migrations.versions import default_registry

        MigrationRunner(self, default_registry()).migrate()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block under an explicit immediate transaction.

        A successful block commits; a raised block rolls back and re-raises.
        On the single shared connection this keeps ordering-sensitive writes
        (event sequences, terminal-event sealing, status updates) atomic.
        """
        with self._transaction_lock, self.connect() as connection:
            if connection.in_transaction:
                # Repository operations can participate in one startup unit of
                # work without committing its enclosing transaction.
                self._savepoint_sequence += 1
                name = f"ava_nested_{self._savepoint_sequence}"
                connection.execute(f"SAVEPOINT {name}")
                try:
                    yield connection
                except BaseException:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
                    connection.execute(f"RELEASE SAVEPOINT {name}")
                    raise
                else:
                    connection.execute(f"RELEASE SAVEPOINT {name}")
                return
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as exc:
                raise PersistenceError(f"could not begin transaction: {exc}") from exc
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                try:
                    connection.execute("COMMIT")
                except sqlite3.Error as exc:
                    raise PersistenceError(f"could not commit transaction: {exc}") from exc

    def dispose(self) -> None:
        """Close the shared connection and drop any in-memory database state.

        File-backed databases remain durable (their content lives on disk);
        only an in-memory ``:memory:`` database is lost.
        """
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._url, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        self._connection = connection
        if self._auto_migrate:
            try:
                self.ensure_schema()
            except Exception:
                self._connection = None
                connection.close()
                raise
        return connection


# ============================================================
# END: Database lifecycle
# ============================================================


def translate_database_error(exc: sqlite3.Error, *, entity: str, key: str) -> Exception:
    """Map a driver error to repository-port semantics.

    Duplicate-key violations become ``ValueError`` (the port's duplicate
    error); every other database failure becomes a ``PersistenceError`` so raw
    driver exceptions and table/connection details never reach services.
    """
    if isinstance(exc, sqlite3.IntegrityError):
        return ValueError(f"{entity} already exists: {key}")
    return PersistenceError(f"{entity} persistence failure: {exc}")
