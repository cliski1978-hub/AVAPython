"""SQLite adapter for reusable CORE prompt definitions."""

import sqlite3
from datetime import datetime

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.infrastructure.persistence.serialization import row_to_core_prompt_record, to_utc_iso
from ava.repositories.core_prompt import CorePromptRecord
from ava.repositories.core_prompt_repository import CorePromptRepository


class RelationalCorePromptRepository(CorePromptRepository):
    """Durable CORE prompt adapter over the shared AVA SQLite database."""

    _SELECT = (
        "SELECT id, name, description, prompt_text, category, is_enabled, created_at, updated_at FROM core_prompts"
    )

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, prompt: CorePromptRecord) -> CorePromptRecord:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO core_prompts "
                    "(id, name, description, prompt_text, category, is_enabled, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        prompt.id,
                        prompt.name,
                        prompt.description,
                        prompt.prompt_text,
                        prompt.category.value,
                        int(prompt.is_enabled),
                        to_utc_iso(prompt.created_at),
                        to_utc_iso(prompt.updated_at),
                    ),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="CORE prompt", key=prompt.id) from exc
        return prompt

    def get(self, core_prompt_id: str) -> CorePromptRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(f"{self._SELECT} WHERE id = ?", (core_prompt_id,)).fetchone()
        return row_to_core_prompt_record(row) if row is not None else None

    def list(self) -> list[CorePromptRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(self._SELECT).fetchall()
        prompts = [row_to_core_prompt_record(row) for row in rows]
        return sorted(
            prompts,
            key=lambda item: (item.category.value, item.name.casefold(), item.created_at, item.id),
        )

    def update(self, prompt: CorePromptRecord) -> CorePromptRecord | None:
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    "UPDATE core_prompts SET name = ?, description = ?, prompt_text = ?, category = ?, "
                    "updated_at = ? WHERE id = ?",
                    (
                        prompt.name,
                        prompt.description,
                        prompt.prompt_text,
                        prompt.category.value,
                        to_utc_iso(prompt.updated_at),
                        prompt.id,
                    ),
                )
                if cursor.rowcount == 0:
                    return None
                row = connection.execute(f"{self._SELECT} WHERE id = ?", (prompt.id,)).fetchone()
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="CORE prompt", key=prompt.id) from exc
        return row_to_core_prompt_record(row) if row is not None else None

    def set_enabled(self, core_prompt_id: str, is_enabled: bool, updated_at: datetime) -> CorePromptRecord | None:
        with self._database.transaction() as connection:
            row = connection.execute(f"{self._SELECT} WHERE id = ?", (core_prompt_id,)).fetchone()
            if row is None:
                return None
            current = row_to_core_prompt_record(row)
            if current.is_enabled == is_enabled:
                return current
            connection.execute(
                "UPDATE core_prompts SET is_enabled = ?, updated_at = ? WHERE id = ?",
                (int(is_enabled), to_utc_iso(updated_at), core_prompt_id),
            )
            updated_row = connection.execute(f"{self._SELECT} WHERE id = ?", (core_prompt_id,)).fetchone()
        return row_to_core_prompt_record(updated_row) if updated_row is not None else None

    def delete(self, core_prompt_id: str) -> bool:
        try:
            with self._database.transaction() as connection:
                connection.execute("DELETE FROM core_prompt_assignments WHERE core_prompt_id = ?", (core_prompt_id,))
                cursor = connection.execute("DELETE FROM core_prompts WHERE id = ?", (core_prompt_id,))
        except sqlite3.Error as exc:
            raise translate_database_error(exc, entity="CORE prompt", key=core_prompt_id) from exc
        return cursor.rowcount > 0
