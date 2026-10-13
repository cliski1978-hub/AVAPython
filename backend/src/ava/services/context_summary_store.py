"""In-memory implementation of the conversation summary repository."""

from dataclasses import replace

from ava.repositories.context_summary_repository import (
    ContextSummaryRepository,
    ConversationContextSummary,
)


class ContextSummaryStore(ContextSummaryRepository):
    def __init__(self) -> None:
        self._items: dict[str, list[ConversationContextSummary]] = {}

    def get_active(self, conversation_id: str) -> ConversationContextSummary | None:
        items = [row for row in self._items.get(conversation_id, ()) if not row.stale]
        return max(items, key=lambda row: row.version, default=None)

    def list_versions(self, conversation_id: str) -> list[ConversationContextSummary]:
        return sorted(self._items.get(conversation_id, ()), key=lambda row: row.version)

    def save_version(self, summary: ConversationContextSummary) -> ConversationContextSummary:
        items = self._items.setdefault(summary.conversation_id, [])
        if any(row.version == summary.version for row in items):
            raise ValueError("Conversation summary version already exists")
        items.append(summary)
        return summary

    def mark_stale(self, summary_id: str) -> None:
        for conversation_id, items in self._items.items():
            self._items[conversation_id] = [
                row if row.summary_id != summary_id else replace(row, stale=True) for row in items
            ]

    def delete_for_conversation(self, conversation_id: str) -> None:
        self._items.pop(conversation_id, None)
