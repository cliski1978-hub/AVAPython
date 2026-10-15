"""SQLite adapter for Project metadata."""

import sqlite3
from collections.abc import Collection

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.repositories.project_file_repository import _record
from ava.infrastructure.persistence.serialization import row_to_project_record, to_utc_iso
from ava.repositories.project import ProjectRecord
from ava.repositories.project_file import ProjectFileRecord
from ava.repositories.project_file_repository import ProjectFileRepository
from ava.repositories.project_repository import ProjectRepository


class RelationalProjectRepository(ProjectRepository):
    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, project: ProjectRecord) -> ProjectRecord:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO projects "
                    "(id, name, description, instructions, is_archived, created_at, updated_at, "
                    "default_runtime_key, default_model_id, owner_principal_ref, owner_tenant_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        project.id,
                        project.name,
                        project.description,
                        project.instructions,
                        int(project.is_archived),
                        to_utc_iso(project.created_at),
                        to_utc_iso(project.updated_at),
                        project.execution_defaults.runtime_key,
                        project.execution_defaults.model_id,
                        project.owner_principal_ref,
                        project.owner_tenant_ref,
                    ),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Project", key=project.id) from exc
        return project

    def get(self, project_id: str) -> ProjectRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, name, description, instructions, is_archived, created_at, updated_at, "
                "default_runtime_key, default_model_id, owner_principal_ref, owner_tenant_ref "
                "FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return row_to_project_record(row) if row is not None else None

    def list(self) -> list[ProjectRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, description, instructions, is_archived, created_at, updated_at, "
                "default_runtime_key, default_model_id, owner_principal_ref, owner_tenant_ref FROM projects"
            ).fetchall()
        return sorted(
            (row_to_project_record(row) for row in rows),
            key=lambda item: (item.is_archived, item.name.casefold(), item.created_at, item.id),
        )

    def update(self, project: ProjectRecord) -> ProjectRecord | None:
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    "UPDATE projects SET name = ?, description = ?, instructions = ?, is_archived = ?, "
                    "created_at = ?, updated_at = ?, default_runtime_key = ?, default_model_id = ?, "
                    "owner_principal_ref = ?, owner_tenant_ref = ? WHERE id = ?",
                    (
                        project.name,
                        project.description,
                        project.instructions,
                        int(project.is_archived),
                        to_utc_iso(project.created_at),
                        to_utc_iso(project.updated_at),
                        project.execution_defaults.runtime_key,
                        project.execution_defaults.model_id,
                        project.owner_principal_ref,
                        project.owner_tenant_ref,
                        project.id,
                    ),
                )
                if cursor.rowcount == 0:
                    return None
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Project", key=project.id) from exc
        return project

    def delete(self, project_id: str) -> bool:
        deleted, _ = self._delete_project(project_id, collect_files=False)
        return deleted

    def delete_with_project_files(
        self, project_id: str, files: ProjectFileRepository
    ) -> tuple[bool, Collection[ProjectFileRecord]]:
        del files  # The shared SQLite transaction reads the authoritative table directly.
        return self._delete_project(project_id, collect_files=True)

    def _delete_project(self, project_id: str, *, collect_files: bool) -> tuple[bool, Collection[ProjectFileRecord]]:
        try:
            with self._database.transaction() as connection:
                row = connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
                if row is None:
                    return False, []
                if collect_files:
                    file_rows = connection.execute(
                        "SELECT id, project_id, file_name, content_type, size_bytes, content_ref, "
                        "created_at, updated_at "
                        "FROM project_files WHERE project_id = ?",
                        (project_id,),
                    ).fetchall()
                else:
                    file_rows = []
                connection.execute(
                    "DELETE FROM core_prompt_assignments WHERE scope_type = 'project' AND scope_id = ?", (project_id,)
                )
                connection.execute("UPDATE conversations SET project_id = NULL WHERE project_id = ?", (project_id,))
                cursor = connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Project", key=project_id) from exc
        records = [_record(file_row) for file_row in file_rows]
        records.sort(key=lambda item: (item.file_name.casefold(), item.created_at, item.id))
        return cursor.rowcount > 0, records
