"""AVA's application migration versions (Step 4.7).

``default_registry()`` is the authoritative, application-owned migration
sequence. Versions 0001 through 0003 establish the Phase 4 schema; version
0004 adds Phase 5.3 provider connections, 0005 Phase 5.5 model configurations,
0006 Phase 5.7 runtime configurations, 0007 Phase 5.8 application execution
defaults, 0008 the Phase 5.19 durable run relationships, and 0009 the Phase
5.24 durable cancellation request. The registry is built from explicit
versions, never from directory/import order.
"""

from ava.infrastructure.persistence.migrations.migration import Migration
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.migrations.versions import (
    v0001_initial_schema,
    v0002_document_revisions,
    v0003_attachments,
    v0004_provider_connections,
    v0005_model_configurations,
    v0006_runtime_configurations,
    v0007_application_execution_defaults,
    v0008_run_conversation_relationships,
    v0009_run_cancellation_request,
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
    registry.register(
        Migration(
            version=v0004_provider_connections.VERSION,
            name=v0004_provider_connections.NAME,
            up=v0004_provider_connections.migrate_up,
            verify=v0004_provider_connections.verify_structure,
            expected_tables=v0004_provider_connections.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0005_model_configurations.VERSION,
            name=v0005_model_configurations.NAME,
            up=v0005_model_configurations.migrate_up,
            verify=v0005_model_configurations.verify_structure,
            expected_tables=v0005_model_configurations.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0006_runtime_configurations.VERSION,
            name=v0006_runtime_configurations.NAME,
            up=v0006_runtime_configurations.migrate_up,
            verify=v0006_runtime_configurations.verify_structure,
            expected_tables=v0006_runtime_configurations.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0007_application_execution_defaults.VERSION,
            name=v0007_application_execution_defaults.NAME,
            up=v0007_application_execution_defaults.migrate_up,
            verify=v0007_application_execution_defaults.verify_structure,
            expected_tables=v0007_application_execution_defaults.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0008_run_conversation_relationships.VERSION,
            name=v0008_run_conversation_relationships.NAME,
            up=v0008_run_conversation_relationships.migrate_up,
            verify=v0008_run_conversation_relationships.verify_structure,
            expected_tables=v0008_run_conversation_relationships.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0009_run_cancellation_request.VERSION,
            name=v0009_run_cancellation_request.NAME,
            up=v0009_run_cancellation_request.migrate_up,
            verify=v0009_run_cancellation_request.verify_structure,
            expected_tables=v0009_run_cancellation_request.EXPECTED_TABLES,
        )
    )
    return registry
