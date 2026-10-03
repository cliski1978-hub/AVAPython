"""Phase 5.44: pin-only writes preserve all other state in both backends."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.events import EventType, RunEvent
from ava.infrastructure.composition import create_application_persistence
from ava.services.conversation_service import ConversationService
from ava.services.conversation_store import ConversationStore


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_service_pin_transitions_preserve_metadata_and_execution_records(mode: str, tmp_path: Path) -> None:
    persistence = create_application_persistence(Settings(
        persistence_provider=mode, persistence_database_url=str(tmp_path / "pin.sqlite3")
    ))
    try:
        repository = persistence.conversation_repository
        repository.create("first", title="First")
        original = repository.create("target", title="Original")
        if isinstance(repository, ConversationStore):
            repository._conversations["target"] = replace(original, is_archived=True, folder_id="folder-x")
        else:
            assert persistence.database is not None
            with persistence.database.transaction() as connection:
                connection.execute(
                    "UPDATE conversations SET is_archived = 1, folder_id = 'folder-x' WHERE conversation_id = 'target'"
                )
        baseline = repository.get("target")
        assert baseline is not None
        service = ConversationService(
            conversation_repository=repository, message_repository=persistence.message_repository
        )
        message = service.append_message("target", content="Keep this message")
        run = persistence.run_repository.create(
            "run-1", conversation_id="target", source_user_message_id=message.message_id
        )
        persistence.run_event_repository.append(RunEvent(
            event_id="event-1", run_id=run.run_id, sequence=1, event_type=EventType.RUN_STARTED,
            timestamp=datetime.now(UTC), payload={},
        ))
        messages = service.list_messages("target")
        events = persistence.run_event_repository.get_events(run.run_id)
        for pinned in (False, True, True, False, False, True):
            response = service.set_pinned("target", pinned)
            assert response is not None and response.is_pinned is pinned
            assert repository.get("target") == replace(baseline, is_pinned=pinned)
            assert [r.conversation_id for r in repository.list()] == ["target", "first"]
            assert service.list_messages("target") == messages
            assert persistence.run_repository.get(run.run_id) == run
            assert persistence.run_event_repository.get_events(run.run_id) == events
        renamed = service.update_title("target", "Renamed")
        assert renamed is not None and renamed.is_pinned is True
        baseline = repository.get("target")
        assert baseline is not None and baseline.title == "Renamed"
        assert service.set_pinned("target", False) is not None
        assert repository.get("target") == replace(baseline, is_pinned=False)
        assert repository.set_pinned("missing", True) is None
        assert service.set_pinned("missing", False) is None
        assert len(repository.list()) == 2
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_http_pin_only_unpin_rename_validation_and_order(mode: str, tmp_path: Path) -> None:
    settings = Settings(persistence_provider=mode, persistence_database_url=str(tmp_path / "api.sqlite3"))
    with TestClient(create_app(settings=settings)) as client:
        first = client.post("/conversations", json={"title": "First"}).json()
        original = client.post("/conversations", json={"title": "Original"}).json()
        path = f"/conversations/{original['conversation_id']}"
        for pinned in (False, True, True, False, False, True):
            response = client.patch(f"{path}/pin", json={"is_pinned": pinned})
            assert response.status_code == 200
            assert response.json() == {**original, "is_pinned": pinned}
            assert client.get(path).json() == response.json()
            listing = client.get("/conversations").json()["conversations"]
            assert [item["conversation_id"] for item in listing] == [
                original["conversation_id"], first["conversation_id"]
            ]
            assert listing[0]["is_pinned"] is pinned
        renamed = client.patch(path, json={"title": "Renamed"})
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Renamed"
        assert renamed.json()["is_pinned"] is True
        preserved = client.patch(f"{path}/pin", json={
            "is_pinned": False, "is_archived": True, "folder_id": "ignored", "title": "Ignored",
        })
        assert preserved.json() == {**renamed.json(), "is_pinned": False}
        for body in ({}, {"is_archived": True}, {"folder_id": "x"}):
            assert client.patch(f"{path}/pin", json=body).status_code == 422
        assert client.patch(path, json={}).status_code == 422
        missing = client.patch("/conversations/missing/pin", json={"is_pinned": True})
        assert missing.status_code == 404
        assert missing.json()["error_code"] == "conversation_not_found"


@pytest.mark.parametrize("value", [None, "true", "false", 0, 1, [], {}])
def test_http_rejects_malformed_pin_values(value: object) -> None:
    with TestClient(create_app()) as client:
        assert client.patch("/conversations/missing/pin", json={"is_pinned": value}).status_code == 422


def test_pin_and_unpin_survive_application_restart(tmp_path: Path) -> None:
    settings = Settings(persistence_provider="relational", persistence_database_url=str(tmp_path / "restart.sqlite3"))
    with TestClient(create_app(settings=settings)) as client:
        created = client.post("/conversations", json={"title": "Durable"}).json()
        path = f"/conversations/{created['conversation_id']}"
        assert client.patch(f"{path}/pin", json={"is_pinned": True}).json()["is_pinned"] is True
    with TestClient(create_app(settings=settings)) as client:
        assert client.get(path).json()["is_pinned"] is True
        assert client.patch(f"{path}/pin", json={"is_pinned": False}).json()["is_pinned"] is False
    with TestClient(create_app(settings=settings)) as client:
        assert client.get(path).json() == created
