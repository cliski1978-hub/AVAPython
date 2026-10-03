"""SQLite adapter for Project-file metadata."""

import sqlite3

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import parse_utc, to_utc_iso
from ava.repositories.project_file import ProjectFileRecord
from ava.repositories.project_file_repository import ProjectFileRepository


def _record(row: sqlite3.Row) -> ProjectFileRecord:
    return ProjectFileRecord(
        id=row["id"],
        project_id=row["project_id"],
        file_name=row["file_name"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        content_ref=row["content_ref"],
        created_at=parse_utc(row["created_at"]),
        updated_at=parse_utc(row["updated_at"]),
    )


_SELECT = "id, project_id, file_name, content_type, size_bytes, content_ref, created_at, updated_at"


class RelationalProjectFileRepository(ProjectFileRepository):
    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, record: ProjectFileRecord) -> ProjectFileRecord:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    f"INSERT INTO project_files ({_SELECT}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.id,
                        record.project_id,
                        record.file_name,
                        record.content_type,
                        record.size_bytes,
                        record.content_ref,
                        to_utc_iso(record.created_at),
                        to_utc_iso(record.updated_at),
                    ),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Project file", key=record.id) from exc
        return record

    def get(self, file_id: str) -> ProjectFileRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(f"SELECT {_SELECT} FROM project_files WHERE id = ?", (file_id,)).fetchone()
        return _record(row) if row is not None else None

    def list_by_project(self, project_id: str) -> list[ProjectFileRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"SELECT {_SELECT} FROM project_files WHERE project_id = ?", (project_id,)
            ).fetchall()
        return sorted(
            (_record(row) for row in rows), key=lambda item: (item.file_name.casefold(), item.created_at, item.id)
        )

    def delete(self, file_id: str) -> ProjectFileRecord | None:
        try:
            with self._database.transaction() as connection:
                row = connection.execute(f"SELECT {_SELECT} FROM project_files WHERE id = ?", (file_id,)).fetchone()
                if row is None:
                    return None
                connection.execute("DELETE FROM project_files WHERE id = ?", (file_id,))
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Project file", key=file_id) from exc
        return _record(row)

    def delete_by_project(self, project_id: str) -> list[ProjectFileRecord]:
        try:
            with self._database.transaction() as connection:
                rows = connection.execute(
                    f"SELECT {_SELECT} FROM project_files WHERE project_id = ?", (project_id,)
                ).fetchall()
                connection.execute("DELETE FROM project_files WHERE project_id = ?", (project_id,))
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="Project files", key=project_id) from exc
        return sorted(
            (_record(row) for row in rows), key=lambda item: (item.file_name.casefold(), item.created_at, item.id)
        )
