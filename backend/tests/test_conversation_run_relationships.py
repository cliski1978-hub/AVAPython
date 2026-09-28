"""Phase 5.19 durable conversation/run relationship integration tests."""

from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings


def _settings(tmp_path) -> Settings:
    return Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "relationships.sqlite3"),
        attachment_storage="memory",
    )


def _conversation_with_user(client: TestClient, content: str = "Ask AVA") -> tuple[str, str]:
    conversation = client.post("/conversations", json={"title": content}).json()
    message = client.post(
        f"/conversations/{conversation['conversation_id']}/messages",
        json={"content": content, "role": "user"},
    ).json()
    return conversation["conversation_id"], message["message_id"]


def _linked_run(client: TestClient, conversation_id: str, user_message_id: str) -> dict[str, object]:
    response = client.post(
        "/runs",
        json={
            "prompt": "Ask AVA",
            "conversation_id": conversation_id,
            "source_user_message_id": user_message_id,
        },
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["status"] == "running"
    return client.get(f"/runs/{accepted['run_id']}").json()


def test_linked_run_persists_conversation_source_assistant_and_events(tmp_path) -> None:
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        conversation_id, user_message_id = _conversation_with_user(client)
        run = _linked_run(client, conversation_id, user_message_id)

        assert run["conversation_id"] == conversation_id
        assert run["source_user_message_id"] == user_message_id
        assert isinstance(run["assistant_message_id"], str)
        stored = client.get(f"/runs/{run['run_id']}").json()
        assert stored == run
        messages = client.get(f"/conversations/{conversation_id}/messages").json()["messages"]
        assert [message["message_id"] for message in messages] == [user_message_id, run["assistant_message_id"]]
        assert messages[1]["role"] == "assistant"
        assert messages[1]["source_run_id"] == run["run_id"]
        events = client.get(f"/runs/{run['run_id']}/events").json()
        assert all(event["run_id"] == run["run_id"] for event in events)
        started = next(event for event in events if event["event_type"] == "message_started")
        assert started["payload"]["message_id"] == run["assistant_message_id"]


def test_linked_run_rejects_cross_conversation_source_message(tmp_path) -> None:
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        first_conversation, _ = _conversation_with_user(client, "First")
        _, second_message = _conversation_with_user(client, "Second")
        response = client.post(
            "/runs",
            json={
                "prompt": "Ask AVA",
                "conversation_id": first_conversation,
                "source_user_message_id": second_message,
            },
        )
        assert response.status_code == 422
        assert response.json()["error_code"] == "invalid_run_relationship"


def test_linked_run_rejects_non_user_source_message(tmp_path) -> None:
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        conversation_id, _ = _conversation_with_user(client)
        assistant = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "Existing answer", "role": "assistant"},
        ).json()
        response = client.post(
            "/runs",
            json={
                "prompt": "Ask again",
                "conversation_id": conversation_id,
                "source_user_message_id": assistant["message_id"],
            },
        )
        assert response.status_code == 422
        assert "role user" in response.json()["message"]


def test_relationships_reconstruct_after_restart(tmp_path) -> None:
    settings = _settings(tmp_path)
    first_app = create_app(settings=settings)
    with TestClient(first_app) as client:
        conversation_id, user_message_id = _conversation_with_user(client)
        seeded = _linked_run(client, conversation_id, user_message_id)
        event_ids = [event["event_id"] for event in client.get(f"/runs/{seeded['run_id']}/events").json()]
    first_app.state.persistence.dispose()

    with TestClient(create_app(settings=settings)) as client:
        restored = client.get(f"/runs/{seeded['run_id']}").json()
        assert restored == seeded
        messages = client.get(f"/conversations/{conversation_id}/messages").json()["messages"]
        assert [message["message_id"] for message in messages] == [
            user_message_id,
            seeded["assistant_message_id"],
        ]
        assert [event["event_id"] for event in client.get(f"/runs/{seeded['run_id']}/events").json()] == event_ids


def test_regenerate_keeps_prior_runs_and_assistant_responses(tmp_path) -> None:
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        conversation_id, user_message_id = _conversation_with_user(client)
        runs = [_linked_run(client, conversation_id, user_message_id) for _ in range(3)]
        assert len({run["run_id"] for run in runs}) == 3
        assert len({run["assistant_message_id"] for run in runs}) == 3
        assert all(run["source_user_message_id"] == user_message_id for run in runs)
        messages = client.get(f"/conversations/{conversation_id}/messages").json()["messages"]
        assert [message["message_id"] for message in messages] == [
            user_message_id,
            *(run["assistant_message_id"] for run in runs),
        ]
        assert [message["source_run_id"] for message in messages[1:]] == [
            run["run_id"] for run in runs
        ]
