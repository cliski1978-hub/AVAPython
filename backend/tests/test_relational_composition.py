"""Relational persistence composition tests (Step 4.6).

Verify the optional infrastructure composition seam:
``create_relational_repositories`` builds the activated adapters — run, run,
event, conversation, message, document, and document revision — plus the
document write coordinator over one shared ``SqliteDatabase``, each adapter
conforms to its port, and the set owns a ``dispose()`` lifecycle.
"""

from ava.contracts.events import EventType, RunEvent
from ava.infrastructure.persistence import PersistenceRepositories, create_relational_repositories
from ava.repositories import (
    AttachmentRepository,
    ConversationRepository,
    DocumentRepository,
    DocumentRevisionRepository,
    MessageRepository,
    RunEventRepository,
    RunRepository,
)


def test_factory_builds_all_five_adapters() -> None:
    repositories = create_relational_repositories(":memory:")
    try:
        assert isinstance(repositories, PersistenceRepositories)
        assert isinstance(repositories.run_repository, RunRepository)
        assert isinstance(repositories.run_event_repository, RunEventRepository)
        assert isinstance(repositories.conversation_repository, ConversationRepository)
        assert isinstance(repositories.message_repository, MessageRepository)
        assert isinstance(repositories.document_repository, DocumentRepository)
        assert isinstance(repositories.attachment_repository, AttachmentRepository)
    finally:
        repositories.dispose()


def test_adapters_share_a_single_database_instance() -> None:
    repositories = create_relational_repositories(":memory:")
    try:
        shared = repositories.database
        assert repositories.run_repository._database is shared
        assert repositories.run_event_repository._database is shared
        assert repositories.conversation_repository._database is shared
        assert repositories.message_repository._database is shared
        assert repositories.document_repository._database is shared
        assert repositories.document_revision_repository._database is shared
        assert repositories.attachment_repository._database is shared
        assert repositories.document_write_coordinator._database is shared
    finally:
        repositories.dispose()


def test_factory_builds_the_revision_adapters_and_coordinator() -> None:
    repositories = create_relational_repositories(":memory:")
    try:
        assert isinstance(repositories.document_revision_repository, DocumentRevisionRepository)
        coordinator = repositories.document_write_coordinator
        assert coordinator._database is repositories.database
        assert coordinator._document_repository is repositories.document_repository
        assert coordinator._revision_repository is repositories.document_revision_repository
    finally:
        repositories.dispose()


def test_composed_set_round_trips_through_its_ports() -> None:
    repositories = create_relational_repositories(":memory:")
    try:
        run = repositories.run_repository.create("run-1")
        assert repositories.run_repository.get("run-1") == run
        repositories.run_event_repository.append(
            RunEvent(event_id="e1", run_id="run-1", event_type=EventType.RUN_COMPLETED)
        )
        assert repositories.run_event_repository.get_latest("run-1").event_id == "e1"
        conversations = repositories.conversation_repository.create("c1", title="Hello")
        assert repositories.conversation_repository.list() == [conversations]
    finally:
        repositories.dispose()


def test_dispose_closes_the_shared_database() -> None:
    repositories = create_relational_repositories(":memory:")
    repositories.run_repository.create("run-1")
    repositories.dispose()
    # Dispose is idempotent and safe to call again.
    repositories.dispose()


def test_database_url_is_surfaces_on_the_set() -> None:
    repositories = create_relational_repositories(":memory:")
    try:
        assert repositories.database.url == ":memory:"
    finally:
        repositories.dispose()