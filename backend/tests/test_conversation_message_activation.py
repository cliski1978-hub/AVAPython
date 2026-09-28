"""Conversation/message persistence activation tests (Step 4.9).

``AVA_PERSISTENCE=relational`` now also routes the conversation and message
repository ports to the durable relational adapters over **one shared**
``SqliteDatabase`` (alongside the Step 4.8 run/run-event activation); the
document domain stays memory-backed until Step 4.10. ``AVA_PERSISTENCE=memory``
remains the default and installs every store.

The durability proof is the application-level restart: conversations and
messages written through one application survive ``dispose()`` and are re-read
through a second application over the same database file. The behavioral
equivalence tests drive the same conversation/message scenarios through both
compositions to show implementational interchangeability.
"""

from uuid import UUID, uuid4

import pytest

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.conversations import MessageRole
from ava.infrastructure.composition import (
    ApplicationPersistence,
    create_application_persistence,
)
from ava.infrastructure.persistence.repositories import (
    RelationalConversationRepository,
    RelationalMessageRepository,
)
from ava.services.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
)
from ava.services.conversation_store import ConversationStore
from ava.services.message_store import MessageStore

# ============================================================
# BEGIN: Helpers
# ============================================================


def relational_settings(database_url: str) -> Settings:
    """Build relational Settings pointing at ``database_url``."""
    return Settings(
        persistence_provider="relational",
        persistence_database_url=database_url,
    )


MODE_TO_SETTINGS = {
    "memory": lambda path: Settings(),
    "relational": lambda path: relational_settings(str(path / "ava.sqlite3")),
}


def compose_conversation_service(
    mode: str, tmp_path
) -> tuple[ConversationService, ApplicationPersistence]:
    """Compose the ConversationService the application wires over the selection."""
    persistence = create_application_persistence(MODE_TO_SETTINGS[mode](tmp_path))
    service = ConversationService(
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
    )
    return service, persistence


# ============================================================
# END: Helpers
# ============================================================


# ============================================================
# BEGIN: Composition Selection
# ============================================================


def test_default_persistence_selects_in_memory_conversation_and_message_stores() -> None:
    """The unconfigured default keeps ConversationStore/MessageStore, no database."""
    persistence = create_application_persistence(Settings())
    assert isinstance(persistence.conversation_repository, ConversationStore)
    assert isinstance(persistence.message_repository, MessageStore)
    assert persistence.database is None


def test_relational_persistence_selects_relational_conversation_and_message_adapters(
    tmp_path,
) -> None:
    """Relational settings wire the durable conversation/message adapters."""
    persistence = create_application_persistence(
        relational_settings(str(tmp_path / "ava.sqlite3"))
    )
    assert isinstance(
        persistence.conversation_repository, RelationalConversationRepository
    )
    assert isinstance(persistence.message_repository, RelationalMessageRepository)
    assert persistence.database is not None
    persistence.dispose()


def test_relational_adapters_share_one_database_instance(tmp_path) -> None:
    """All four activated relational adapters share the same SqliteDatabase."""
    persistence = create_application_persistence(
        relational_settings(str(tmp_path / "ava.sqlite3"))
    )
    run_db = persistence.run_repository._database
    assert run_db is persistence.run_event_repository._database
    assert run_db is persistence.conversation_repository._database
    assert run_db is persistence.message_repository._database
    assert run_db is persistence.database
    persistence.dispose()


# ============================================================
# END: Composition Selection
# ============================================================


# ============================================================
# BEGIN: Conversation Restart Durability
# ============================================================


def test_conversation_survives_application_restart(tmp_path) -> None:
    """A created+renamed conversation survives a full application restart.

    App A creates and renames the conversation; shutdown disposes the
    database. App B over the same file must list the same conversation (same
    id, title, timestamps, ordering) and serve the identical snapshot.
    """
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))

    with _client(settings) as client:
        created = client.post("/conversations", json={"title": "Initial"}).json()
        conversation_id = created["conversation_id"]
        created_at = created["created_at"]
        renamed = client.patch(
            f"/conversations/{conversation_id}", json={"title": "Renamed"}
        ).json()
        assert renamed["title"] == "Renamed"
        assert renamed["updated_at"] != created["updated_at"]

    with _client(settings) as client:
        listed = client.get("/conversations").json()["conversations"]
        assert [entry["conversation_id"] for entry in listed] == [conversation_id]
        snapshot = listed[0]
        assert snapshot["title"] == "Renamed"
        assert snapshot["created_at"] == created_at
        assert snapshot["updated_at"] == renamed["updated_at"]

        fetched = client.get(f"/conversations/{conversation_id}")
        assert fetched.status_code == 200
        assert fetched.json() == snapshot


def test_multiple_conversations_persist_isolated_and_ordered(tmp_path) -> None:
    """Two conversations stay isolated and ordered across an application restart."""
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))

    with _client(settings) as client:
        first = client.post("/conversations", json={"title": "First"}).json()
        second = client.post("/conversations", json={"title": "Second"}).json()
        assert first["conversation_id"] != second["conversation_id"]

    with _client(settings) as client:
        listed = client.get("/conversations").json()["conversations"]
        assert [entry["conversation_id"] for entry in listed] == [
            first["conversation_id"],
            second["conversation_id"],
        ]
        assert [entry["title"] for entry in listed] == ["First", "Second"]


# ============================================================
# END: Conversation Restart Durability
# ============================================================


# ============================================================
# BEGIN: Message Restart Durability
# ============================================================


def test_messages_survive_application_restart(tmp_path) -> None:
    """User/assistant messages survive the restart with full fidelity."""
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))

    with _client(settings) as client:
        conversation_id = client.post("/conversations", json={}).json()["conversation_id"]
        first = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "Hello from user", "role": "user"},
        ).json()
        second = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "Hello from assistant", "role": "assistant"},
        ).json()
        before = client.get(f"/conversations/{conversation_id}/messages").json()

    with _client(settings) as client:
        after = client.get(f"/conversations/{conversation_id}/messages")
        assert after.status_code == 200
        body = after.json()
        assert body["conversation_id"] == conversation_id
        assert [m["message_id"] for m in body["messages"]] == [
            first["message_id"],
            second["message_id"],
        ]
        assert [m["content"] for m in body["messages"]] == [
            "Hello from user",
            "Hello from assistant",
        ]
        assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
        assert [m["status"] for m in body["messages"]] == ["complete", "complete"]
        assert all(
            m["conversation_id"] == conversation_id for m in body["messages"]
        )
        assert body["messages"] == before["messages"]


# ============================================================
# END: Message Restart Durability
# ============================================================


# ============================================================
# BEGIN: Behavioral Equivalence (memory vs relational)
# ============================================================


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_message_round_trip_preserves_role_status_and_content(mode, tmp_path) -> None:
    """Every AVA role round-trips with exact content and COMPLETE status."""

    service, persistence = compose_conversation_service(mode, tmp_path)
    try:
        conversation = service.create_conversation(title="Roles")
        expected_ids: list[str] = []
        for role in (MessageRole.USER, MessageRole.ASSISTANT, MessageRole.SYSTEM):
            message = service.append_message(
                conversation.conversation_id,
                content=f"content-{role}",
                role=role,
            )
            assert message.role == role
            assert message.status.value == "complete"
            assert message.content == f"content-{role}"
            expected_ids.append(message.message_id)

        listed = service.list_messages(conversation.conversation_id)
        assert listed is not None
        assert [m.message_id for m in listed.messages] == expected_ids
        assert [m.role for m in listed.messages] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
            MessageRole.SYSTEM,
        ]
        assert all(m.status.value == "complete" for m in listed.messages)
        assert [m.content for m in listed.messages] == [
            "content-user",
            "content-assistant",
            "content-system",
        ]
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_message_ordering_matches_in_both_modes(mode, tmp_path) -> None:
    """Interleaved user/assistant messages preserve exact append order."""

    service, persistence = compose_conversation_service(mode, tmp_path)
    try:
        conversation = service.create_conversation(title="Ordered")
        expected: list[tuple[str, str]] = []
        for index, (role, content) in enumerate(
            [
                (MessageRole.USER, "u1"),
                (MessageRole.ASSISTANT, "a1"),
                (MessageRole.USER, "u2"),
                (MessageRole.ASSISTANT, "a2"),
            ]
        ):
            message = service.append_message(
                conversation.conversation_id, content=content, role=role
            )
            expected.append((message.message_id, content))
            other = service.create_conversation(title=f"other-{index}")
            service.append_message(other.conversation_id, content=f"stray-{index}")

        listed = service.list_messages(conversation.conversation_id)
        assert listed is not None
        assert [(m.message_id, m.content) for m in listed.messages] == expected
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_conversation_and_message_isolation_matches_in_both_modes(mode, tmp_path) -> None:
    """Messages never bleed across conversations in either mode."""

    service, persistence = compose_conversation_service(mode, tmp_path)
    try:
        first = service.create_conversation(title="One")
        second = service.create_conversation(title="Two")
        service.append_message(first.conversation_id, content="for-one")
        service.append_message(second.conversation_id, content="for-two")

        first_messages = service.list_messages(first.conversation_id)
        second_messages = service.list_messages(second.conversation_id)
        assert first_messages is not None and second_messages is not None
        assert [m.content for m in first_messages.messages] == ["for-one"]
        assert [m.content for m in second_messages.messages] == ["for-two"]
        assert service.get_message(second.conversation_id, first_messages.messages[0].message_id) is None
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_unknown_conversation_behavior_matches_in_both_modes(mode, tmp_path) -> None:
    """Service-level unknown-conversation semantics match across modes."""

    service, persistence = compose_conversation_service(mode, tmp_path)
    try:
        unknown = str(uuid4())
        assert service.get_conversation(unknown) is None
        assert service.update_title(unknown, "nope") is None
        assert service.list_messages(unknown) is None
        with pytest.raises(ConversationNotFoundError):
            service.append_message(unknown, content="orphan")
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_unknown_conversation_routes_match_in_both_modes(mode, tmp_path) -> None:
    """GET/PATCH/append/list responses for an unknown conversation are identical."""

    unknown = str(uuid4())
    settings = MODE_TO_SETTINGS[mode](tmp_path)
    with _client(settings) as client:
        assert client.get(f"/conversations/{unknown}").json()["error_code"] == "conversation_not_found"
        patch = client.patch(f"/conversations/{unknown}", json={"title": "x"})
        assert patch.status_code == 404
        assert patch.json()["error_code"] == "conversation_not_found"
        append = client.post(
            f"/conversations/{unknown}/messages", json={"content": "x"}
        )
        assert append.status_code == 404
        assert append.json()["error_code"] == "conversation_not_found"
        listed = client.get(f"/conversations/{unknown}/messages")
        assert listed.status_code == 404
        assert listed.json()["error_code"] == "conversation_not_found"


# ============================================================
# END: Behavioral Equivalence
# ============================================================


# ============================================================
# BEGIN: Duplicate Conflict Semantics
# ============================================================


def test_relational_conversation_duplicate_maps_to_repository_semantics(tmp_path) -> None:
    """A real SQLite collision surfaces as ValueError, never a driver error."""
    persistence = create_application_persistence(
        relational_settings(str(tmp_path / "ava.sqlite3"))
    )
    try:
        conversation_id = str(uuid4())
        persistence.conversation_repository.create(
            conversation_id, title="First"
        )
        with pytest.raises(ValueError):
            persistence.conversation_repository.create(
                conversation_id, title="Duplicate"
            )
    finally:
        persistence.dispose()


def test_relational_message_duplicate_maps_to_repository_semantics(tmp_path) -> None:
    """A real SQLite message collision surfaces as ValueError."""
    persistence = create_application_persistence(
        relational_settings(str(tmp_path / "ava.sqlite3"))
    )
    try:
        service = ConversationService(
            conversation_repository=persistence.conversation_repository,
            message_repository=persistence.message_repository,
        )
        conversation = service.create_conversation(title="Duplicates")
        duplicate = service.append_message(
            conversation.conversation_id, content="same id" * 2
        )
        from ava.contracts.conversations import MessageStatus
        from ava.repositories import MessageRecord

        with pytest.raises(ValueError):
            persistence.message_repository.append(
                MessageRecord(
                    message_id=duplicate.message_id,
                    conversation_id=conversation.conversation_id,
                    role=MessageRole.USER,
                    content="dup",
                    status=MessageStatus.COMPLETE,
                    created_at=duplicate.created_at,
                    updated_at=duplicate.updated_at,
                )
            )
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_duplicate_conflict_routes_are_unchanged(mode, tmp_path, monkeypatch) -> None:
    """Real duplicate collisions surface as the same 409 contract in both modes.

    The service mints uuid4 identifiers; pinning the generator forces genuine
    collisions inside the configured repository so the full HTTP → service →
    repository → 409 path is exercised against both implementations. Both
    domains mint one uuid per create, so a single pinned id collides for both
    a second conversation and a second message.
    """
    fixed_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(
        "ava.services.conversation_service.uuid4",
        lambda: UUID(fixed_id),
    )

    settings = MODE_TO_SETTINGS[mode](tmp_path) if mode == "relational" else None
    app = create_app(settings=settings)
    app.state.conversation_service = ConversationService(
        conversation_repository=app.state.persistence.conversation_repository,
        message_repository=app.state.persistence.message_repository,
    )

    with _client_for_app(app) as client:
        created = client.post("/conversations", json={"title": "x"})
        assert created.status_code == 201
        assert created.json()["conversation_id"] == fixed_id

        duplicate_conversation = client.post("/conversations", json={"title": "dup"})
        assert duplicate_conversation.status_code == 409
        assert duplicate_conversation.json()["error_code"] == "conversation_id_conflict"
        assert duplicate_conversation.json()["category"] == "validation"

        first = client.post(
            f"/conversations/{fixed_id}/messages", json={"content": "one"}
        )
        assert first.status_code == 201
        assert first.json()["message_id"] == fixed_id

        duplicate_message = client.post(
            f"/conversations/{fixed_id}/messages", json={"content": "two"}
        )
        assert duplicate_message.status_code == 409
        assert duplicate_message.json()["error_code"] == "message_id_conflict"
        assert duplicate_message.json()["category"] == "validation"


# ============================================================
# END: Duplicate Conflict Semantics
# ============================================================


# ============================================================
# BEGIN: Cross-Domain Durability
# ============================================================


def test_one_relational_application_stores_runs_and_conversations_together(
    tmp_path,
) -> None:
    """Run, RunEvent, Conversation, and Message share one durable database.

    App A writes a completed run and a conversation with two messages; app B
    over the same file retrieves all four domains correctly. This proves the
    composition is converging toward one durable application store rather
    than independent databases.
    """
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))

    with _client(settings) as client:
        run = client.post("/runs", json={"prompt": "cross-domain"}).json()
        run_id = run["run_id"]
        assert run["status"] == "running"
        run = client.get(f"/runs/{run_id}").json()
        assert run["status"] == "completed"

        conversation_id = client.post("/conversations", json={"title": "Shared DB"}).json()[
            "conversation_id"
        ]
        user_message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "user says", "role": "user"},
        ).json()
        assistant_message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "assistant says", "role": "assistant"},
        ).json()

    with _client(settings) as client:
        run_snapshot = client.get(f"/runs/{run_id}")
        assert run_snapshot.status_code == 200
        assert run_snapshot.json()["status"] == "completed"
        events = client.get(f"/runs/{run_id}/events")
        assert events.status_code == 200
        assert [e["event_type"] for e in events.json()] == [
            "run_started",
            "message_started",
            "message_content",
            "run_completed",
        ]

        conversations = client.get("/conversations").json()["conversations"]
        assert [entry["conversation_id"] for entry in conversations] == [conversation_id]
        assert conversations[0]["title"] == "Shared DB"

        messages = client.get(f"/conversations/{conversation_id}/messages").json()["messages"]
        assert [m["message_id"] for m in messages] == [
            user_message["message_id"],
            assistant_message["message_id"],
        ]
        assert [m["role"] for m in messages] == ["user", "assistant"]


# ============================================================
# END: Cross-Domain Durability
# ============================================================


def _client(settings: Settings):
    """A TestClient bound to an application composed over ``settings``."""
    from fastapi.testclient import TestClient

    return TestClient(create_app(settings=settings))


def _client_for_app(app):
    """A TestClient bound to a prepared application instance."""
    from fastapi.testclient import TestClient

    return TestClient(app)
