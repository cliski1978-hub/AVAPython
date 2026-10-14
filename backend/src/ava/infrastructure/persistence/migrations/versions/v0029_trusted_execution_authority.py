"""Migration 0029 — durable Run ownership and Workspace access grants."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import has_named_index, table_columns, table_exists

VERSION = 29
NAME = "trusted Run ownership and Workspace grants"
RUN_COLUMNS = (
    "owner_principal_ref",
    "owner_tenant_ref",
    "owner_auth_context_ref",
    "owner_auth_valid_until",
    "execution_workspace_id",
)


def migrate_up(connection: sqlite3.Connection) -> None:
    """Add nullable legacy ownership fields and a separately scoped grant table."""
    connection.execute("ALTER TABLE runs ADD COLUMN owner_principal_ref TEXT")
    connection.execute("ALTER TABLE runs ADD COLUMN owner_tenant_ref TEXT")
    connection.execute("ALTER TABLE runs ADD COLUMN owner_auth_context_ref TEXT")
    connection.execute("ALTER TABLE runs ADD COLUMN owner_auth_valid_until TEXT")
    connection.execute("ALTER TABLE runs ADD COLUMN execution_workspace_id TEXT")
    connection.execute(
        "CREATE INDEX ix_runs_owner_conversation_created "
        "ON runs(owner_principal_ref, owner_tenant_ref, conversation_id, created_at, run_id)"
    )
    connection.execute(
        """CREATE TABLE workspace_access_grants (
            grant_id TEXT PRIMARY KEY CHECK(length(grant_id)=32),
            workspace_id TEXT NOT NULL REFERENCES workspace_access_configurations(workspace_id) ON DELETE RESTRICT,
            principal_ref TEXT NOT NULL CHECK(length(principal_ref)=64),
            tenant_ref TEXT,
            run_id TEXT REFERENCES runs(run_id) ON DELETE RESTRICT,
            capabilities TEXT NOT NULL,
            workspace_configuration_revision INTEGER NOT NULL CHECK(workspace_configuration_revision >= 1),
            status TEXT NOT NULL CHECK(status IN ('active','revoked')),
            revision INTEGER NOT NULL CHECK(revision >= 1),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            contract_version TEXT NOT NULL CHECK(contract_version='v1')
        )"""
    )
    connection.execute(
        "CREATE UNIQUE INDEX ux_workspace_access_grants_active_scope "
        "ON workspace_access_grants(workspace_id, principal_ref, ifnull(tenant_ref,'')) WHERE status='active'"
    )
    connection.execute(
        "CREATE INDEX ix_workspace_access_grants_principal "
        "ON workspace_access_grants(principal_ref, tenant_ref, status)"
    )
    connection.execute(
        "CREATE INDEX ix_workspace_access_grants_workspace "
        "ON workspace_access_grants(workspace_id, status, created_at, grant_id)"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if not set(RUN_COLUMNS).issubset(table_columns(connection, "runs")):
        raise SchemaValidationError("Run ownership schema is incomplete")
    if not table_exists(connection, "workspace_access_grants"):
        raise SchemaValidationError("Workspace access grant table is missing")
    required = {
        "grant_id", "workspace_id", "principal_ref", "tenant_ref", "run_id", "capabilities",
        "workspace_configuration_revision", "status", "revision", "created_at", "updated_at", "contract_version",
    }
    if not required.issubset(table_columns(connection, "workspace_access_grants")):
        raise SchemaValidationError("Workspace access grant schema is incomplete")
    for name in (
        "ix_runs_owner_conversation_created",
        "ux_workspace_access_grants_active_scope",
        "ix_workspace_access_grants_principal",
        "ix_workspace_access_grants_workspace",
    ):
        if not has_named_index(connection, "runs" if name.startswith("ix_runs") else "workspace_access_grants", name):
            raise SchemaValidationError(f"Required security index is missing: {name}")
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='workspace_access_grants'"
    ).fetchone()
    ddl = "".join(str(row["sql"]).lower().split()) if row else ""
    if "referencesworkspace_access_configurations(workspace_id)ondeleterestrict" not in ddl:
        raise SchemaValidationError("Workspace grant does not bind to Workspace configuration")
    if "statusin('active','revoked')" not in ddl:
        raise SchemaValidationError("Workspace grant status constraint is missing")
