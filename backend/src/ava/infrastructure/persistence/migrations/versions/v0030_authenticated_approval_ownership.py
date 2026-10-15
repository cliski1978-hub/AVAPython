"""Migration 0030 — immutable approval audit and conversation ownership."""

import sqlite3

from ava.infrastructure.persistence.migrations.migration import SchemaValidationError
from ava.infrastructure.persistence.migrations.validation import has_named_index, table_columns, table_exists

VERSION = 30
NAME = "authenticated approval audit and conversation ownership"


def migrate_up(connection: sqlite3.Connection) -> None:
    """Add nullable owner facts without assigning legacy conversations."""
    connection.execute("ALTER TABLE conversations ADD COLUMN owner_principal_ref TEXT")
    connection.execute("ALTER TABLE conversations ADD COLUMN owner_tenant_ref TEXT")
    connection.execute("ALTER TABLE conversation_folders ADD COLUMN owner_principal_ref TEXT")
    connection.execute("ALTER TABLE conversation_folders ADD COLUMN owner_tenant_ref TEXT")
    connection.execute("ALTER TABLE projects ADD COLUMN owner_principal_ref TEXT")
    connection.execute("ALTER TABLE projects ADD COLUMN owner_tenant_ref TEXT")
    connection.execute(
        "CREATE INDEX ix_conversations_owner_activity "
        "ON conversations(owner_principal_ref, owner_tenant_ref, is_archived, updated_at, conversation_id)"
    )
    connection.execute(
        """CREATE TABLE approval_audit_events (
            event_id TEXT PRIMARY KEY CHECK(length(event_id)=32),
            approval_id TEXT NOT NULL REFERENCES approval_records(approval_id) ON DELETE RESTRICT,
            sequence INTEGER NOT NULL CHECK(sequence >= 1),
            event_type TEXT NOT NULL CHECK(event_type IN (
                'requested','approved','denied','expired','cancelled','invalidated'
            )),
            status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','expired','cancelled','invalidated')),
            actor_principal_ref TEXT,
            authority_revision_ref TEXT,
            occurred_at TEXT NOT NULL,
            safe_reason TEXT,
            UNIQUE(approval_id, sequence)
        )"""
    )
    connection.execute(
        "CREATE INDEX ix_approval_audit_events_approval "
        "ON approval_audit_events(approval_id, sequence)"
    )
    connection.execute(
        "CREATE TRIGGER trg_approval_audit_events_immutable_update "
        "BEFORE UPDATE ON approval_audit_events BEGIN "
        "SELECT RAISE(ABORT, 'approval audit events are immutable'); END"
    )
    connection.execute(
        "CREATE TRIGGER trg_approval_audit_events_immutable_delete "
        "BEFORE DELETE ON approval_audit_events BEGIN "
        "SELECT RAISE(ABORT, 'approval audit events are immutable'); END"
    )


def verify_structure(connection: sqlite3.Connection) -> None:
    if not {"owner_principal_ref", "owner_tenant_ref"}.issubset(table_columns(connection, "conversations")):
        raise SchemaValidationError("Conversation ownership schema is incomplete")
    if not {"owner_principal_ref", "owner_tenant_ref"}.issubset(table_columns(connection, "conversation_folders")):
        raise SchemaValidationError("Conversation folder ownership schema is incomplete")
    if not {"owner_principal_ref", "owner_tenant_ref"}.issubset(table_columns(connection, "projects")):
        raise SchemaValidationError("Project ownership schema is incomplete")
    if not has_named_index(connection, "conversations", "ix_conversations_owner_activity"):
        raise SchemaValidationError("Conversation owner index is missing")
    if not table_exists(connection, "approval_audit_events"):
        raise SchemaValidationError("Approval audit table is missing")
    required = {
        "event_id", "approval_id", "sequence", "event_type", "status", "actor_principal_ref",
        "authority_revision_ref", "occurred_at", "safe_reason",
    }
    if not required.issubset(table_columns(connection, "approval_audit_events")):
        raise SchemaValidationError("Approval audit schema is incomplete")
    if not has_named_index(connection, "approval_audit_events", "ix_approval_audit_events_approval"):
        raise SchemaValidationError("Approval audit ordering index is missing")
    trigger_names = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='approval_audit_events'"
        )
    }
    if not {
        "trg_approval_audit_events_immutable_update",
        "trg_approval_audit_events_immutable_delete",
    }.issubset(trigger_names):
        raise SchemaValidationError("Approval audit history must be append-only")
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='approval_audit_events'"
    ).fetchone()
    ddl = "".join(str(row["sql"]).lower().split()) if row else ""
    if "referencesapproval_records(approval_id)ondeleterestrict" not in ddl:
        raise SchemaValidationError("Approval audit records must preserve approval history")
