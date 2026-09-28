"""SQLite-backed provider-connection repository adapter."""

import sqlite3

from ava.infrastructure.persistence.database import SqliteDatabase, translate_database_error
from ava.models.provider_connections import ProviderConnection
from ava.repositories.provider_connection_repository import ProviderConnectionRepository

_COLUMNS = "provider_connection_id, provider_id, display_name, endpoint, enabled, credential_reference"


class RelationalProviderConnectionRepository(ProviderConnectionRepository):
    """SQLite implementation of AVA's provider-connection persistence port."""

    def __init__(self, *, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, connection: ProviderConnection) -> ProviderConnection:
        try:
            with self._database.transaction() as database_connection:
                database_connection.execute(
                    "INSERT INTO provider_connections "
                    "(provider_connection_id, provider_id, display_name, endpoint, enabled, credential_reference) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (connection.provider_connection_id, connection.provider_id, connection.display_name,
                     connection.endpoint, connection.enabled, connection.credential_reference),
                )
        except sqlite3.Error as exc:
            raise translate_database_error(
                exc, entity="Provider connection", key=connection.provider_connection_id
            ) from exc
        return connection

    def get(self, provider_connection_id: str) -> ProviderConnection | None:
        with self._database.connect() as database_connection:
            row = database_connection.execute(
                f"SELECT {_COLUMNS} FROM provider_connections WHERE provider_connection_id = ?",
                (provider_connection_id,),
            ).fetchone()
        return _row_to_provider_connection(row) if row is not None else None

    def list(self) -> list[ProviderConnection]:
        with self._database.connect() as database_connection:
            rows = database_connection.execute(
                f"SELECT {_COLUMNS} FROM provider_connections ORDER BY id ASC"
            ).fetchall()
        return [_row_to_provider_connection(row) for row in rows]

    def update(self, connection: ProviderConnection) -> ProviderConnection | None:
        with self._database.transaction() as database_connection:
            existing = database_connection.execute(
                "SELECT provider_id FROM provider_connections WHERE provider_connection_id = ?",
                (connection.provider_connection_id,),
            ).fetchone()
            if existing is None:
                return None
            if existing["provider_id"] != connection.provider_id:
                raise ValueError("Provider connection provider_id cannot change")
            database_connection.execute(
                "UPDATE provider_connections SET display_name = ?, endpoint = ?, enabled = ?, "
                "credential_reference = ? WHERE provider_connection_id = ?",
                (connection.display_name, connection.endpoint, connection.enabled,
                 connection.credential_reference, connection.provider_connection_id),
            )
        return connection


def _row_to_provider_connection(row: sqlite3.Row) -> ProviderConnection:
    return ProviderConnection(
        provider_connection_id=row["provider_connection_id"],
        provider_id=row["provider_id"],
        display_name=row["display_name"],
        endpoint=row["endpoint"],
        enabled=bool(row["enabled"]),
        credential_reference=row["credential_reference"],
    )
