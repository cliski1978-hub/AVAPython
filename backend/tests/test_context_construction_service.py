"""Phase 5.21 execution-context construction policy tests.

These tests pin the one policy that decides which durable messages a run may
send to a runtime: conversation-scoped, ordered by durable append order,
ending at the run's source user message, with regenerated answers collapsed
and only complete answers eligible.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ava.contracts.conversations import MessageRole, MessageStatus, RunContext
from ava.contracts.responses import RunStatus
from ava.repositories.message_repository import MessageRecord
from ava.services.context_construction_service import (
    ContextConstructionService,
    ContextConversationNotFoundError,
    ContextRunNotFoundError,
    ContextSourceMessageNotFoundError,
    ContextSourceMessageRoleError,
)
from ava.services.conversation_store import ConversationStore
from ava.services.message_store import MessageStore
from ava.services.run_store import RunStore

# ============================================================
# BEGIN: Graph Builder
# ============================================================


class Graph:
    """Minimal durable graph over the in-memory repository ports."""

    def __init__(self) -> None:
        self.runs = RunStore()
        self.messages = MessageStore()
        self.conversations = ConversationStore()
        self.service = ContextConstructionService(
            run_repository=self.runs,
            message_repository=self.messages,
            conversation_repository=self.conversations,
        )
        self._sequence = 0

    def conversation(self, conversation_id: str = "conversation-1") -> str:
        self.conversations.create(conversation_id, title="Graph")
        return conversation_id

    def message(
        self,
        conversation_id: str,
        role: MessageRole,
        content: str,
        *,
        status: MessageStatus = MessageStatus.COMPLETE,
        source_run_id: str | None = None,
    ) -> str:
        self._sequence += 1
        resolved = f"{conversation_id}-message-{self._sequence}"
        now = datetime.now(UTC)
        self.messages.append(
            MessageRecord(
                message_id=resolved,
                conversation_id=conversation_id,
                role=role,
                content=content,
                status=status,
                created_at=now,
                updated_at=now,
                source_run_id=source_run_id,
            )
        )
        return resolved

    def user(self, conversation_id: str, content: str) -> str:
        return self.message(conversation_id, MessageRole.USER, content)

    def assistant(
        self,
        conversation_id: str,
        content: str,
        run_status: RunStatus,
    ) -> tuple[str, str]:
        """Append a linked assistant message produced by a run."""
        self._sequence += 1
        run_id = f"run-{self._sequence}"
        self.runs.create(run_id)
        self.runs.update_status(run_id, run_status)
        message_id = self.message(
            conversation_id,
            MessageRole.ASSISTANT,
            content,
            status=MessageStatus.PENDING,
            source_run_id=run_id,
        )
        self.runs.set_assistant_message_id(run_id, message_id)
        return run_id, message_id

    def linked_run(
        self,
        conversation_id: str,
        source_user_message_id: str | None,
        *,
        assistant_message_id: str | None = None,
    ) -> str:
        """Create a run row linked to a conversation turn."""
        self._sequence += 1
        run_id = f"linked-run-{self._sequence}"
        self.runs.create(
            run_id,
            conversation_id=conversation_id,
            source_user_message_id=source_user_message_id,
        )
        if assistant_message_id is not None:
            self.runs.set_assistant_message_id(run_id, assistant_message_id)
        return run_id

    def texts(self, context: RunContext) -> list[str]:
        return [message.content for message in context.messages]


@pytest.fixture
def graph() -> Graph:
    return Graph()


# ============================================================
# END: Graph Builder
# ============================================================
# ============================================================
# BEGIN: Turn Coverage
# ============================================================


def test_first_turn_context_is_only_the_source_user_message(graph: Graph) -> None:
    conversation_id = graph.conversation()
    first = graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    second = graph.user(conversation_id, "U2")

    context = graph.service.build_for_source(conversation_id, second)

    assert graph.texts(context) == ["U1", "A1", "U2"]
    assert [message.role for message in context.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
    ]
    assert first in [message.message_id for message in context.messages]


def test_multi_turn_context_keeps_every_prior_turn_in_order(graph: Graph) -> None:
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    graph.user(conversation_id, "U2")
    graph.assistant(conversation_id, "A2", RunStatus.COMPLETED)
    third = graph.user(conversation_id, "U3")

    context = graph.service.build_for_source(conversation_id, third)

    assert graph.texts(context) == ["U1", "A1", "U2", "A2", "U3"]


def test_source_user_message_appears_exactly_once(graph: Graph) -> None:
    conversation_id = graph.conversation()
    source = graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    graph.assistant(conversation_id, "A2", RunStatus.COMPLETED)

    context = graph.service.build_for_source(conversation_id, source)

    assert graph.texts(context) == ["U1"]
    assert [message.message_id for message in context.messages] == [source]


def test_system_messages_are_preserved_in_order(graph: Graph) -> None:
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.message(conversation_id, MessageRole.SYSTEM, "S1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    second = graph.user(conversation_id, "U2")

    context = graph.service.build_for_source(conversation_id, second)

    assert graph.texts(context) == ["U1", "S1", "A1", "U2"]


# ============================================================
# END: Turn Coverage
# ============================================================
# ============================================================
# BEGIN: Visible Transcript Rule
# ============================================================


def test_regenerated_answers_collapse_to_the_latest(graph: Graph) -> None:
    conversation_id = graph.conversation()
    source = graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    graph.assistant(conversation_id, "A2", RunStatus.COMPLETED)
    graph.assistant(conversation_id, "A3", RunStatus.COMPLETED)

    context = graph.service.build_for_source(conversation_id, source)

    assert graph.texts(context) == ["U1"]


def test_visible_history_keeps_the_latest_answer_of_an_earlier_turn(graph: Graph) -> None:
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    graph.user(conversation_id, "U2")
    graph.assistant(conversation_id, "A2", RunStatus.COMPLETED)
    graph.assistant(conversation_id, "A3", RunStatus.COMPLETED)
    third = graph.user(conversation_id, "U3")

    context = graph.service.build_for_source(conversation_id, third)

    assert graph.texts(context) == ["U1", "A1", "U2", "A3", "U3"]


def test_collapse_is_positional_not_textual(graph: Graph) -> None:
    """Two different answers for one turn collapse by order, never by content."""
    conversation_id = graph.conversation()
    source = graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "second answer", RunStatus.COMPLETED)
    graph.assistant(conversation_id, "first answer", RunStatus.COMPLETED)
    graph.user(conversation_id, "U2")

    context = graph.service.build_for_source(conversation_id, source)

    assert graph.texts(context) == ["U1"]


def test_interleaved_answers_across_turns_do_not_collapse(graph: Graph) -> None:
    """Only consecutive assistant rows belong to the same turn."""
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    graph.user(conversation_id, "U2")
    graph.assistant(conversation_id, "A2", RunStatus.COMPLETED)
    third = graph.user(conversation_id, "U3")

    context = graph.service.build_for_source(conversation_id, third)

    assert graph.texts(context) == ["U1", "A1", "U2", "A2", "U3"]


# ============================================================
# END: Visible Transcript Rule
# ============================================================
# ============================================================
# BEGIN: Status Eligibility
# ============================================================


@pytest.mark.parametrize(
    "run_status",
    [RunStatus.PENDING, RunStatus.WAITING_FOR_APPROVAL, RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED],
)
def test_incomplete_answers_are_excluded(graph: Graph, run_status: RunStatus) -> None:
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "incomplete", run_status)
    second = graph.user(conversation_id, "U2")

    context = graph.service.build_for_source(conversation_id, second)

    assert graph.texts(context) == ["U1", "U2"]


def test_failed_latest_answer_does_not_resurrect_a_superseded_one(graph: Graph) -> None:
    """The collapsed answer is the latest; a failure is never replaced by an older one."""
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    graph.assistant(conversation_id, "A2", RunStatus.FAILED)
    second = graph.user(conversation_id, "U2")

    context = graph.service.build_for_source(conversation_id, second)

    assert graph.texts(context) == ["U1", "U2"]


def test_legacy_client_authored_answer_uses_its_own_status(graph: Graph) -> None:
    """A message with no run falls back to its stored status, not a default."""
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.message(
        conversation_id,
        MessageRole.ASSISTANT,
        "legacy answer",
        status=MessageStatus.COMPLETE,
    )
    graph.user(conversation_id, "U2")
    graph.message(
        conversation_id,
        MessageRole.ASSISTANT,
        "legacy failure",
        status=MessageStatus.FAILED,
    )
    third = graph.user(conversation_id, "U3")

    context = graph.service.build_for_source(conversation_id, third)

    assert graph.texts(context) == ["U1", "legacy answer", "U2", "U3"]


def test_legacy_client_authored_failure_alone_is_excluded(graph: Graph) -> None:
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.message(
        conversation_id,
        MessageRole.ASSISTANT,
        "legacy failure",
        status=MessageStatus.FAILED,
    )
    second = graph.user(conversation_id, "U2")

    assert graph.texts(graph.service.build_for_source(conversation_id, second)) == ["U1", "U2"]


def test_stored_placeholder_status_never_makes_a_linked_answer_complete(graph: Graph) -> None:
    """A linked answer's stored ``pending`` placeholder is not authoritative."""
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    _, assistant_id = graph.assistant(conversation_id, "A1", RunStatus.RUNNING)
    stored = graph.messages.get(conversation_id, assistant_id)
    assert stored is not None and stored.status == MessageStatus.PENDING
    second = graph.user(conversation_id, "U2")

    assert graph.texts(graph.service.build_for_source(conversation_id, second)) == ["U1", "U2"]


# ============================================================
# END: Status Eligibility
# ============================================================
# ============================================================
# BEGIN: Placeholder Exclusion
# ============================================================


def test_current_run_placeholder_is_excluded_even_when_inside_the_prefix(graph: Graph) -> None:
    """Defense in depth: a run's own assistant message is never its own context."""
    conversation_id = graph.conversation()
    source = graph.user(conversation_id, "U1")
    _, earlier = graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    run_id = graph.linked_run(conversation_id, source, assistant_message_id=earlier)

    context = graph.service.build_for_run(run_id)

    assert graph.texts(context) == ["U1"]


def test_run_context_identifies_the_durable_facts_it_came_from(graph: Graph) -> None:
    conversation_id = graph.conversation()
    source = graph.user(conversation_id, "U1")
    run_id = graph.linked_run(conversation_id, source)

    context = graph.service.build_for_run(run_id)

    assert context.conversation_id == conversation_id
    assert context.source_user_message_id == source
    assert context.has_messages is True


# ============================================================
# END: Placeholder Exclusion
# ============================================================
# ============================================================
# BEGIN: Conversation Boundary and Ordering
# ============================================================


def test_messages_from_another_conversation_are_never_included(graph: Graph) -> None:
    first = graph.conversation("conversation-1")
    second = graph.conversation("conversation-2")
    graph.user(first, "U1 first")
    graph.assistant(first, "A1 first", RunStatus.COMPLETED)
    graph.user(second, "U1 second")
    graph.assistant(second, "A1 second", RunStatus.COMPLETED)
    source = graph.user(first, "U2 first")

    context = graph.service.build_for_source(first, source)

    assert graph.texts(context) == ["U1 first", "A1 first", "U2 first"]


def test_context_is_deterministic_across_calls(graph: Graph) -> None:
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    source = graph.user(conversation_id, "U2")

    first = graph.service.build_for_source(conversation_id, source)
    second = graph.service.build_for_source(conversation_id, source)

    assert [message.model_dump() for message in first.messages] == [
        message.model_dump() for message in second.messages
    ]


def test_context_does_not_change_when_later_history_is_appended(graph: Graph) -> None:
    """Context for a turn is fixed by that turn, not by what came after it."""
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    source = graph.user(conversation_id, "U2")

    before = graph.texts(graph.service.build_for_source(conversation_id, source))
    graph.assistant(conversation_id, "A2", RunStatus.COMPLETED)
    after = graph.texts(graph.service.build_for_source(conversation_id, source))

    assert before == after == ["U1", "A1", "U2"]


# ============================================================
# END: Conversation Boundary and Ordering
# ============================================================
# ============================================================
# BEGIN: Legacy Compatibility
# ============================================================


def test_unlinked_run_has_no_durable_context(graph: Graph) -> None:
    run_id = graph.runs.create("legacy-run").run_id

    context = graph.service.build_for_run(run_id)

    assert context.messages == []
    assert context.has_messages is False


def test_linked_run_without_a_source_message_uses_the_visible_transcript(graph: Graph) -> None:
    """The legacy rule ends at the conversation's last user message.

    Nothing identifies which turn the run continues, so the visible transcript
    through the last user turn is used: the same history a reader sees before
    answering, and never a later answer that has no following question.
    """
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    graph.assistant(conversation_id, "A1", RunStatus.COMPLETED)
    graph.user(conversation_id, "U2")
    graph.assistant(conversation_id, "A2", RunStatus.COMPLETED)
    run_id = graph.linked_run(conversation_id, None)

    context = graph.service.build_for_run(run_id)

    assert graph.texts(context) == ["U1", "A1", "U2"]


def test_legacy_conversation_without_any_user_message_has_no_context(graph: Graph) -> None:
    conversation_id = graph.conversation()
    graph.assistant(conversation_id, "orphan answer", RunStatus.COMPLETED)
    run_id = graph.linked_run(conversation_id, None)

    assert graph.service.build_for_run(run_id).messages == []


# ============================================================
# END: Legacy Compatibility
# ============================================================
# ============================================================
# BEGIN: Deterministic Errors
# ============================================================


def test_unknown_run_is_rejected(graph: Graph) -> None:
    with pytest.raises(ContextRunNotFoundError):
        graph.service.build_for_run("missing-run")


def test_missing_conversation_is_rejected(graph: Graph) -> None:
    run_id = graph.linked_run("absent-conversation", "absent-message")

    with pytest.raises(ContextConversationNotFoundError):
        graph.service.build_for_run(run_id)


def test_missing_source_message_is_rejected(graph: Graph) -> None:
    conversation_id = graph.conversation()
    run_id = graph.linked_run(conversation_id, "never-appended")

    with pytest.raises(ContextSourceMessageNotFoundError):
        graph.service.build_for_run(run_id)


def test_source_message_from_another_conversation_is_rejected(graph: Graph) -> None:
    first = graph.conversation("conversation-1")
    second = graph.conversation("conversation-2")
    foreign = graph.user(second, "U1 second")
    run_id = graph.linked_run(first, foreign)

    with pytest.raises(ContextSourceMessageNotFoundError):
        graph.service.build_for_run(run_id)


def test_non_user_source_message_is_rejected(graph: Graph) -> None:
    conversation_id = graph.conversation()
    graph.user(conversation_id, "U1")
    assistant_id = graph.message(conversation_id, MessageRole.ASSISTANT, "A1")
    run_id = graph.linked_run(conversation_id, assistant_id)

    with pytest.raises(ContextSourceMessageRoleError):
        graph.service.build_for_run(run_id)


# ============================================================
# END: Deterministic Errors
# ============================================================
