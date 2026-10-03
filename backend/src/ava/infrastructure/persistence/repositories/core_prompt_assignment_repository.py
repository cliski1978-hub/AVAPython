"""SQLite adapter for explicit scoped CORE prompt assignments."""

import sqlite3
from datetime import datetime

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import to_utc_iso
from ava.repositories.core_prompt_assignment import (
    CorePromptAssignmentMode,
    CorePromptAssignmentRecord,
    CorePromptScopeType,
)
from ava.repositories.core_prompt_assignment_repository import CorePromptAssignmentRepository


def _record(row: sqlite3.Row) -> CorePromptAssignmentRecord:
    return CorePromptAssignmentRecord(
        id=row["id"],
        core_prompt_id=row["core_prompt_id"],
        scope_type=CorePromptScopeType(row["scope_type"]),
        scope_id=row["scope_id"],
        mode=CorePromptAssignmentMode(row["mode"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class RelationalCorePromptAssignmentRepository(CorePromptAssignmentRepository):
    """Assignment storage; returned rows order by scope/type, id, time, identity."""

    _SELECT = (
        "SELECT id, core_prompt_id, scope_type, scope_id, mode, created_at, updated_at FROM core_prompt_assignments"
    )

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def get_explicit(
        self, core_prompt_id: str, scope_type: CorePromptScopeType, scope_id: str | None
    ) -> CorePromptAssignmentRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"{self._SELECT} WHERE core_prompt_id = ? AND scope_type = ? AND scope_id IS ?",
                (core_prompt_id, scope_type.value, scope_id),
            ).fetchone()
        return _record(row) if row else None

    def list_for_prompt(self, core_prompt_id: str) -> list[CorePromptAssignmentRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"{self._SELECT} WHERE core_prompt_id = ? ORDER BY scope_type, COALESCE(scope_id, ''), created_at, id",
                (core_prompt_id,),
            ).fetchall()
        return [_record(row) for row in rows]

    def list_for_scope(self, scope_type: CorePromptScopeType, scope_id: str | None) -> list[CorePromptAssignmentRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"{self._SELECT} WHERE scope_type = ? AND scope_id IS ? "
                "ORDER BY scope_type, COALESCE(scope_id, ''), created_at, id",
                (scope_type.value, scope_id),
            ).fetchall()
        return [_record(row) for row in rows]

    def upsert_explicit(self, assignment: CorePromptAssignmentRecord) -> CorePromptAssignmentRecord:
        try:
            with self._database.transaction() as connection:
                old = connection.execute(
                    f"{self._SELECT} WHERE core_prompt_id = ? AND scope_type = ? AND scope_id IS ?",
                    (assignment.core_prompt_id, assignment.scope_type.value, assignment.scope_id),
                ).fetchone()
                if old and old["mode"] == assignment.mode.value:
                    return _record(old)
                if old:
                    connection.execute(
                        "UPDATE core_prompt_assignments SET mode = ?, updated_at = ? WHERE id = ?",
                        (assignment.mode.value, to_utc_iso(assignment.updated_at), old["id"]),
                    )
                else:
                    connection.execute(
                        "INSERT INTO core_prompt_assignments "
                        "(id, core_prompt_id, scope_type, scope_id, mode, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            assignment.id,
                            assignment.core_prompt_id,
                            assignment.scope_type.value,
                            assignment.scope_id,
                            assignment.mode.value,
                            to_utc_iso(assignment.created_at),
                            to_utc_iso(assignment.updated_at),
                        ),
                    )
                row = connection.execute(
                    f"{self._SELECT} WHERE core_prompt_id = ? AND scope_type = ? AND scope_id IS ?",
                    (assignment.core_prompt_id, assignment.scope_type.value, assignment.scope_id),
                ).fetchone()
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="CORE prompt assignment", key=assignment.id) from exc
        return _record(row)

    def delete_explicit(self, core_prompt_id: str, scope_type: CorePromptScopeType, scope_id: str | None) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM core_prompt_assignments WHERE core_prompt_id = ? AND scope_type = ? AND scope_id IS ?",
                (core_prompt_id, scope_type.value, scope_id),
            )
        return cursor.rowcount > 0

    def delete_for_prompt(self, core_prompt_id: str) -> int:
        with self._database.transaction() as connection:
            return connection.execute(
                "DELETE FROM core_prompt_assignments WHERE core_prompt_id = ?", (core_prompt_id,)
            ).rowcount

    def delete_for_scope(self, scope_type: CorePromptScopeType, scope_id: str) -> int:
        with self._database.transaction() as connection:
            return connection.execute(
                "DELETE FROM core_prompt_assignments WHERE scope_type = ? AND scope_id = ?",
                (scope_type.value, scope_id),
            ).rowcount
