"""Conversation/message API tests (Step 4.4).

API-level coverage for the conversation transport layer: creating, reading,
renaming, and listing conversations, and appending/listing messages, through
``/conversations`` and ``/conversations/{conversation_id}/messages``. The
routes must operate on AVA-owned contracts, delegate to ``ConversationService``,
and never expose internal identifiers from clients.
"""

from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.contracts.version import CONTRACT_VERSION

# ============================================================
# BEGIN: Helpers
# ============================================================


def make_client() -> TestClient:
    """Create a test client with a default application."""
    return TestClient(create_app())


def create_conversation(client: TestClient, title: str | None = None) -> dict[str, Any]:
    """Create a conversation and return the parsed response body."""
    payload: dict[str, str] = {}
    if title is not None:
        payload["title"] = title
    response = client.post("/conversations", json=payload)
    assert response.status_code == 201
    return dict(response.json())


# ============================================================
# END: Helpers
# ============================================================


# ============================================================
# BEGIN: Create Conversation
# ============================================================


def test_create_conversation_returns_201_and_response_shape() -> None:
    """A valid conversation create should return 201 with the response contract."""
    with make_client() as client:
        body = create_conversation(client, title="My Project")

    assert set(body) == {
        "conversation_id",
        "title",
        "created_at",
        "updated_at",
        "is_pinned",
        "is_archived",
        "folder_id",
        "project_id",
        "is_title_custom",
        "contract_version",
    }
    assert body["title"] == "My Project"
    assert body["is_pinned"] is False
    assert body["is_archived"] is False
    assert body["folder_id"] is None
    assert body["project_id"] is None
    assert body["is_title_custom"] is True
    assert body["contract_version"] == CONTRACT_VERSION


def test_create_conversation_defaults_title() -> None:
    """An omitted title resolves to the service default."""
    with make_client() as client:
        body = create_conversation(client)
    assert body["title"] == "New Conversation"
    assert body["is_title_custom"] is False


def test_create_conversation_in_folder_sets_folder_atomically_without_project_membership() -> None:
    """Folder creation is one create request and never infers Project ownership."""
    with make_client() as client:
        folder_response = client.post("/conversation-folders", json={"name": "Engineering"})
        assert folder_response.status_code == 201
        folder_id = folder_response.json()["id"]

        response = client.post("/conversations", json={"folder_id": folder_id})

    assert response.status_code == 201
    assert response.json()["folder_id"] == folder_id
    assert response.json()["project_id"] is None


def test_create_conversation_rejects_a_missing_folder() -> None:
    with make_client() as client:
        response = client.post("/conversations", json={"folder_id": "missing-folder"})

    assert response.status_code == 404
    assert response.json()["error_code"] == "conversation_folder_not_found"


def test_create_conversation_mints_valid_ava_owned_uuid() -> None:
    """The conversation identifier is a service-generated UUID."""
    with make_client() as client:
        body = create_conversation(client)
    conversation_id = body["conversation_id"]
    assert UUID(conversation_id)
    assert str(UUID(conversation_id)) == conversation_id


def test_create_conversation_timestamps_are_utc_iso() -> None:
    """Timestamps serialize as timezone-aware ISO strings."""
    from datetime import datetime

    with make_client() as client:
        body = create_conversation(client)
    for raw in (body["created_at"], body["updated_at"]):
        parsed = datetime.fromisoformat(raw)
        assert parsed.tzinfo is not None
        offset = parsed.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0


def test_create_conversation_duplicate_maps_to_409() -> None:
    """A duplicate conversation identifier collision maps to 409."""
    from ava.repositories import ConversationRecord, ConversationRepository
    from ava.services.conversation_service import ConversationService
    from ava.services.message_store import MessageStore

    class AlwaysDuplicate(ConversationRepository):
        def create(self, conversation_id: str, *, title: str) -> ConversationRecord:
            raise ValueError(f"Conversation already exists: {conversation_id}")

        def get(self, conversation_id: str) -> ConversationRecord | None:
            return None

        def list(self, search: str | None = None) -> list[ConversationRecord]:
            return []

        def set_pinned(self, conversation_id: str, is_pinned: bool) -> ConversationRecord | None:
            return None

        def set_archived(self, conversation_id: str, is_archived: bool) -> ConversationRecord | None:
            return None

        def set_folder(self, conversation_id: str, folder_id: str | None) -> ConversationRecord | None:
            return None

        def set_project(self, conversation_id: str, project_id: str | None) -> ConversationRecord | None:
            return None

        def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
            return None

    app = create_app()
    app.state.conversation_service = ConversationService(
        conversation_repository=AlwaysDuplicate(),
        message_repository=MessageStore(),
    )
    with TestClient(app) as client:
        response = client.post("/conversations", json={})
    assert response.status_code == 409
    body = dict(response.json())
    assert body["error_code"] == "conversation_id_conflict"
    assert body["category"] == "validation"


# ============================================================
# END: Create Conversation
# ============================================================


# ============================================================
# BEGIN: List Conversations
# ============================================================


def test_list_conversations_is_empty_until_a_create() -> None:
    with make_client() as client:
        response = client.get("/conversations")
    assert response.status_code == 200
    assert response.json() == {"contract_version": CONTRACT_VERSION, "conversations": []}


def test_list_conversations_in_canonical_order() -> None:
    with make_client() as client:
        first = create_conversation(client, title="First")
        second = create_conversation(client, title="Second")
        response = client.get("/conversations")

    assert response.status_code == 200
    body = dict(response.json())
    expected = sorted(
        [first, second], key=lambda item: item["conversation_id"]
    )
    expected.sort(
        key=lambda item: (item["is_pinned"], item["updated_at"], item["created_at"]),
        reverse=True,
    )
    assert [c["conversation_id"] for c in body["conversations"]] == [
        item["conversation_id"] for item in expected
    ]


# ============================================================
# END: List Conversations
# ============================================================


# ============================================================
# BEGIN: Get Conversation
# ============================================================


def test_get_conversation_returns_snapshot() -> None:
    with make_client() as client:
        created = create_conversation(client, title="Known")
        response = client.get(f"/conversations/{created['conversation_id']}")

    assert response.status_code == 200
    assert dict(response.json()) == created


def test_get_unknown_conversation_returns_404_resource() -> None:
    with make_client() as client:
        response = client.get("/conversations/ghost")
    assert response.status_code == 404
    body = dict(response.json())
    assert body["error_code"] == "conversation_not_found"
    assert body["category"] == "not_found"


# ============================================================
# END: Get Conversation
# ============================================================


# ============================================================
# BEGIN: Rename Conversation
# ============================================================


def test_rename_conversation_returns_updated_snapshot() -> None:
    with make_client() as client:
        created = create_conversation(client, title="Old")
        response = client.patch(
            f"/conversations/{created['conversation_id']}", json={"title": "Renamed"}
        )

    assert response.status_code == 200
    body = dict(response.json())
    assert body["title"] == "Renamed"
    assert body["conversation_id"] == created["conversation_id"]
    assert body["is_title_custom"] is True


def test_rename_unknown_conversation_returns_404_resource() -> None:
    with make_client() as client:
        response = client.patch("/conversations/ghost", json={"title": "Renamed"})
    assert response.status_code == 404
    assert dict(response.json())["error_code"] == "conversation_not_found"


def test_rename_conversation_rejects_blank_title() -> None:
    with make_client() as client:
        created = create_conversation(client)
        response = client.patch(
            f"/conversations/{created['conversation_id']}", json={"title": "   "}
        )
    assert response.status_code == 422


# ============================================================
# END: Rename Conversation
# ============================================================


# ============================================================
# BEGIN: Append Message
# ============================================================


def test_append_message_returns_201_and_response_shape() -> None:
    """A valid message append returns 201 with the message contract."""
    with make_client() as client:
        conversation = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation['conversation_id']}/messages",
            json={"content": "Hello AVA"},
        )

    assert response.status_code == 201
    body = dict(response.json())
    assert set(body) == {
        "message_id",
        "conversation_id",
        "role",
        "content",
        "status",
        "source_run_id",
        "source_user_message_id",
        "error_code",
        "created_at",
        "updated_at",
        "contract_version",
    }
    assert body["content"] == "Hello AVA"
    assert body["role"] == "user"
    assert body["status"] == "complete"
    assert body["source_run_id"] is None
    assert body["source_user_message_id"] is None
    assert body["error_code"] is None
    assert body["conversation_id"] == conversation["conversation_id"]
    assert body["contract_version"] == CONTRACT_VERSION


def test_first_user_message_auto_titles_an_untouched_conversation() -> None:
    with make_client() as client:
        conversation = create_conversation(client)
        conversation_id = conversation["conversation_id"]
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "  Explain   dependency injection  "},
        )
        assert message.status_code == 201
        current = client.get(f"/conversations/{conversation_id}")

    assert current.status_code == 200
    assert current.json()["title"] == "Explain dependency injection"
    assert current.json()["is_title_custom"] is False


def test_append_message_mints_valid_ava_owned_uuid() -> None:
    with make_client() as client:
        conversation = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation['conversation_id']}/messages",
            json={"content": "Hi"},
        )
    assert UUID(dict(response.json())["message_id"])


def test_append_message_accepts_role_and_source_run_id() -> None:
    with make_client() as client:
        conversation = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation['conversation_id']}/messages",
            json={"content": "Answer", "role": "assistant", "source_run_id": "run-1"},
        )
    body = dict(response.json())
    assert body["role"] == "assistant"
    assert body["source_run_id"] == "run-1"


def test_append_message_unknown_conversation_returns_404_resource() -> None:
    with make_client() as client:
        response = client.post("/conversations/ghost/messages", json={"content": "Hi"})
    assert response.status_code == 404
    assert dict(response.json())["error_code"] == "conversation_not_found"


def test_append_message_rejects_invalid_role() -> None:
    with make_client() as client:
        conversation = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation['conversation_id']}/messages",
            json={"content": "Hi", "role": "supervisor"},
        )
    assert response.status_code == 422


def test_append_message_rejects_blank_content() -> None:
    with make_client() as client:
        conversation = create_conversation(client)
        response = client.post(
            f"/conversations/{conversation['conversation_id']}/messages",
            json={"content": "   "},
        )
    assert response.status_code == 422


def test_append_message_duplicate_maps_to_409() -> None:
    """A duplicate message identifier collision maps to 409."""
    from ava.repositories import MessageRecord, MessageRepository
    from ava.services.conversation_service import ConversationService
    from ava.services.conversation_store import ConversationStore

    class AlwaysDuplicate(MessageRepository):
        def append(self, message: MessageRecord) -> MessageRecord:
            raise ValueError(f"Message already exists: {message.message_id}")

        def get(self, conversation_id: str, message_id: str) -> MessageRecord | None:
            return None

        def list_for_conversation(self, conversation_id: str) -> list[MessageRecord]:
            return []

    conversation_store = ConversationStore()
    conversation_store.create("conv-seeded", title="Seeded")
    app = create_app()
    app.state.conversation_service = ConversationService(
        conversation_repository=conversation_store,
        message_repository=AlwaysDuplicate(),
    )
    with TestClient(app) as client:
        response = client.post("/conversations/conv-seeded/messages", json={"content": "Hi"})
    assert response.status_code == 409
    body = dict(response.json())
    assert body["error_code"] == "message_id_conflict"
    assert body["category"] == "validation"


# ============================================================
# END: Append Message
# ============================================================


# ============================================================
# BEGIN: List Messages
# ============================================================


def test_list_messages_preserves_append_order() -> None:
    with make_client() as client:
        conversation = create_conversation(client)
        client.post(f"/conversations/{conversation['conversation_id']}/messages", json={"content": "One"})
        client.post(f"/conversations/{conversation['conversation_id']}/messages", json={"content": "Two"})
        response = client.get(f"/conversations/{conversation['conversation_id']}/messages")

    assert response.status_code == 200
    body = dict(response.json())
    assert body["conversation_id"] == conversation["conversation_id"]
    assert [m["content"] for m in body["messages"]] == ["One", "Two"]


def test_list_messages_empty_conversation_yields_empty_list() -> None:
    with make_client() as client:
        conversation = create_conversation(client)
        response = client.get(f"/conversations/{conversation['conversation_id']}/messages")
    assert response.status_code == 200
    assert dict(response.json())["messages"] == []


def test_list_messages_unknown_conversation_returns_404_resource() -> None:
    with make_client() as client:
        response = client.get("/conversations/ghost/messages")
    assert response.status_code == 404
    assert dict(response.json())["error_code"] == "conversation_not_found"


# ============================================================
# END: List Messages
# ============================================================


def test_prompt_preview_returns_backend_resolved_root_for_a_conversation_without_runs() -> None:
    with make_client() as client:
        conversation = create_conversation(client)
        response = client.get(f"/conversations/{conversation['conversation_id']}/prompt-preview")

    assert response.status_code == 200
    body = response.json()
    assert body["root_system_prompt"] == (
        "You are AVA, an AI assistant. Respond helpfully and accurately to the user's request."
    )
    assert body["resolved_core_prompts"] == []
    assert body["project_instructions"] is None


def test_global_prompt_preview_is_available_before_a_conversation_is_created() -> None:
    with make_client() as client:
        response = client.get("/prompt-preview")

    assert response.status_code == 200
    assert response.json()["root_system_prompt"].startswith("You are AVA,")
