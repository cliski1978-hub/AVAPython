"""AVA's application migration versions (Step 4.7).

``default_registry()`` is the authoritative, application-owned migration
sequence. Versions 0001 through 0003 establish the Phase 4 schema; version
0004 adds Phase 5.3 provider connections, 0005 Phase 5.5 model configurations,
0006 Phase 5.7 runtime configurations, 0007 Phase 5.8 application execution
defaults, 0008 the Phase 5.19 durable run relationships, 0009 the Phase 5.24
durable cancellation request, 0010 Phase 5.43 conversation organization
metadata, 0011 conversation folders, 0012 Project persistence, 0013 the
conversation Project relationship, and 0014 Project lookup indexing.
Phase 5.67 adds 0015 CORE prompt definitions; Phase 5.68 adds 0016 scoped assignments.
Phase 5.76 adds 0018 Project file metadata (0017 is Project execution defaults).
The registry is built from explicit versions, never from directory/import order.
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
    v0010_conversation_organization_metadata,
    v0011_conversation_folders,
    v0012_projects,
    v0013_conversation_project_relationship,
    v0014_conversation_project_index,
    v0015_core_prompts,
    v0016_core_prompt_assignments,
    v0017_project_execution_defaults,
    v0018_project_files,
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
    registry.register(
        Migration(
            version=v0010_conversation_organization_metadata.VERSION,
            name=v0010_conversation_organization_metadata.NAME,
            up=v0010_conversation_organization_metadata.migrate_up,
            verify=v0010_conversation_organization_metadata.verify_structure,
            expected_tables=v0010_conversation_organization_metadata.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0011_conversation_folders.VERSION,
            name=v0011_conversation_folders.NAME,
            up=v0011_conversation_folders.migrate_up,
            verify=v0011_conversation_folders.verify_structure,
            expected_tables=v0011_conversation_folders.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0012_projects.VERSION,
            name=v0012_projects.NAME,
            up=v0012_projects.migrate_up,
            verify=v0012_projects.verify_structure,
            expected_tables=v0012_projects.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0013_conversation_project_relationship.VERSION,
            name=v0013_conversation_project_relationship.NAME,
            up=v0013_conversation_project_relationship.migrate_up,
            verify=v0013_conversation_project_relationship.verify_structure,
            expected_tables=v0013_conversation_project_relationship.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0014_conversation_project_index.VERSION,
            name=v0014_conversation_project_index.NAME,
            up=v0014_conversation_project_index.migrate_up,
            verify=v0014_conversation_project_index.verify_structure,
            expected_tables=v0014_conversation_project_index.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0015_core_prompts.VERSION,
            name=v0015_core_prompts.NAME,
            up=v0015_core_prompts.migrate_up,
            verify=v0015_core_prompts.verify_structure,
            expected_tables=v0015_core_prompts.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0016_core_prompt_assignments.VERSION,
            name=v0016_core_prompt_assignments.NAME,
            up=v0016_core_prompt_assignments.migrate_up,
            verify=v0016_core_prompt_assignments.verify_structure,
            expected_tables=v0016_core_prompt_assignments.EXPECTED_TABLES,
        )
    )
    registry.register(
        Migration(
            version=v0017_project_execution_defaults.VERSION,
            name=v0017_project_execution_defaults.NAME,
            up=v0017_project_execution_defaults.migrate_up,
            verify=v0017_project_execution_defaults.verify_structure,
        )
    )
    registry.register(
        Migration(
            version=v0018_project_files.VERSION,
            name=v0018_project_files.NAME,
            up=v0018_project_files.migrate_up,
            verify=v0018_project_files.verify_structure,
        )
    )
    return registry
