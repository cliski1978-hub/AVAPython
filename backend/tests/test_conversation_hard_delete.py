import sqlite3
from datetime import UTC, datetime
from io import BytesIO

import pytest

from ava.configuration.settings import Settings
from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.events import EventType, RunEvent
from ava.contracts.responses import RunStatus
from ava.infrastructure.composition import (
    create_application_persistence,
    create_conversation_hard_delete_coordinator,
)
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories.attachment_repository import RelationalAttachmentRepository
from ava.infrastructure.persistence.repositories.context_summary_repository import RelationalContextSummaryRepository
from ava.infrastructure.persistence.repositories.conversation_hard_delete_coordinator import (
    RelationalConversationHardDeleteCoordinator,
)
from ava.infrastructure.persistence.repositories.conversation_repository import RelationalConversationRepository
from ava.infrastructure.persistence.repositories.message_repository import RelationalMessageRepository
from ava.infrastructure.persistence.repositories.run_event_repository import RelationalRunEventRepository
from ava.infrastructure.persistence.repositories.run_repository import RelationalRunRepository
from ava.repositories.attachment_repository import AttachmentRecord
from ava.repositories.context_summary_repository import ConversationContextSummary
from ava.repositories.message_repository import MessageRecord
from ava.services.attachment_content_store import InMemoryAttachmentContentStore
from ava.services.attachment_store import InMemoryAttachmentRepository
from ava.services.context_summary_store import ContextSummaryStore
from ava.services.conversation_hard_delete_coordinator import InMemoryConversationHardDeleteCoordinator
from ava.services.conversation_service import ConversationHasActiveRunError, ConversationService
from ava.services.conversation_store import ConversationStore
from ava.services.message_store import MessageStore
from ava.services.run_event_store import RunEventStore
from ava.services.run_store import RunStore


class Harness:
    def __init__(self, backend: str, database_path: str | None = None) -> None:
        self.backend = backend
        self.database: SqliteDatabase | None = None
        self.content = InMemoryAttachmentContentStore()
        if backend == "memory":
            self.conversations = ConversationStore()
            self.messages = MessageStore()
            self.runs = RunStore()
            self.events = RunEventStore()
            self.attachments = InMemoryAttachmentRepository()
            self.summaries = ContextSummaryStore()
            coordinator = InMemoryConversationHardDeleteCoordinator(
                conversations=self.conversations,
                messages=self.messages,
                runs=self.runs,
                run_events=self.events,
                attachments=self.attachments,
                context_summaries=self.summaries,
            )
        else:
            self.database = SqliteDatabase(database_path or ":memory:")
            self.conversations = RelationalConversationRepository(database=self.database)
            self.messages = RelationalMessageRepository(database=self.database)
            self.runs = RelationalRunRepository(database=self.database)
            self.events = RelationalRunEventRepository(database=self.database)
            self.attachments = RelationalAttachmentRepository(database=self.database)
            self.summaries = RelationalContextSummaryRepository(database=self.database)
            coordinator = RelationalConversationHardDeleteCoordinator(database=self.database)
        self.service = ConversationService(
            conversation_repository=self.conversations,
            message_repository=self.messages,
            run_repository=self.runs,
            run_event_repository=self.events,
            hard_delete_coordinator=coordinator,
            attachment_content_store=self.content,
        )

    def add_message(self, conversation_id: str, message_id: str, *, source_run_id: str | None = None) -> None:
        now = datetime.now(UTC)
        self.messages.append(
            MessageRecord(
                message_id=message_id,
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content=f"{conversation_id}:{message_id}",
                status=MessageStatus.COMPLETE,
                created_at=now,
                updated_at=now,
                source_run_id=source_run_id,
            )
        )

    def add_attachment(self, attachment_id: str, key: str, owner_type: AttachmentOwnerType, owner_id: str) -> None:
        self.attachments.create(
            AttachmentRecord(
                attachment_id=attachment_id,
                file_name=f"{attachment_id}.txt",
                media_type="text/plain",
                size_bytes=4,
                storage_key=key,
                owner_type=owner_type,
                owner_id=owner_id,
                status=AttachmentStatus.AVAILABLE,
                created_at=datetime.now(UTC),
            )
        )
        self.content.put(key, BytesIO(b"blob"))


@pytest.mark.parametrize("persistence_provider", ["memory", "relational"])
def test_composition_selects_hard_delete_adapter_behind_port(
    persistence_provider: str,
    tmp_path,
) -> None:
    settings = Settings(
        persistence_provider=persistence_provider,
        persistence_database_url=str(tmp_path / "delete-composition.sqlite3"),
    )
    persistence = create_application_persistence(settings)
    try:
        coordinator = create_conversation_hard_delete_coordinator(persistence)
        if persistence_provider == "memory":
            assert isinstance(coordinator, InMemoryConversationHardDeleteCoordinator)
        else:
            assert isinstance(coordinator, RelationalConversationHardDeleteCoordinator)
    finally:
        persistence.dispose()


@pytest.mark.parametrize("backend", ["memory", "relational"])
def test_delete_removes_owned_graph_and_preserves_other_conversation(backend: str, tmp_path) -> None:
    harness = Harness(backend, str(tmp_path / "delete.sqlite") if backend == "relational" else None)
    conversations, messages, runs, events, attachments = (
        harness.conversations,
        harness.messages,
        harness.runs,
        harness.events,
        harness.attachments,
    )
    conversations.create("delete-me", title="Target")
    conversations.create("keep-me", title="Other")
    conversations.set_pinned("delete-me", True)
    conversations.set_archived("delete-me", True)
    if backend == "relational":
        with harness.database.connect() as connection:  # type: ignore[union-attr]
            connection.execute(
                "UPDATE conversations SET folder_id = 'future-folder' WHERE conversation_id = 'delete-me'"
            )
    harness.add_message("delete-me", "target-message")
    harness.add_message("keep-me", "other-message")
    now = datetime.now(UTC)
    harness.summaries.save_version(
        ConversationContextSummary(
            summary_id="target-summary",
            conversation_id="delete-me",
            content="target summary",
            covers_through_message_id="target-message",
            covers_through_sequence=0,
            source_token_count=20,
            summary_token_count=5,
            model_id="model",
            provider_id="provider",
            version=1,
            created_at=now,
        )
    )
    harness.summaries.save_version(
        ConversationContextSummary(
            summary_id="other-summary",
            conversation_id="keep-me",
            content="keep summary",
            covers_through_message_id="other-message",
            covers_through_sequence=0,
            source_token_count=20,
            summary_token_count=5,
            model_id="model",
            provider_id="provider",
            version=1,
            created_at=now,
        )
    )
    deleted_run = runs.create("target-run", conversation_id="delete-me", source_user_message_id="target-message")
    runs.update_status(deleted_run.run_id, RunStatus.COMPLETED)
    events.append(RunEvent(event_id="target-event", run_id="target-run", event_type=EventType.RUN_STARTED))
    legacy_run = runs.create("legacy-target-run", source_user_message_id="target-message")
    runs.update_status(legacy_run.run_id, RunStatus.COMPLETED)
    events.append(
        RunEvent(event_id="legacy-target-event", run_id="legacy-target-run", event_type=EventType.RUN_STARTED)
    )
    other_run = runs.create("other-run", conversation_id="keep-me", source_user_message_id="other-message")
    runs.update_status(other_run.run_id, RunStatus.COMPLETED)
    events.append(RunEvent(event_id="other-event", run_id="other-run", event_type=EventType.RUN_STARTED))
    harness.add_attachment(
        "target-conversation-attachment", "target/conversation", AttachmentOwnerType.CONVERSATION, "delete-me"
    )
    harness.add_attachment("target-message-attachment", "target/message", AttachmentOwnerType.MESSAGE, "target-message")
    harness.add_attachment("other-attachment", "other/conversation", AttachmentOwnerType.CONVERSATION, "keep-me")
    other_snapshot = (
        conversations.get("keep-me"),
        messages.list_for_conversation("keep-me"),
        runs.get("other-run"),
        events.get_events("other-run"),
        attachments.get("other-attachment"),
    )

    assert harness.service.delete_conversation("delete-me") is True
    assert harness.service.delete_conversation("delete-me") is False
    assert harness.service.delete_conversation("missing") is False
    assert conversations.get("delete-me") is None
    assert harness.summaries.get_active("delete-me") is None
    assert harness.summaries.get_active("keep-me").summary_id == "other-summary"
    assert messages.list_for_conversation("delete-me") == []
    assert runs.get("target-run") is None
    assert runs.get("legacy-target-run") is None
    assert list(events.get_events("target-run")) == []
    assert list(events.get_events("legacy-target-run")) == []
    assert attachments.get("target-conversation-attachment") is None
    assert attachments.get("target-message-attachment") is None
    assert not harness.content.exists("target/conversation")
    assert not harness.content.exists("target/message")
    assert harness.content.exists("other/conversation")
    assert (
        conversations.get("keep-me"),
        messages.list_for_conversation("keep-me"),
        runs.get("other-run"),
        events.get_events("other-run"),
        attachments.get("other-attachment"),
    ) == other_snapshot

    if harness.database is not None:
        with harness.database.connect() as connection:
            assert (
                connection.execute("SELECT count(*) FROM conversations WHERE conversation_id='delete-me'").fetchone()[0]
                == 0
            )
            assert (
                connection.execute("SELECT count(*) FROM messages WHERE conversation_id='delete-me'").fetchone()[0] == 0
            )
            assert connection.execute("SELECT count(*) FROM runs WHERE run_id='target-run'").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM run_events WHERE run_id='target-run'").fetchone()[0] == 0
            assert (
                connection.execute("SELECT count(*) FROM attachments WHERE attachment_id LIKE 'target-%'").fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM run_events e LEFT JOIN runs r ON r.run_id=e.run_id WHERE r.run_id IS NULL"
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM messages m LEFT JOIN runs r ON r.run_id=m.source_run_id "
                    "WHERE m.source_run_id IS NOT NULL AND r.run_id IS NULL"
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM attachments a WHERE a.owner_type = 'conversation' "
                    "AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.conversation_id = a.owner_id)"
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM attachments a WHERE a.owner_type = 'message' "
                    "AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.message_id = a.owner_id)"
                ).fetchone()[0]
                == 0
            )
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        harness.database.dispose()
        reopened = SqliteDatabase(harness.database.url)
        with reopened.connect() as connection:
            assert (
                connection.execute("SELECT count(*) FROM conversations WHERE conversation_id='delete-me'").fetchone()[0]
                == 0
            )
            assert (
                connection.execute("SELECT count(*) FROM conversations WHERE conversation_id='keep-me'").fetchone()[0]
                == 1
            )
        reopened.dispose()


@pytest.mark.parametrize("backend", ["memory", "relational"])
def test_active_run_rejects_delete_without_mutation(backend: str) -> None:
    harness = Harness(backend)
    harness.conversations.create("active", title="Active")
    harness.add_message("active", "active-message")
    harness.runs.create("active-run", conversation_id="active", source_user_message_id="active-message")
    harness.runs.create("active-legacy-run", source_user_message_id="active-message")
    harness.events.append(RunEvent(event_id="active-event", run_id="active-run", event_type=EventType.RUN_STARTED))
    harness.events.append(
        RunEvent(event_id="active-legacy-event", run_id="active-legacy-run", event_type=EventType.RUN_STARTED)
    )
    harness.add_attachment("active-attachment", "active/blob", AttachmentOwnerType.CONVERSATION, "active")
    with pytest.raises(ConversationHasActiveRunError) as error:
        harness.service.delete_conversation("active")
    assert set(error.value.run_ids) == {"active-run", "active-legacy-run"}
    assert harness.conversations.get("active") is not None
    assert len(harness.messages.list_for_conversation("active")) == 1
    assert harness.runs.get("active-run") is not None
    assert harness.runs.get("active-legacy-run") is not None
    assert len(harness.events.get_events("active-run")) == 1
    assert len(harness.events.get_events("active-legacy-run")) == 1
    assert harness.attachments.get("active-attachment") is not None
    assert harness.content.exists("active/blob")


def test_relational_failure_rolls_back_entire_delete(tmp_path) -> None:
    harness = Harness("relational", str(tmp_path / "rollback.sqlite"))
    harness.conversations.create("rollback", title="Rollback")
    harness.add_message("rollback", "rollback-message")
    harness.runs.create("rollback-run", conversation_id="rollback", source_user_message_id="rollback-message")
    harness.runs.update_status("rollback-run", RunStatus.COMPLETED)
    harness.events.append(RunEvent(event_id="rollback-event", run_id="rollback-run", event_type=EventType.RUN_STARTED))
    harness.add_attachment("rollback-attachment", "rollback/blob", AttachmentOwnerType.CONVERSATION, "rollback")
    with harness.database.connect() as connection:  # type: ignore[union-attr]
        connection.execute(
            "CREATE TRIGGER fail_conversation_delete BEFORE DELETE ON conversations "
            "BEGIN SELECT RAISE(ABORT, 'controlled failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="controlled failure"):
        harness.service.delete_conversation("rollback")
    assert harness.conversations.get("rollback") is not None
    assert len(harness.messages.list_for_conversation("rollback")) == 1
    assert harness.runs.get("rollback-run") is not None
    assert len(harness.events.get_events("rollback-run")) == 1
    assert harness.attachments.get("rollback-attachment") is not None
    assert harness.content.exists("rollback/blob")


def test_memory_delete_preserves_ambiguous_message_attachment() -> None:
    harness = Harness("memory")
    harness.conversations.create("one", title="One")
    harness.conversations.create("two", title="Two")
    harness.add_message("one", "same-id")
    harness.add_message("two", "same-id")
    harness.add_attachment("ambiguous", "shared/key", AttachmentOwnerType.MESSAGE, "same-id")
    assert harness.service.delete_conversation("one") is True
    retained = harness.attachments.get("ambiguous")
    assert retained is not None
    assert retained.owner_type is None and retained.owner_id is None
    assert harness.content.exists("shared/key")


@pytest.mark.parametrize("backend", ["memory", "relational"])
def test_delete_preserves_legacy_run_referenced_by_another_conversation(backend: str) -> None:
    harness = Harness(backend)
    harness.conversations.create("one", title="One")
    harness.conversations.create("two", title="Two")
    harness.add_message("one", "owner-message")
    shared_run = harness.runs.create("shared-run", source_user_message_id="owner-message")
    harness.runs.update_status(shared_run.run_id, RunStatus.COMPLETED)
    harness.events.append(RunEvent(event_id="shared-event", run_id="shared-run", event_type=EventType.RUN_STARTED))
    harness.add_message("two", "reference-message", source_run_id="shared-run")

    assert harness.service.delete_conversation("one") is True
    assert harness.runs.get("shared-run") is not None
    assert len(harness.events.get_events("shared-run")) == 1
    surviving_message = harness.messages.get("two", "reference-message")
    assert surviving_message is not None and surviving_message.source_run_id == "shared-run"
