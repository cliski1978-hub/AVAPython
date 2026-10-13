import json
import sqlite3

from pydantic import ValidationError

from ava.contracts.workspace_access import WorkspaceAccessConfiguration
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.repositories.workspace_access_repository import (
    WorkspaceAccessAlreadyExistsError,
    WorkspaceAccessConflictError,
    WorkspaceAccessRepository,
)


class RelationalWorkspaceAccessRepository(WorkspaceAccessRepository):
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def list(self) -> list[WorkspaceAccessConfiguration]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM workspace_access_configurations ORDER BY workspace_id").fetchall()
        return [self._decode(row) for row in rows]

    def get(self, workspace_id: str) -> WorkspaceAccessConfiguration | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspace_access_configurations WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
        return self._decode(row) if row else None

    @staticmethod
    def _decode(row: sqlite3.Row) -> WorkspaceAccessConfiguration:
        try:
            return WorkspaceAccessConfiguration.model_validate(
                {
                    "workspace_id": row["workspace_id"],
                    "name": row["name"],
                    "kind": row["kind"],
                    "root_path": row["root_path"],
                    "allowed_capabilities": json.loads(row["allowed_capabilities"]),
                    "status": row["status"],
                    "revision": row["revision"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "contract_version": row["contract_version"],
                }
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
            raise ValueError("workspace configuration is invalid") from exc

    @staticmethod
    def _values(configuration: WorkspaceAccessConfiguration) -> tuple[object, ...]:
        return (
            configuration.workspace_id,
            configuration.name,
            configuration.kind.value,
            configuration.root_path,
            json.dumps([item.value for item in configuration.allowed_capabilities]),
            configuration.status.value,
            configuration.revision,
            configuration.created_at.isoformat(),
            configuration.updated_at.isoformat(),
            configuration.contract_version,
        )

    def create(self, configuration: WorkspaceAccessConfiguration) -> None:
        if configuration.revision != 1:
            raise ValueError("new Workspace revision must be 1")
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO workspace_access_configurations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._values(configuration),
                )
        except sqlite3.IntegrityError as exc:
            if "workspace_access_configurations.workspace_id" in str(exc):
                raise WorkspaceAccessAlreadyExistsError(configuration.workspace_id) from exc
            raise

    def compare_and_set(self, expected_revision: int, configuration: WorkspaceAccessConfiguration) -> None:
        if configuration.revision != expected_revision + 1:
            raise ValueError("Workspace revision must advance by one")
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT revision, status FROM workspace_access_configurations WHERE workspace_id = ?",
                (configuration.workspace_id,),
            ).fetchone()
            if row is None or row["revision"] != expected_revision:
                raise WorkspaceAccessConflictError(configuration.workspace_id)
            if row["status"] == "revoked" and configuration.status.value != "revoked":
                raise ValueError("revoked Workspace identity cannot be reactivated")
            connection.execute(
                "UPDATE workspace_access_configurations SET name=?, kind=?, root_path=?, allowed_capabilities=?, "
                "status=?, revision=?, updated_at=?, contract_version=? WHERE workspace_id=? AND revision=?",
                (
                    configuration.name,
                    configuration.kind.value,
                    configuration.root_path,
                    json.dumps([item.value for item in configuration.allowed_capabilities]),
                    configuration.status.value,
                    configuration.revision,
                    configuration.updated_at.isoformat(),
                    configuration.contract_version,
                    configuration.workspace_id,
                    expected_revision,
                ),
            )
