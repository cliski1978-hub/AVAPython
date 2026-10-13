from datetime import UTC, datetime

from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories.context_summary_repository import RelationalContextSummaryRepository
from ava.repositories.context_summary_repository import ConversationContextSummary


def _summary(version: int) -> ConversationContextSummary:
    return ConversationContextSummary(
        summary_id=f"summary-{version}",
        conversation_id="conversation-1",
        content=f"Summary version {version}",
        covers_through_message_id=f"message-{version}",
        covers_through_sequence=version * 10,
        source_token_count=100 * version,
        summary_token_count=10,
        model_id="model-1",
        provider_id="provider-1",
        version=version,
        created_at=datetime.now(UTC),
    )


def test_relational_repository_retains_versions_and_active_summary_after_reopen(tmp_path):
    path = tmp_path / "context-summaries.sqlite3"
    database = SqliteDatabase(str(path))
    repository = RelationalContextSummaryRepository(database=database)
    repository.save_version(_summary(1))
    repository.save_version(_summary(2))
    database.dispose()

    reopened = SqliteDatabase(str(path))
    try:
        repository = RelationalContextSummaryRepository(database=reopened)
        assert repository.get_active("conversation-1").summary_id == "summary-2"
        assert [summary.version for summary in repository.list_versions("conversation-1")] == [1, 2]
        assert repository.get_active("conversation-1").covers_through_sequence == 20
    finally:
        reopened.dispose()
