"""Relational persistence durability tests (Step 4.6).

The adapter-level restart proof: writes performed through the five relational
adapters against a file-backed SQLite database survive ``dispose()`` and are
re-read after reopening the database with a fresh connection. A tightly paired
in-memory check shows the file is what carries the state.
"""

from datetime import UTC, datetime

from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.documents import ContentFormat
from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.models import ModelHostingMode
from ava.contracts.responses import RunStatus
from ava.infrastructure.persistence import SqliteDatabase, create_relational_repositories
from ava.repositories import MessageRecord

_EVENT_PAYLOAD: dict[str, object] = {"content": "durable ✓", "nested": {"seq": 7}}


def _write_full_state(repositories) -> None:
    repositories.run_repository.create("run-1")
    repositories.run_repository.update_status("run-1", RunStatus.RUNNING)
    repositories.run_repository.set_execution_selection(
        "run-1",
        RunExecutionSelection(
            runtime_id="native",
            model_provider_id="local",
            model_id="model-a",
            hosting_mode=ModelHostingMode.LOCAL,
        ),
    )
    repositories.run_event_repository.append(
        RunEvent(event_id="e1", run_id="run-1", event_type=EventType.RUN_STARTED, payload=_EVENT_PAYLOAD)
    )
    repositories.run_event_repository.append(
        RunEvent(event_id="e2", run_id="run-1", event_type=EventType.RUN_COMPLETED)
    )
    repositories.conversation_repository.create("conv-1", title="Durable")
    at = datetime.now(UTC)
    repositories.message_repository.append(
        MessageRecord(
            message_id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="<p>hi</p>",
            status=MessageStatus.COMPLETE,
            source_run_id="run-1",
            created_at=at,
            updated_at=at,
        )
    )
    repositories.document_repository.create(
        "doc-1",
        title="Notes",
        content="<p>Durable</p>",
        content_format=ContentFormat.HTML,
    )


def _assert_full_state(repositories) -> None:
    run = repositories.run_repository.get("run-1")
    assert run is not None
    assert run.status == RunStatus.RUNNING
    assert run.execution_selection == RunExecutionSelection(
        runtime_id="native",
        model_provider_id="local",
        model_id="model-a",
        hosting_mode=ModelHostingMode.LOCAL,
    )

    events = repositories.run_event_repository.get_events("run-1")
    assert [e.event_id for e in events] == ["e1", "e2"]
    assert events[0].payload == _EVENT_PAYLOAD
    assert events[1].event_type == EventType.RUN_COMPLETED
    assert repositories.run_event_repository.get_latest("run-1").event_type == EventType.RUN_COMPLETED

    conversations = repositories.conversation_repository.list()
    assert [c.conversation_id for c in conversations] == ["conv-1"]
    assert conversations[0].title == "Durable"

    messages = repositories.message_repository.list_for_conversation("conv-1")
    assert [m.message_id for m in messages] == ["msg-1"]
    assert messages[0].content == "<p>hi</p>"
    assert messages[0].source_run_id == "run-1"

    documents = repositories.document_repository.list()
    assert [d.document_id for d in documents] == ["doc-1"]
    assert documents[0].content == "<p>Durable</p>"
    assert documents[0].content_format == ContentFormat.HTML


def test_file_backed_state_survives_dispose_and_reopen(tmp_path) -> None:
    """Records written via the adapters survive a full database close/reopen."""
    database_url = str(tmp_path / "ava.sqlite3")
    first = create_relational_repositories(database_url)
    _write_full_state(first)
    first.dispose()

    second = create_relational_repositories(database_url)
    try:
        _assert_full_state(second)
    finally:
        second.dispose()


def test_memory_backed_state_does_not_survive_dispose() -> None:
    """The same write path against :memory: clears on dispose (control check)."""
    first = create_relational_repositories(":memory:")
    _write_full_state(first)
    first.dispose()

    second = create_relational_repositories(":memory:")
    try:
        assert second.run_repository.get("run-1") is None
        assert second.conversation_repository.list() == []
        assert second.document_repository.list() == []
    finally:
        second.dispose()


def test_reopened_schema_is_idempotent(tmp_path) -> None:
    """Reopening a populated database never errors on schema bootstrap."""
    database_url = str(tmp_path / "ava.sqlite3")
    first = SqliteDatabase(database_url)
    with first.connect() as connection:
        connection.execute(
            "INSERT INTO runs (run_id, status, created_at, updated_at) "
            "VALUES ('r1', 'pending', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    first.dispose()

    second = SqliteDatabase(database_url)
    with second.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert count == 1
    second.dispose()