"""Shared behavioral contract suite: in-memory stores vs relational adapters.

Step 4.6's relational adapters must be indistinguishable from the in-memory
stores except for durability. This suite runs the same representative
semantics against both implementations through the repository ports, so any
semantic drift becomes visible at the port level.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.documents import ContentFormat
from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.models import ModelHostingMode
from ava.contracts.responses import RunStatus
from ava.infrastructure.persistence import create_relational_repositories
from ava.repositories import (
    ConversationRepository,
    DocumentRepository,
    MessageRecord,
    MessageRepository,
    RunEventRepository,
    RunRepository,
)
from ava.services.conversation_store import ConversationStore
from ava.services.document_store import DocumentStore
from ava.services.message_store import MessageStore
from ava.services.run_event_store import RunEventStore
from ava.services.run_store import RunStore

_IMPL_IDENTIFIERS = ["in-memory", "relational"]


@dataclass(frozen=True)
class RepositorySetup:
    """All five repository ports plus a shared dispose lifecycle."""

    runs: RunRepository
    events: RunEventRepository
    conversations: ConversationRepository
    messages: MessageRepository
    documents: DocumentRepository
    dispose: Callable[[], None]


def _memory_setup() -> RepositorySetup:
    return RepositorySetup(
        runs=RunStore(),
        events=RunEventStore(),
        conversations=ConversationStore(),
        messages=MessageStore(),
        documents=DocumentStore(),
        dispose=lambda: None,
    )


def _relational_setup() -> RepositorySetup:
    repositories = create_relational_repositories(":memory:")
    return RepositorySetup(
        runs=repositories.run_repository,
        events=repositories.run_event_repository,
        conversations=repositories.conversation_repository,
        messages=repositories.message_repository,
        documents=repositories.document_repository,
        dispose=repositories.dispose,
    )


@pytest.fixture(params=_IMPL_IDENTIFIERS)
def repositories(request: pytest.FixtureRequest) -> RepositorySetup:
    """Parameterize every shared test over both repository implementations."""
    setup = _memory_setup() if request.param == "in-memory" else _relational_setup()
    yield setup
    setup.dispose()


# ============================================================
# BEGIN: Run semantics
# ============================================================


def test_run_create_and_duplicate_rejection(repositories: RepositorySetup) -> None:
    record = repositories.runs.create("run-1")
    assert record.run_id == "run-1"
    assert record.status == RunStatus.PENDING
    assert repositories.runs.get("run-1") == record
    with pytest.raises(ValueError, match="Run already exists: run-1"):
        repositories.runs.create("run-1")


def test_run_status_lifecycle_and_unknown_results(repositories: RepositorySetup) -> None:
    repositories.runs.create("run-1")
    updated = repositories.runs.update_status("run-1", RunStatus.COMPLETED)
    assert updated is not None
    assert updated.status == RunStatus.COMPLETED
    assert updated.updated_at >= updated.created_at
    assert repositories.runs.get("run-1") == updated
    assert repositories.runs.update_status("ghost", RunStatus.FAILED) is None
    assert repositories.runs.get("ghost") is None


def test_run_execution_selection_round_trip(repositories: RepositorySetup) -> None:
    repositories.runs.create("run-1")
    selection = RunExecutionSelection(
        runtime_id="native",
        model_provider_id="local",
        model_id="model-a",
        hosting_mode=ModelHostingMode.LOCAL,
    )
    updated = repositories.runs.set_execution_selection("run-1", selection)
    assert updated is not None
    assert updated.execution_selection == selection
    assert repositories.runs.get("run-1").execution_selection == selection
    cleared = repositories.runs.set_execution_selection("run-1", None)
    assert cleared is not None
    assert cleared.execution_selection is None
    assert repositories.runs.set_execution_selection("ghost", selection) is None


# ============================================================
# END: Run semantics
# ============================================================


# ============================================================
# BEGIN: Run-event semantics
# ============================================================


def test_event_append_order_and_latest(repositories: RepositorySetup) -> None:
    for event_id, event_type in (
        ("e1", EventType.RUN_STARTED),
        ("e2", EventType.MESSAGE_STARTED),
        ("e3", EventType.RUN_COMPLETED),
    ):
        repositories.events.append(RunEvent(event_id=event_id, run_id="r", event_type=event_type))
    assert [e.event_id for e in repositories.events.get_events("r")] == ["e1", "e2", "e3"]
    assert repositories.events.get_latest("r").event_id == "e3"
    assert repositories.events.get_events("ghost") == []
    assert repositories.events.get_latest("ghost") is None


def test_event_terminal_sealing_is_idempotent(repositories: RepositorySetup) -> None:
    repositories.events.append(RunEvent(event_id="e1", run_id="r", event_type=EventType.RUN_STARTED))
    repositories.events.append(RunEvent(event_id="e2", run_id="r", event_type=EventType.RUN_COMPLETED))
    repositories.events.append(RunEvent(event_id="e3", run_id="r", event_type=EventType.RUN_FAILED))
    assert [e.event_id for e in repositories.events.get_events("r")] == ["e1", "e2"]
    assert repositories.events.get_latest("r").event_type == EventType.RUN_COMPLETED


def test_event_payload_and_timestamp_round_trip(repositories: RepositorySetup) -> None:
    payload = {"content": "héllo ✓", "nested": {"flag": True}}
    event = RunEvent(event_id="e1", run_id="r", event_type=EventType.MESSAGE_CONTENT, payload=payload)
    repositories.events.append(event)
    restored = repositories.events.get_events("r")[0]
    assert restored == event
    assert restored.payload == payload
    assert restored.timestamp == event.timestamp


def test_events_are_isolated_per_run(repositories: RepositorySetup) -> None:
    repositories.events.append(RunEvent(event_id="e1", run_id="a", event_type=EventType.RUN_STARTED))
    repositories.events.append(RunEvent(event_id="e2", run_id="b", event_type=EventType.RUN_STARTED))
    assert [e.event_id for e in repositories.events.get_events("a")] == ["e1"]
    assert [e.event_id for e in repositories.events.get_events("b")] == ["e2"]


# ============================================================
# END: Run-event semantics
# ============================================================


# ============================================================
# BEGIN: Conversation semantics
# ============================================================


def test_conversation_create_list_order_and_duplicate(repositories: RepositorySetup) -> None:
    repositories.conversations.create("c1", title="First")
    repositories.conversations.create("c2", title="Second")
    assert [c.conversation_id for c in repositories.conversations.list()] == ["c1", "c2"]
    assert repositories.conversations.get("c1").title == "First"
    assert repositories.conversations.get("ghost") is None
    with pytest.raises(ValueError, match="Conversation already exists: c2"):
        repositories.conversations.create("c2", title="Duplicate")


def test_conversation_rename_and_unknown(repositories: RepositorySetup) -> None:
    repositories.conversations.create("c1", title="First")
    renamed = repositories.conversations.update_title("c1", "Renamed")
    assert renamed is not None
    assert renamed.title == "Renamed"
    assert renamed.updated_at >= renamed.created_at
    assert repositories.conversations.get("c1") == renamed
    assert repositories.conversations.update_title("ghost", "Renamed") is None


# ============================================================
# END: Conversation semantics
# ============================================================


# ============================================================
# BEGIN: Message semantics
# ============================================================


def _message(message_id: str, conversation_id: str, **kwargs: object) -> MessageRecord:
    defaults: dict[str, object] = {
        "role": MessageRole.USER,
        "content": "hi",
        "status": MessageStatus.COMPLETE,
        "source_run_id": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return MessageRecord(message_id=message_id, conversation_id=conversation_id, **defaults)


def test_message_append_order_isolation_and_scoped_get(repositories: RepositorySetup) -> None:
    repositories.messages.append(_message("shared", "c1"))
    repositories.messages.append(_message("shared", "c2"))
    repositories.messages.append(_message("m2", "c1"))
    assert [m.message_id for m in repositories.messages.list_for_conversation("c1")] == ["shared", "m2"]
    assert [m.message_id for m in repositories.messages.list_for_conversation("c2")] == ["shared"]
    assert repositories.messages.get("c1", "shared") is not None
    assert repositories.messages.get("ghost", "shared") is None
    assert repositories.messages.list_for_conversation("ghost") == []


def test_message_duplicate_rejection_and_verbatim_storage(repositories: RepositorySetup) -> None:
    repositories.messages.append(_message("m1", "c1"))
    with pytest.raises(ValueError, match="Message already exists: m1"):
        repositories.messages.append(_message("m1", "c1", content="duplicate"))
    stored = repositories.messages.get("c1", "m1")
    assert stored is not None
    assert stored.content == "hi"


# ============================================================
# END: Message semantics
# ============================================================


# ============================================================
# BEGIN: Document semantics
# ============================================================


def test_document_create_list_order_and_duplicate(repositories: RepositorySetup) -> None:
    repositories.documents.create(
        "d1", title="First", content="<p>1</p>", content_format=ContentFormat.HTML
    )
    repositories.documents.create(
        "d2", title="Second", content="<p>2</p>", content_format=ContentFormat.HTML
    )
    assert [d.document_id for d in repositories.documents.list()] == ["d1", "d2"]
    assert repositories.documents.get("d1").title == "First"
    assert repositories.documents.get("ghost") is None
    with pytest.raises(ValueError, match="Document already exists: d2"):
        repositories.documents.create(
            "d2", title="Duplicate", content="<p>x</p>", content_format=ContentFormat.HTML
        )


def test_document_title_and_content_updates(repositories: RepositorySetup) -> None:
    repositories.documents.create(
        "d1", title="First", content="<p>1</p>", content_format=ContentFormat.HTML
    )
    renamed = repositories.documents.update_title("d1", "Renamed")
    assert renamed is not None
    assert renamed.title == "Renamed"
    replaced = repositories.documents.update_content(
        "d1", content="<p>2</p>", content_format=ContentFormat.HTML
    )
    assert replaced is not None
    assert replaced.content == "<p>2</p>"
    assert replaced.content_format == ContentFormat.HTML
    assert replaced.updated_at >= replaced.created_at
    assert repositories.documents.get("d1") == replaced
    assert repositories.documents.update_title("ghost", "Renamed") is None
    assert repositories.documents.update_content("ghost", content="<p>x</p>", content_format=ContentFormat.HTML) is None


# ============================================================
# END: Document semantics
# ============================================================


# ============================================================
# BEGIN: Timestamps
# ============================================================


def test_all_timestamps_round_trip_as_aware_utc(repositories: RepositorySetup) -> None:
    repositories.runs.create("run-1")
    repositories.conversations.create("c1", title="First")
    repositories.documents.create(
        "d1", title="First", content="<p>1</p>", content_format=ContentFormat.HTML
    )
    at = datetime.now(UTC)
    repositories.messages.append(
        MessageRecord("m1", "c1", MessageRole.USER, "hi", MessageStatus.COMPLETE, at, at)
    )

    assert repositories.runs.get("run-1").created_at.tzinfo is not None
    assert repositories.conversations.get("c1").created_at.tzinfo is not None
    assert repositories.documents.get("d1").created_at.tzinfo is not None
    assert repositories.messages.get("c1", "m1").created_at.tzinfo is not None


# ============================================================
# END: Timestamps
# ============================================================