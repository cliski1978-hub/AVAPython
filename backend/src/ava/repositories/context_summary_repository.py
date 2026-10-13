"""Persistence port for AVA-owned rolling conversation summaries."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConversationContextSummary:
    summary_id: str
    conversation_id: str
    content: str
    covers_through_message_id: str
    covers_through_sequence: int
    source_token_count: int
    summary_token_count: int
    model_id: str
    provider_id: str
    version: int
    created_at: datetime
    stale: bool = False


class ContextSummaryRepository(ABC):
    @abstractmethod
    def get_active(self, conversation_id: str) -> ConversationContextSummary | None: ...

    @abstractmethod
    def list_versions(self, conversation_id: str) -> list[ConversationContextSummary]: ...

    @abstractmethod
    def save_version(self, summary: ConversationContextSummary) -> ConversationContextSummary: ...

    @abstractmethod
    def mark_stale(self, summary_id: str) -> None: ...

    @abstractmethod
    def delete_for_conversation(self, conversation_id: str) -> None: ...
