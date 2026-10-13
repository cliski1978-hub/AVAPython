"""Versioned migration registry (Step 4.7).

The registry is the authoritative, deterministic sequence of schema
migrations for the application. Ordering is derived from explicit integer
versions — execution follows strict ascending version order and never depends
on filesystem enumeration or import order.

Guarantees enforced here:

* a version may be registered at most once (duplicate versions are rejected);
* every version is a positive integer (zero/negative/non-numeric are rejected);
* iteration yields migrations in ascending version order.
"""

from collections.abc import Iterator

from ava.infrastructure.persistence.migrations.migration import Migration, MigrationError

# ============================================================
# BEGIN: Migration registry
# ============================================================


class MigrationRegistry:
    """An ordered, deduplicated collection of schema migrations."""

    def __init__(self) -> None:
        self._migrations: dict[int, Migration] = {}

    def register(self, migration: Migration) -> None:
        """Register a migration, rejecting duplicates and invalid versions."""
        version = migration.version
        if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
            raise MigrationError(
                f"migration version must be a positive integer, got {version!r} for {migration.name!r}"
            )
        if version in self._migrations:
            raise MigrationError(f"duplicate migration version {version} ({migration.name!r})")
        self._migrations[version] = migration

    def get(self, version: int) -> Migration | None:
        """Return the migration for a version, or ``None`` when unknown."""
        return self._migrations.get(version)

    def versions(self) -> list[int]:
        """Return all registered versions in deterministic ascending order."""
        return sorted(self._migrations)

    def max_version(self) -> int:
        """Return the highest registered version, or 0 when empty."""
        return self.versions()[-1] if self._migrations else 0

    def verify(self) -> None:
        """Fail closed if the registry is structurally invalid.

        A registry is valid when every stored migration is a positive integer
        version that agrees with the version it is stored under. Duplicate
        registration is already rejected by ``register``; this cross-checks
        the stored entries (e.g. after external mutation). Registration order
        is irrelevant — deterministic application order always follows version.
        """
        for key, migration in self._migrations.items():
            if migration.version != key:
                raise MigrationError(
                    "migration registry contains an internally inconsistent version "
                    f"(stored under {key}, declares {migration.version})"
                )
            if migration.version <= 0:
                raise MigrationError(f"migration registry contains invalid version {migration.version}")

    def __iter__(self) -> Iterator[Migration]:
        return (self._migrations[version] for version in self.versions())

    def __len__(self) -> int:
        return len(self._migrations)

    def __contains__(self, version: int) -> bool:
        return version in self._migrations


# ============================================================
# END: Migration registry
# ============================================================
