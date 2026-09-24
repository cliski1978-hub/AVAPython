"""Relational message repository tests (Step 4.6).

Mirror the in-memory ``MessageStore`` semantics against the SQLite-backed
``RelationalMessageRepository``: immutable storage verbatim (timestamps not
re-minted), stable append order per conversation, conversation-scoped lookup,
duplicate rejection via ``ValueError``, and role/status/source-run
round-tripping.
"""

from datetime import UTC, datetime

import pytest

from ava.contracts.conversations import MessageRole, MessageStatus
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import RelationalMessageRepository
from ava.repositories import MessageRecord


@pytest.fixture()
def repository() -> tuple[RelationalMessageRepository, SqliteDatabase]:
    database = SqliteDatabase(":memory:")
    yield RelationalMessageRepository(database=database), database
    database.dispose()


def _message(
    message_id: str,
    conversation_id: str,
    *,
    role: MessageRole = MessageRole.USER,
    content: str = "hello",
    status: MessageStatus = MessageStatus.COMPLETE,
    source_run_id: str | None = None,
    timestamp: datetime | None = None,
) -> MessageRecord:
    at = timestamp or datetime.now(UTC)
    return MessageRecord(
        message_id=message_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        status=status,
        source_run_id=source_run_id,
        created_at=at,
        updated_at=at,
    )


# ============================================================
# BEGIN: Append semantics
# ============================================================


def test_append_stores_message_verbatim(repository: tuple[RelationalMessageRepository, SqliteDatabase]) -> None:
    message_repository, _ = repository
    timestamp = datetime(2026, 9, 18, 12, 30, 15, 123456, tzinfo=UTC)
    message = _message("m1", "c1", content="<p>hi</p>", timestamp=timestamp)
    returned = message_repository.append(message)
    assert returned == message
    stored = message_repository.get("c1", "m1")
    assert stored is not None
    assert stored == message
    assert stored.created_at == timestamp
    assert stored.updated_at == timestamp
    assert stored.content == "<p>hi</p>"


def test_isolation_between_conversations(repository: tuple[RelationalMessageRepository, SqliteDatabase]) -> None:
    message_repository, _ = repository
    message_repository.append(_message("shared-id", "c1", content="in c1"))
    message_repository.append(_message("shared-id", "c2", content="in c2"))
    assert message_repository.get("c1", "shared-id").content == "in c1"
    assert message_repository.get("c2", "shared-id").content == "in c2"
    assert message_repository.get("c1", "missing") is None
    assert message_repository.get("c2", "missing") is None


def test_list_for_conversation_is_in_append_order(
    repository: tuple[RelationalMessageRepository, SqliteDatabase],
) -> None:
    message_repository, _ = repository
    for message_id in ("m1", "m2", "m3"):
        message_repository.append(_message(message_id, "c1"))
    message_repository.append(_message("other", "c2"))
    assert [m.message_id for m in message_repository.list_for_conversation("c1")] == ["m1", "m2", "m3"]
    assert [m.message_id for m in message_repository.list_for_conversation("c2")] == ["other"]


def test_list_for_unknown_conversation_is_empty(
    repository: tuple[RelationalMessageRepository, SqliteDatabase],
) -> None:
    message_repository, _ = repository
    assert message_repository.list_for_conversation("ghost") == []


def test_duplicate_append_raises_value_error(repository: tuple[RelationalMessageRepository, SqliteDatabase]) -> None:
    message_repository, _ = repository
    message_repository.append(_message("m1", "c1"))
    with pytest.raises(ValueError, match="Message already exists: m1"):
        message_repository.append(_message("m1", "c1", content="duplicate"))


# ============================================================
# END: Append semantics
# ============================================================


# ============================================================
# BEGIN: Vocabulary round-tripping
# ============================================================


@pytest.mark.parametrize("role", [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.SYSTEM])
@pytest.mark.parametrize("status", [MessageStatus.PENDING, MessageStatus.COMPLETE])
def test_role_and_status_round_trip(repository, role, status) -> None:
    message_repository, _ = repository
    message = _message("m1", "c1", role=role, status=status)
    message_repository.append(message)
    stored = message_repository.get("c1", "m1")
    assert stored is not None
    assert stored.role == role
    assert stored.status == status


def test_source_run_id_round_trip(repository: tuple[RelationalMessageRepository, SqliteDatabase]) -> None:
    message_repository, _ = repository
    message_repository.append(_message("m1", "c1", source_run_id="run-9"))
    assert message_repository.get("c1", "m1").source_run_id == "run-9"
    message_repository.append(_message("m2", "c1", source_run_id=None))
    assert message_repository.get("c1", "m2").source_run_id is None


# ============================================================
# END: Vocabulary round-tripping
# ============================================================