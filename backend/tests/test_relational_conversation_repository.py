"""Relational conversation repository tests (Step 4.6).

Mirror the in-memory ``ConversationStore`` semantics against the SQLite-backed
``RelationalConversationRepository``: stable insertion-order listing, duplicate
rejection via ``ValueError``, title updates that refresh ``updated_at``, and
unknown-conversation ``None`` results.
"""

from datetime import UTC, datetime

import pytest

from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import RelationalConversationRepository


@pytest.fixture()
def repository() -> tuple[RelationalConversationRepository, SqliteDatabase]:
    database = SqliteDatabase(":memory:")
    yield RelationalConversationRepository(database=database), database
    database.dispose()


# ============================================================
# BEGIN: Create / get / list semantics
# ============================================================


def test_create_produces_record(repository: tuple[RelationalConversationRepository, SqliteDatabase]) -> None:
    conversation_repository, _ = repository
    record = conversation_repository.create("c1", title="Hello")
    assert record.conversation_id == "c1"
    assert record.title == "Hello"
    assert record.created_at.tzinfo is not None
    assert record.updated_at.tzinfo is not None


def test_get_returns_created_record(repository: tuple[RelationalConversationRepository, SqliteDatabase]) -> None:
    conversation_repository, _ = repository
    created = conversation_repository.create("c1", title="Hello")
    stored = conversation_repository.get("c1")
    assert stored is not None
    assert stored == created


def test_get_unknown_conversation_is_none(repository: tuple[RelationalConversationRepository, SqliteDatabase]) -> None:
    conversation_repository, _ = repository
    assert conversation_repository.get("ghost") is None


def test_owner_scoped_reads_preserve_legacy_ownerless_records_as_inaccessible(
    repository: tuple[RelationalConversationRepository, SqliteDatabase],
) -> None:
    conversation_repository, _ = repository
    conversation_repository.create("legacy", title="Old conversation")
    conversation_repository.create(
        "alice", title="Private conversation", owner_principal_ref="principal-a", owner_tenant_ref="tenant-a"
    )
    conversation_repository.create(
        "bob", title="Other tenant", owner_principal_ref="principal-b", owner_tenant_ref="tenant-b"
    )

    assert conversation_repository.get_for_owner("legacy", "principal-a", "tenant-a") is None
    owned = conversation_repository.get_for_owner("alice", "principal-a", "tenant-a")
    assert owned is not None and owned.conversation_id == "alice"
    assert conversation_repository.get_for_owner("alice", "principal-a", "tenant-b") is None
    assert [item.conversation_id for item in conversation_repository.list_for_owner("principal-a", "tenant-a")] == [
        "alice"
    ]


def test_list_uses_canonical_activity_order(
    repository: tuple[RelationalConversationRepository, SqliteDatabase],
) -> None:
    conversation_repository, database = repository
    for conversation_id in ("a", "b", "c"):
        conversation_repository.create(conversation_id, title=f"T-{conversation_id}")
    # Assign distinct activity timestamps so the ordering assertion does not
    # depend on the host clock's resolution or SQLite's timestamp tie order.
    with database.connect() as connection:
        for conversation_id, updated_at in (
            ("a", "2026-01-01T00:00:00+00:00"),
            ("b", "2026-01-02T00:00:00+00:00"),
            ("c", "2026-01-03T00:00:00+00:00"),
        ):
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (updated_at, conversation_id),
            )
    assert [r.conversation_id for r in conversation_repository.list()] == ["c", "b", "a"]


def test_list_is_empty_when_no_conversations(
    repository: tuple[RelationalConversationRepository, SqliteDatabase],
) -> None:
    conversation_repository, _ = repository
    assert conversation_repository.list() == []


def test_duplicate_create_raises_value_error(
    repository: tuple[RelationalConversationRepository, SqliteDatabase],
) -> None:
    conversation_repository, _ = repository
    conversation_repository.create("c1", title="Hello")
    with pytest.raises(ValueError, match="Conversation already exists: c1"):
        conversation_repository.create("c1", title="Duplicate")


# ============================================================
# END: Create / get / list semantics
# ============================================================


# ============================================================
# BEGIN: Update semantics
# ============================================================


def test_update_title_refreshes_record(repository: tuple[RelationalConversationRepository, SqliteDatabase]) -> None:
    conversation_repository, _ = repository
    conversation_repository.create("c1", title="Hello")
    updated = conversation_repository.update_title("c1", "Renamed")
    assert updated is not None
    assert updated.title == "Renamed"
    assert updated.updated_at >= updated.created_at
    assert conversation_repository.get("c1") == updated


def test_update_title_unknown_conversation_is_none(
    repository: tuple[RelationalConversationRepository, SqliteDatabase],
) -> None:
    conversation_repository, _ = repository
    assert conversation_repository.update_title("ghost", "Renamed") is None


# ============================================================
# END: Update semantics
# ============================================================


# ============================================================
# BEGIN: Timestamps
# ============================================================


def test_timestamps_round_trip_as_aware_utc(
    repository: tuple[RelationalConversationRepository, SqliteDatabase],
) -> None:
    conversation_repository, _ = repository
    before = datetime.now(UTC)
    conversation_repository.create("c1", title="Hello")
    stored = conversation_repository.get("c1")
    assert stored is not None
    after = datetime.now(UTC)
    assert before <= stored.created_at <= after
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset().total_seconds() == 0
    assert stored.updated_at.tzinfo is not None


# ============================================================
# END: Timestamps
# ============================================================
