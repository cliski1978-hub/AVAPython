"""Concrete relational persistence adapters (Step 4.6/4.7).

This package is the only place in the AVA backend authorized to import
database drivers and ORM tooling. Repository ports, contracts, services, and
the API layer stay database-neutral. The default production composition still
uses the in-memory stores; this package is available and tested for the
relational activation step (4.8+).

Step 4.7 adds the version-controlled schema migration system
(``ava.infrastructure.persistence.migrations``): ``default_registry()`` owns
schema evolution, ``MigrationRunner`` applies/verifies it, and the database
lifecycle owns connections/transactions/dispose.
"""

from ava.infrastructure.persistence.composition import (
    PersistenceRepositories,
    create_relational_repositories,
)
from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.errors import PersistenceError
from ava.infrastructure.persistence.migrations import (
    AppliedMigration,
    Migration,
    MigrationError,
    MigrationRegistry,
    MigrationRunner,
    SchemaValidationError,
    UnsupportedSchemaVersionError,
    default_registry,
)

__all__ = [
    "AppliedMigration",
    "Migration",
    "MigrationError",
    "MigrationRegistry",
    "MigrationRunner",
    "PersistenceError",
    "PersistenceRepositories",
    "SchemaValidationError",
    "SqliteDatabase",
    "UnsupportedSchemaVersionError",
    "create_relational_repositories",
    "default_registry",
    "translate_database_error",
]