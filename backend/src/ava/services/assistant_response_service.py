"""Durable assistant-content authority for active AVA runs.

The assistant message owns the current content snapshot. ``message_content``
events are ordered facts describing that same progression. This module is the
single write path for both streaming updates and final-response reconciliation.
"""

from uuid import uuid4

from ava.contracts.conversations import MessageRole
from ava.contracts.events import EventType, RunEvent
from ava.repositories.message_repository import MessageRepository
from ava.repositories.run_event_repository import RunEventRepository
from ava.repositories.run_repository import RunRepository


class AssistantContentOwnershipError(ValueError):
    """A run attempted to write content to an assistant message it does not own."""


class AssistantResponseService:
    """Persist assistant snapshots and their matching ordered event facts."""

    def __init__(
        self,
        *,
        run_repository: RunRepository,
        run_event_repository: RunEventRepository,
        message_repository: MessageRepository | None,
    ) -> None:
        self._runs = run_repository
        self._events = run_event_repository
        self._messages = message_repository

    def start_message(self, run_id: str, message_id: str) -> RunEvent:
        """Record which stable assistant message this run is producing."""
        return self._events.append(
            RunEvent(
                event_id=str(uuid4()),
                run_id=run_id,
                event_type=EventType.MESSAGE_STARTED,
                payload={"message_id": message_id, "role": "assistant"},
            )
        )

    def record_snapshot(
        self,
        *,
        run_id: str,
        message_id: str,
        conversation_id: str | None,
        content: str,
    ) -> RunEvent | None:
        """Persist one non-empty, changed full-content snapshot while active.

        The message write happens before the event append. A crash may therefore
        leave newer message content without its matching fact, but replay never
        claims content that the durable message snapshot does not contain.
        """
        if content == "":
            return None
        run = self._runs.get(run_id)
        if run is None or not run.status.is_active:
            return None
        if run.assistant_message_id is not None:
            if message_id != run.assistant_message_id or conversation_id is None:
                raise AssistantContentOwnershipError(
                    f"Run {run_id!r} does not own assistant message {message_id!r}"
                )
            if self._messages is None:
                raise AssistantContentOwnershipError("Durable assistant message repository is unavailable")
            message = self._messages.get(conversation_id, message_id)
            if (
                message is None
                or message.role != MessageRole.ASSISTANT
                or message.source_run_id != run_id
            ):
                raise AssistantContentOwnershipError(
                    f"Assistant message {message_id!r} is not linked to run {run_id!r}"
                )
            if message.content == content:
                return None
            updated = self._messages.update_content(conversation_id, message_id, content)
            if updated is None:
                raise AssistantContentOwnershipError(
                    f"Assistant message {message_id!r} could not be updated"
                )
        else:
            latest = self._latest_content(message_id, run_id)
            if latest == content:
                return None
        return self._events.append(
            RunEvent(
                event_id=str(uuid4()),
                run_id=run_id,
                event_type=EventType.MESSAGE_CONTENT,
                payload={"message_id": message_id, "content": content},
            )
        )

    def _latest_content(self, message_id: str, run_id: str) -> str | None:
        for event in reversed(list(self._events.get_events(run_id))):
            if event.event_type == EventType.MESSAGE_CONTENT:
                event_message_id = event.payload.get("message_id")
                content = event.payload.get("content")
                if event_message_id == message_id and isinstance(content, str):
                    return content
        return None
