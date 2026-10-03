from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings


def _client(path: Path) -> TestClient:
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(path),
    )
    return TestClient(create_app(settings=settings))


@pytest.mark.parametrize("organization", ["normal", "archived", "pinned", "folder"])
def test_delete_returns_204_and_removes_conversation(organization: str, tmp_path: Path) -> None:
    with _client(tmp_path / f"{organization}.sqlite3") as client:
        response = client.post("/conversations", json={"title": organization})
        conversation = response.json()
        conversation_id = conversation["conversation_id"]
        path = f"/conversations/{conversation_id}"

        if organization == "archived":
            assert client.patch(f"{path}/archive", json={"is_archived": True}).status_code == 200
        elif organization == "pinned":
            assert client.patch(f"{path}/pin", json={"is_pinned": True}).status_code == 200
        elif organization == "folder":
            database = client.app.state.persistence.database
            assert database is not None
            with database.transaction() as connection:
                connection.execute(
                    "UPDATE conversations SET folder_id = 'folder-123' WHERE conversation_id = ?",
                    (conversation_id,),
                )

        deleted = client.delete(path)
        assert deleted.status_code == 204
        assert deleted.content == b""
        assert client.get(path).status_code == 404


def test_delete_unknown_conversation_uses_not_found_contract(tmp_path: Path) -> None:
    with _client(tmp_path / "unknown.sqlite3") as client:
        response = client.delete("/conversations/missing")

    assert response.status_code == 404
    assert response.json()["error_code"] == "conversation_not_found"
    assert response.json()["category"] == "not_found"


def test_second_delete_uses_not_found_contract(tmp_path: Path) -> None:
    with _client(tmp_path / "second-delete.sqlite3") as client:
        conversation_id = client.post("/conversations", json={"title": "Once"}).json()["conversation_id"]
        path = f"/conversations/{conversation_id}"
        assert client.delete(path).status_code == 204
        second = client.delete(path)

    assert second.status_code == 404
    assert second.json()["error_code"] == "conversation_not_found"


def test_active_run_rejects_delete_without_partial_mutation(tmp_path: Path) -> None:
    with _client(tmp_path / "active.sqlite3") as client:
        conversation_id = client.post("/conversations", json={"title": "Active"}).json()["conversation_id"]
        runs = client.app.state.persistence.run_repository
        active_run = runs.create("active-delete-run", conversation_id=conversation_id)

        response = client.delete(f"/conversations/{conversation_id}")

        assert response.status_code == 409
        body = response.json()
        assert body["error_code"] == "conversation_run_active"
        assert body["category"] == "validation"
        assert client.get(f"/conversations/{conversation_id}").status_code == 200
        assert runs.get(active_run.run_id) == active_run
