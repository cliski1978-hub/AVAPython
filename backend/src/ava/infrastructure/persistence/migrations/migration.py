"""Migration primitives and the migration error boundary (Step 4.7).

A ``Migration`` is a named, versioned, ordered schema step:

* ``version`` — an explicit non-zero positive integer. Ordering is derived
  from the version number, never from filesystem enumeration or import order.
* ``name`` — a short human description recorded in the metadata table.
* ``up`` — the forward operation, applied transactionally and exactly once.
* ``verify`` (optional) — a structural validator used to detect an
  incompatible/corrupted database at that version before anything is stamped
  or migrated.
* ``expected_tables`` — the application tables this migration creates; used to
  recognize a legacy database that already carries this shape.

Errors raised by the migration system are isolated behind ``MigrationError`` so
raw ``sqlite3`` exceptions never escape the persistence infrastructure. The
subclasses give callers a stable way to distinguish the failure class:

* ``SchemaValidationError`` — an existing database does not match any schema
  the application knows how to validate (unknown/incompatible legacy layout).
* ``UnsupportedSchemaVersionError`` — the database is at a version newer than
  the running application supports; downgrades are never attempted.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from ava.infrastructure.persistence.errors import PersistenceError

# ============================================================
# BEGIN: Migration error boundary
# ============================================================


class MigrationError(PersistenceError):
    """A schema-migration failure at the persistence-infrastructure boundary."""


class SchemaValidationError(MigrationError):
    """An existing database does not match the expected schema structure."""


class UnsupportedSchemaVersionError(MigrationError):
    """The database schema is newer than the running application supports."""


# ============================================================
# END: Migration error boundary
# ============================================================


# ============================================================
# BEGIN: Migration
# ============================================================


@dataclass(frozen=True)
class Migration:
    """A single versioned, ordered schema migration.

    Frozen by convention: a migration is a versioned constant whose identity
    is its ``version`` and whose integrity is its ``up``/``verify``
    operations. The runner executes the registry's ``up`` operations in strict
    ascending version order, each inside its own transaction.
    """

    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]
    verify: Callable[[sqlite3.Connection], None] | None = None
    expected_tables: tuple[str, ...] = ()


# ============================================================
# END: Migration
# ============================================================
