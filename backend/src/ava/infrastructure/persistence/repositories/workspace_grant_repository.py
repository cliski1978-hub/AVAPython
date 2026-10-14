"""SQLite Workspace-grant persistence adapter."""

import json
import sqlite3

from pydantic import ValidationError

from ava.contracts.workspace_grants import WorkspaceGrant
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.serialization import parse_utc
from ava.repositories.workspace_grant_repository import WorkspaceGrantConflictError, WorkspaceGrantRepository


class RelationalWorkspaceGrantRepository(WorkspaceGrantRepository):
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def list_for_workspace(self, workspace_id: str) -> list[WorkspaceGrant]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workspace_access_grants WHERE workspace_id=? ORDER BY created_at, grant_id",
                (workspace_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, grant_id: str) -> WorkspaceGrant | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM workspace_access_grants WHERE grant_id=?", (grant_id,)).fetchone()
        return self._decode(row) if row is not None else None

    def get_active_for_principal(
        self, workspace_id: str, principal_ref: str, tenant_ref: str | None
    ) -> WorkspaceGrant | None:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workspace_access_grants WHERE workspace_id=? AND principal_ref=? "
                "AND tenant_ref IS ? AND status='active' ORDER BY created_at DESC, grant_id DESC LIMIT 2",
                (workspace_id, principal_ref, tenant_ref),
            ).fetchall()
        if len(rows) > 1:
            raise WorkspaceGrantConflictError("multiple active Workspace grants conflict")
        return self._decode(rows[0]) if rows else None

    def create(self, grant: WorkspaceGrant) -> None:
        if grant.revision != 1 or grant.status.value != "active":
            raise ValueError("new Workspace grants must be active at revision one")
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO workspace_access_grants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._values(grant),
                )
        except sqlite3.IntegrityError as exc:
            raise WorkspaceGrantConflictError("Workspace grant identity or active scope already exists") from exc

    def compare_and_set(self, expected_revision: int, grant: WorkspaceGrant) -> None:
        if grant.revision != expected_revision + 1:
            raise ValueError("Workspace grant revision must advance by one")
        values = self._values(grant)
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT revision, status FROM workspace_access_grants WHERE grant_id=?", (grant.grant_id,)
            ).fetchone()
            if row is None or row["revision"] != expected_revision:
                raise WorkspaceGrantConflictError("Workspace grant revision conflict")
            if row["status"] == "revoked":
                raise WorkspaceGrantConflictError("revoked Workspace grants are terminal")
            try:
                cursor = connection.execute(
                    "UPDATE workspace_access_grants SET workspace_id=?, principal_ref=?, tenant_ref=?, run_id=?, "
                    "capabilities=?, workspace_configuration_revision=?, status=?, revision=?, created_at=?, "
                    "updated_at=?, contract_version=? WHERE grant_id=? AND revision=?",
                    (*values[1:], values[0], expected_revision),
                )
            except sqlite3.IntegrityError as exc:
                raise WorkspaceGrantConflictError("Workspace grant update conflicts with an active scope") from exc
            if cursor.rowcount != 1:
                raise WorkspaceGrantConflictError("Workspace grant revision conflict")

    @staticmethod
    def _values(grant: WorkspaceGrant) -> tuple[object, ...]:
        return (
            grant.grant_id,
            grant.workspace_id,
            grant.principal_ref,
            grant.tenant_ref,
            grant.run_id,
            json.dumps([item.value for item in grant.capabilities], separators=(",", ":")),
            grant.workspace_configuration_revision,
            grant.status.value,
            grant.revision,
            grant.created_at.isoformat(),
            grant.updated_at.isoformat(),
            grant.contract_version,
        )

    @staticmethod
    def _decode(row: sqlite3.Row) -> WorkspaceGrant:
        try:
            return WorkspaceGrant.model_validate(
                {
                    "grant_id": row["grant_id"],
                    "workspace_id": row["workspace_id"],
                    "principal_ref": row["principal_ref"],
                    "tenant_ref": row["tenant_ref"],
                    "run_id": row["run_id"],
                    "capabilities": json.loads(row["capabilities"]),
                    "workspace_configuration_revision": row["workspace_configuration_revision"],
                    "status": row["status"],
                    "revision": row["revision"],
                    "created_at": parse_utc(row["created_at"]),
                    "updated_at": parse_utc(row["updated_at"]),
                    "contract_version": row["contract_version"],
                }
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
            raise ValueError("Workspace grant record is invalid") from exc
