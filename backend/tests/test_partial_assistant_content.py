"""Phase 5.27 durable partial assistant response tests."""

import asyncio
from datetime import UTC, datetime

import pytest

from ava.agents.contracts import AgentPort, AgentRunResult
from ava.contracts.capabilities import CapabilityName
from ava.contracts.conversations import MessageRole, MessageStatus, RunContext
from ava.contracts.events import EventType
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import (
    RelationalMessageRepository,
    RelationalRunEventRepository,
    RelationalRunRepository,
)
from ava.repositories.message_repository import MessageRecord
from ava.services.assistant_response_service import (
    AssistantContentOwnershipError,
    AssistantResponseService,
)
from ava.services.context_construction_service import ContextConstructionService
from ava.services.conversation_service import ConversationService
from ava.services.conversation_store import ConversationStore
from ava.services.message_store import MessageStore
from ava.services.run_event_store import RunEventStore
from ava.services.run_lifecycle_service import RunLifecycleService
from ava.services.run_service import RunService
from ava.services.run_store import RunStore


class _ControlledStreamingAgent(AgentPort):
    def __init__(self, outcome: RunStatus = RunStatus.COMPLETED) -> None:
        self.outcome = outcome
        self.partial_persisted = asyncio.Event()
        self.release = asyncio.Event()

    def name(self) -> str:
        return "controlled-stream"

    def get_capabilities(self) -> set[CapabilityName]:
        return {CapabilityName.RUNS}

    async def start_run(
        self, run_id: str, request: RunRequest, *, context: RunContext | None = None
    ) -> AgentRunResult:
        del run_id, request, context
        return AgentRunResult(status=self.outcome, content="こんにちは🙂")

    async def start_run_streaming(
        self,
        run_id: str,
        request: RunRequest,
        *,
        context: RunContext | None = None,
        on_content,
    ) -> AgentRunResult:
        del run_id, request, context
        on_content("")
        on_content("こん")
        on_content("こん")
        self.partial_persisted.set()
        await self.release.wait()
        if self.outcome == RunStatus.COMPLETED:
            on_content("こんにちは🙂")
            return AgentRunResult(status=self.outcome, content="こんにちは🙂")
        return AgentRunResult(status=self.outcome)

    async def cancel_run(self, run_id: str) -> RunResponse:
        self.outcome = RunStatus.CANCELLED
        self.release.set()
        return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)


def _linked_service(agent: AgentPort):
    runs, events, messages, conversations = RunStore(), RunEventStore(), MessageStore(), ConversationStore()
    conversations.create("conversation", title="Partial")
    now = datetime.now(UTC)
    messages.append(MessageRecord(
        message_id="user", conversation_id="conversation", role=MessageRole.USER,
        content="prompt", status=MessageStatus.COMPLETE, created_at=now, updated_at=now,
    ))
    context = ContextConstructionService(
        run_repository=runs,
        message_repository=messages,
        conversation_repository=conversations,
    )
    service = RunService(
        agent,
        run_repository=runs,
        run_event_repository=events,
        conversation_repository=conversations,
        message_repository=messages,
        context_service=context,
    )
    return service, runs, events, messages, conversations


def test_partial_snapshot_is_durable_while_running_and_reconciles_once() -> None:
    async def scenario() -> None:
        agent = _ControlledStreamingAgent()
        service, runs, events, messages, conversations = _linked_service(agent)
        task = asyncio.create_task(service.start_run(RunRequest(
            prompt="prompt", conversation_id="conversation", source_user_message_id="user",
        )))
        await agent.partial_persisted.wait()
        (run_id,) = runs.list_run_ids()
        active = service.get_run(run_id)
        assert active is not None and active.status == RunStatus.RUNNING
        assert active.assistant_message_id is not None
        partial = messages.get("conversation", active.assistant_message_id)
        assert partial is not None and partial.content == "こん"
        snapshot = ConversationService(
            conversation_repository=conversations,
            message_repository=messages,
            run_repository=runs,
        ).list_messages("conversation")
        assert snapshot is not None
        assistant = snapshot.messages[-1]
        assert assistant.content == "こん"
        assert assistant.status == MessageStatus.STREAMING
        partial_events = service.get_run_events(run_id)
        assert partial_events is not None
        assert [event.event_type for event in partial_events] == [
            EventType.RUN_STARTED, EventType.MESSAGE_STARTED, EventType.MESSAGE_CONTENT,
        ]
        assert partial_events[-1].payload == {
            "message_id": active.assistant_message_id, "content": "こん",
        }

        agent.release.set()
        completed = await task
        final = messages.get("conversation", completed.assistant_message_id or "")
        assert final is not None and final.content == "こんにちは🙂"
        content_events = [
            event for event in events.get_events(run_id)
            if event.event_type == EventType.MESSAGE_CONTENT
        ]
        assert [event.payload["content"] for event in content_events] == ["こん", "こんにちは🙂"]
        assert events.get_events(run_id)[-1].event_type == EventType.RUN_COMPLETED
        before = list(events.get_events(run_id))
        output = AssistantResponseService(
            run_repository=runs, run_event_repository=events, message_repository=messages,
        )
        assert output.record_snapshot(
            run_id=run_id, message_id=completed.assistant_message_id or "",
            conversation_id="conversation", content="late",
        ) is None
        assert messages.get("conversation", completed.assistant_message_id or "").content == "こんにちは🙂"
        assert events.get_events(run_id) == before

    asyncio.run(scenario())


def test_cancellation_request_mid_stream_preserves_partial_snapshot_and_exact_history() -> None:
    async def scenario() -> None:
        agent = _ControlledStreamingAgent()
        service, runs, events, messages, _ = _linked_service(agent)
        task = asyncio.create_task(service.start_run(RunRequest(
            prompt="prompt", conversation_id="conversation", source_user_message_id="user",
        )))
        await agent.partial_persisted.wait()
        (run_id,) = runs.list_run_ids()
        cancelled = await service.cancel_run(run_id)
        result = await task
        assert cancelled.status == result.status == RunStatus.CANCELLED
        assert result.assistant_message_id is not None
        assert messages.get("conversation", result.assistant_message_id).content == "こん"
        assert [event.event_type for event in events.get_events(run_id)] == [
            EventType.RUN_STARTED,
            EventType.MESSAGE_STARTED,
            EventType.MESSAGE_CONTENT,
            EventType.RUN_CANCEL_REQUESTED,
            EventType.RUN_CANCELLED,
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", [RunStatus.FAILED, RunStatus.CANCELLED])
def test_terminal_outcome_retains_partial_content_and_rejects_late_snapshot(outcome: RunStatus) -> None:
    async def scenario() -> None:
        agent = _ControlledStreamingAgent(outcome)
        service, runs, events, messages, _ = _linked_service(agent)
        task = asyncio.create_task(service.start_run(RunRequest(
            prompt="prompt", conversation_id="conversation", source_user_message_id="user",
        )))
        await agent.partial_persisted.wait()
        agent.release.set()
        result = await task
        assert result.status == outcome
        assert result.assistant_message_id is not None
        message = messages.get("conversation", result.assistant_message_id)
        assert message is not None and message.content == "こん"
        before = list(events.get_events(result.run_id))
        output = AssistantResponseService(
            run_repository=runs, run_event_repository=events, message_repository=messages,
        )
        assert output.record_snapshot(
            run_id=result.run_id, message_id=result.assistant_message_id,
            conversation_id="conversation", content="late",
        ) is None
        assert messages.get("conversation", result.assistant_message_id).content == "こん"
        assert events.get_events(result.run_id) == before

    asyncio.run(scenario())


def test_content_writer_rejects_cross_run_message_ownership() -> None:
    service, runs, events, messages, _ = _linked_service(_ControlledStreamingAgent())
    del service
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    lifecycle.create_run("other", conversation_id="conversation", source_user_message_id="user")
    runs.set_assistant_message_id("other", "not-owned")
    lifecycle.start("other")
    output = AssistantResponseService(
        run_repository=runs, run_event_repository=events, message_repository=messages,
    )
    with pytest.raises(AssistantContentOwnershipError):
        output.record_snapshot(
            run_id="other", message_id="different", conversation_id="conversation", content="x",
        )


def test_partial_message_and_replay_survive_database_restart(tmp_path) -> None:
    path = str(tmp_path / "partial.sqlite3")
    database = SqliteDatabase(path)
    runs = RelationalRunRepository(database=database)
    events = RelationalRunEventRepository(database=database)
    messages = RelationalMessageRepository(database=database)
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    lifecycle.create_run("run", conversation_id="conversation", source_user_message_id="user")
    runs.set_assistant_message_id("run", "assistant")
    now = datetime.now(UTC)
    messages.append(MessageRecord(
        message_id="assistant", conversation_id="conversation", role=MessageRole.ASSISTANT,
        content="", status=MessageStatus.PENDING, source_run_id="run",
        created_at=now, updated_at=now,
    ))
    lifecycle.start("run")
    output = AssistantResponseService(
        run_repository=runs, run_event_repository=events, message_repository=messages,
    )
    output.start_message("run", "assistant")
    output.record_snapshot(
        run_id="run", message_id="assistant", conversation_id="conversation", content="Hello wor",
    )
    expected = list(events.get_events("run"))
    database.dispose()

    reopened = SqliteDatabase(path)
    reopened_runs = RelationalRunRepository(database=reopened)
    reopened_events = RelationalRunEventRepository(database=reopened)
    reopened_messages = RelationalMessageRepository(database=reopened)
    assert reopened_runs.get("run").status == RunStatus.RUNNING
    assert reopened_messages.get("conversation", "assistant").content == "Hello wor"
    assert reopened_events.list_after_sequence("run", 0) == expected
    reopened.dispose()
