"""AVA's application migration versions (Step 4.7).

``default_registry()`` is the authoritative, application-owned migration
sequence. Version 0001 reproduces the Step 4.6 five-table schema; version 0002
(Step 4.13.C) adds the document revision history table; version 0003
(Step 4.14.C) adds the attachment metadata table. Later versions are added
here as real AVA schema evolution requires them. The registry is built from
explicit versions, never from directory/import order.
"""

from ava.infrastructure.persistence.migrations.migration import Migration
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.migrations.versions import (
    v0001_initial_schema,
    v0002_document_revisions,
    v0003_attachments,
)

__all__ = ["default_registry"]


def default_registry() -> MigrationRegistry:
    """Return the application's ordered, versioned migration registry."""
    registry = MigrationRegistry()
    registry.register(
        Migration(
            version=v0001_initial_schema.VERSION,
            name=v0001_initial_schema.NAME,
            up=v0001_initial_schema.migrate_up,
            verify=v0001_initial_schema.verify_structure,
            expected_tables=v0001_initial_schema.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0002_document_revisions.VERSION,
            name=v0002_document_revisions.NAME,
            up=v0002_document_revisions.migrate_up,
            verify=v0002_document_revisions.verify_structure,
            expected_tables=v0002_document_revisions.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0003_attachments.VERSION,
            name=v0003_attachments.NAME,
            up=v0003_attachments.migrate_up,
            verify=v0003_attachments.verify_structure,
            expected_tables=v0003_attachments.EXPECTED_TABLES,
        )
    )
    return registry