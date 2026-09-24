"""AVA's version-controlled schema migration system (Step 4.7).

The migration system is the single authoritative mechanism for creating and
evolving the relational schema. It lives entirely inside
``ava.infrastructure.persistence`` and is never exposed through repository
ports, contracts, services, or HTTP endpoints.

Public vocabulary (infrastructure-owned):

* ``Migration`` — a named, versioned, ordered schema step.
* ``MigrationRegistry`` — the deterministic, deduplicated migration sequence.
* ``MigrationRunner`` — applies/verifies migrations against a database.
* ``default_registry`` — the application's authoritative migration sequence.
* errors: ``MigrationError``, ``SchemaValidationError``,
  ``UnsupportedSchemaVersionError``.
"""

from ava.infrastructure.persistence.migrations.migration import (
    Migration,
    MigrationError,
    SchemaValidationError,
    UnsupportedSchemaVersionError,
)
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.migrations.runner import (
    AppliedMigration,
    MigrationRunner,
)
from ava.infrastructure.persistence.migrations.versions import default_registry

__all__ = [
    "AppliedMigration",
    "Migration",
    "MigrationError",
    "MigrationRegistry",
    "MigrationRunner",
    "SchemaValidationError",
    "UnsupportedSchemaVersionError",
    "default_registry",
]