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
Migration 0019 records whether a Conversation title was explicitly set by a user.
Migration 0024 adds normalized-tool feature gates; migration 0025 adds
administrator-configured execution Workspace access; migration 0026 adds
durable normalized-tool approval records; migration 0027 adds the Run-scoped
execution mode with a safe ``chat`` default for existing records.
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
    v0019_conversation_title_ownership,
    v0020_run_inspection,
    v0021_model_context_window,
    v0022_conversation_context_summaries,
    v0023_project_file_name_uniqueness,
    v0024_tool_features,
    v0025_workspace_access,
    v0026_approvals,
    v0027_run_execution_mode,
    v0028_tool_invocation_reservations,
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
    registry.register(
        Migration(
            version=v0019_conversation_title_ownership.VERSION,
            name=v0019_conversation_title_ownership.NAME,
            up=v0019_conversation_title_ownership.migrate_up,
            verify=v0019_conversation_title_ownership.verify_structure,
        )
    )
    registry.register(
        Migration(
            version=v0020_run_inspection.VERSION,
            name=v0020_run_inspection.NAME,
            up=v0020_run_inspection.migrate_up,
            verify=v0020_run_inspection.verify_structure,
        )
    )
    registry.register(
        Migration(
            version=v0021_model_context_window.VERSION,
            name=v0021_model_context_window.NAME,
            up=v0021_model_context_window.migrate_up,
            verify=v0021_model_context_window.verify_structure,
        )
    )
    registry.register(
        Migration(
            version=v0022_conversation_context_summaries.VERSION,
            name=v0022_conversation_context_summaries.NAME,
            up=v0022_conversation_context_summaries.migrate_up,
            verify=v0022_conversation_context_summaries.verify_structure,
        )
    )
    registry.register(
        Migration(
            version=v0023_project_file_name_uniqueness.VERSION,
            name=v0023_project_file_name_uniqueness.NAME,
            up=v0023_project_file_name_uniqueness.migrate_up,
            verify=v0023_project_file_name_uniqueness.verify_structure,
        )
    )
    registry.register(
        Migration(
            version=v0024_tool_features.VERSION,
            name=v0024_tool_features.NAME,
            up=v0024_tool_features.migrate_up,
            verify=v0024_tool_features.verify_structure,
        )
    )
    registry.register(
        Migration(
            version=v0025_workspace_access.VERSION,
            name=v0025_workspace_access.NAME,
            up=v0025_workspace_access.migrate_up,
            verify=v0025_workspace_access.verify_structure,
            expected_tables=("workspace_access_configurations",),
        )
    )
    registry.register(
        Migration(
            version=v0026_approvals.VERSION,
            name=v0026_approvals.NAME,
            up=v0026_approvals.migrate_up,
            verify=v0026_approvals.verify_structure,
        )
    )
    registry.register(
        Migration(
            version=v0027_run_execution_mode.VERSION,
            name=v0027_run_execution_mode.NAME,
            up=v0027_run_execution_mode.migrate_up,
            verify=v0027_run_execution_mode.verify_structure,
        )
    )
    registry.register(
        Migration(
            version=v0028_tool_invocation_reservations.VERSION,
            name=v0028_tool_invocation_reservations.NAME,
            up=v0028_tool_invocation_reservations.migrate_up,
            verify=v0028_tool_invocation_reservations.verify_structure,
        )
    )
    return registry
