"""AVA conversation/message repository port contract tests (Step 4.4).

Prove the conversation and message repository ports are:

* implementable by framework-free in-memory implementations;
* typed entirely with AVA-owned (or stdlib) domain/contract types;
* implemented by the existing in-memory ``ConversationStore`` / ``MessageStore``
  adapters, which Step 4.4 makes explicit subclasses of the ports;
* free of database, provider, and framework concepts.

No database is introduced or exercised here.
"""

import sys
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import get_args, get_type_hints

import pytest

from ava.contracts.conversations import MessageRole, MessageStatus
from ava.repositories import (
    ConversationRecord,
    ConversationRepository,
    MessageRecord,
    MessageRepository,
)
from ava.services.conversation_store import ConversationStore
from ava.services.message_store import MessageStore

# ============================================================
# BEGIN: In-memory port implementations (test fakes)
# ============================================================


class MemoryConversationRepository(ConversationRepository):
    """Framework-free in-memory implementation used to prove the port shape."""

    def __init__(self) -> None:
        self._conversations: dict[str, ConversationRecord] = {}

    def create(self, conversation_id: str, *, title: str) -> ConversationRecord:
        if conversation_id in self._conversations:
            raise ValueError(f"Conversation already exists: {conversation_id}")
        now = datetime.now(UTC)
        record = ConversationRecord(
            conversation_id=conversation_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self._conversations[conversation_id] = record
        return record

    def get(self, conversation_id: str) -> ConversationRecord | None:
        return self._conversations.get(conversation_id)

    def list(self, search: str | None = None) -> list[ConversationRecord]:
        records = list(self._conversations.values())
        records.sort(key=lambda record: record.conversation_id)
        records.sort(
            key=lambda record: (record.is_pinned, record.updated_at, record.created_at),
            reverse=True,
        )
        if search is None or not search.strip():
            return records
        needle = search.strip().lower()
        return [record for record in records if needle in record.title.lower()]

    def set_pinned(self, conversation_id: str, is_pinned: bool) -> ConversationRecord | None:
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, is_pinned=is_pinned)
        self._conversations[conversation_id] = updated
        return updated

    def set_archived(self, conversation_id: str, is_archived: bool) -> ConversationRecord | None:
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, is_archived=is_archived)
        self._conversations[conversation_id] = updated
        return updated

    def set_folder(self, conversation_id: str, folder_id: str | None) -> ConversationRecord | None:
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, folder_id=folder_id)
        self._conversations[conversation_id] = updated
        return updated

    def set_project(self, conversation_id: str, project_id: str | None) -> ConversationRecord | None:
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, project_id=project_id)
        self._conversations[conversation_id] = updated
        return updated

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord | None:
        record = self._conversations.get(conversation_id)
        if record is None:
            return None
        updated = replace(record, title=title, updated_at=datetime.now(UTC))
        self._conversations[conversation_id] = updated
        return updated


class MemoryMessageRepository(MessageRepository):
    """Framework-free in-memory implementation used to prove the port shape."""

    def __init__(self) -> None:
        self._messages: dict[str, dict[str, MessageRecord]] = {}

    def append(self, message: MessageRecord) -> MessageRecord:
        messages = self._messages.setdefault(message.conversation_id, {})
        if message.message_id in messages:
            raise ValueError(f"Message already exists: {message.message_id}")
        messages[message.message_id] = message
        return message

    def get(self, conversation_id: str, message_id: str) -> MessageRecord | None:
        return self._messages.get(conversation_id, {}).get(message_id)

    def list_for_conversation(self, conversation_id: str) -> list[MessageRecord]:
        return list(self._messages.get(conversation_id, {}).values())


# ============================================================
# END: In-memory port implementations (test fakes)
# ============================================================


# ============================================================
# BEGIN: Port implementability
# ============================================================


def test_conversation_repository_is_an_abstract_contract() -> None:
    """The port is a contract, not a usable default implementation."""
    with pytest.raises(TypeError):
        ConversationRepository()  # type: ignore[abstract]


def test_message_repository_is_an_abstract_contract() -> None:
    with pytest.raises(TypeError):
        MessageRepository()  # type: ignore[abstract]


def test_conversation_repository_is_implementable_by_in_memory_fake() -> None:
    repo = MemoryConversationRepository()

    created = repo.create("conv-1", title="First")
    assert isinstance(repo, ConversationRepository)
    assert created.conversation_id == "conv-1"
    assert created.title == "First"
    assert created.created_at == created.updated_at

    with pytest.raises(ValueError):
        repo.create("conv-1", title="Duplicate")

    renamed = repo.update_title("conv-1", "Renamed")
    assert renamed is not None
    assert renamed.title == "Renamed"
    assert renamed.updated_at >= renamed.created_at

    repo.create("conv-2", title="Second")
    assert [c.conversation_id for c in repo.list()] == ["conv-2", "conv-1"]

    assert repo.get("ghost") is None
    assert repo.update_title("ghost", "x") is None


def test_message_repository_is_implementable_by_in_memory_fake() -> None:
    repo = MemoryMessageRepository()
    now = datetime.now(UTC)

    record = MessageRecord(
        message_id="m1",
        conversation_id="conv-1",
        role=MessageRole.USER,
        content="Hello",
        status=MessageStatus.COMPLETE,
        source_run_id="run-1",
        created_at=now,
        updated_at=now,
    )
    assert repo.append(record) is record

    with pytest.raises(ValueError):
        repo.append(record)

    other = MessageRecord(
        message_id="m2",
        conversation_id="conv-1",
        role=MessageRole.ASSISTANT,
        content="Hi",
        status=MessageStatus.COMPLETE,
        created_at=now,
        updated_at=now,
    )
    repo.append(other)

    assert [m.message_id for m in repo.list_for_conversation("conv-1")] == ["m1", "m2"]
    assert repo.list_for_conversation("unknown") == []
    assert repo.get("conv-1", "m1") is record
    assert repo.get("other-conv", "m1") is None


# ============================================================
# END: Port implementability
# ============================================================


# ============================================================
# BEGIN: Record identity and semantics
# ============================================================


def test_conversation_records_are_frozen_ava_owned_snapshots() -> None:
    now = datetime.now(UTC)
    record = ConversationRecord(
        conversation_id="conv-9", title="T", created_at=now, updated_at=now
    )

    assert record.created_at == now
    assert record.updated_at == now

    with pytest.raises(FrozenInstanceError):
        record.title = "Nope"  # type: ignore[misc]


def test_message_records_are_frozen_ava_owned_snapshots() -> None:
    now = datetime.now(UTC)
    record = MessageRecord(
        message_id="m9",
        conversation_id="conv-9",
        role=MessageRole.SYSTEM,
        content="Sys",
        status=MessageStatus.FAILED,
        created_at=now,
        updated_at=now,
    )

    assert record.role == MessageRole.SYSTEM
    assert record.status == MessageStatus.FAILED
    assert record.source_run_id is None

    with pytest.raises(FrozenInstanceError):
        record.content = "Nope"  # type: ignore[misc]


def test_conversation_identity_is_caller_supplied_and_never_minted() -> None:
    repo = MemoryConversationRepository()
    repo.create("conv-alpha", title="Alpha")
    repo.create("conv-beta", title="Beta")

    assert repo.get("conv-alpha") is not None
    assert repo.get("conv-beta") is not None
    with pytest.raises(ValueError):
        repo.create("conv-alpha", title="Duplicate")


def test_message_identity_and_conversation_association_are_preserved() -> None:
    repo = MemoryMessageRepository()
    now = datetime.now(UTC)
    alpha = MessageRecord(
        message_id="id-1",
        conversation_id="conv-a",
        role=MessageRole.USER,
        content="a",
        status=MessageStatus.COMPLETE,
        created_at=now,
        updated_at=now,
    )
    beta = MessageRecord(
        message_id="id-2",
        conversation_id="conv-b",
        role=MessageRole.ASSISTANT,
        content="b",
        status=MessageStatus.COMPLETE,
        created_at=now,
        updated_at=now,
    )
    repo.append(alpha)
    repo.append(beta)

    assert [m.message_id for m in repo.list_for_conversation("conv-a")] == ["id-1"]
    assert [m.message_id for m in repo.list_for_conversation("conv-b")] == ["id-2"]
    assert repo.list_for_conversation("conv-c") == []
    assert alpha.conversation_id == "conv-a"


# ============================================================
# END: Record identity and semantics
# ============================================================


# ============================================================
# BEGIN: Existing in-memory stores and the new ports
# ============================================================


def test_conversation_store_records_are_the_same_conversation_record_type() -> None:
    """No duplicate conversation-record type exists."""
    from ava.repositories import ConversationRecord as PortConversationRecord
    from ava.services import conversation_store

    assert vars(conversation_store)["ConversationRecord"] is PortConversationRecord
    record = ConversationStore().create("conv-1", title="T")
    assert isinstance(record, PortConversationRecord)


def test_message_store_records_are_the_same_message_record_type() -> None:
    from ava.repositories import MessageRecord as PortMessageRecord
    from ava.services import message_store

    assert vars(message_store)["MessageRecord"] is PortMessageRecord


def test_conversation_store_now_implements_conversation_repository() -> None:
    """Step 4.4 makes ``ConversationStore`` an explicit port implementation."""
    assert issubclass(ConversationStore, ConversationRepository)
    store = ConversationStore()
    assert isinstance(store, ConversationRepository)


def test_message_store_now_implements_message_repository() -> None:
    """Step 4.4 makes ``MessageStore`` an explicit port implementation."""
    assert issubclass(MessageStore, MessageRepository)
    store = MessageStore()
    assert isinstance(store, MessageRepository)


def test_stores_expose_the_port_surfaces() -> None:
    """Shape guard: stores expose every port method with matching params.

    Stores may expose extra observability helpers such as ``clear``.
    """
    import inspect

    for store_cls, port_cls in (
        (ConversationStore, ConversationRepository),
        (MessageStore, MessageRepository),
    ):
        for name, port_member in vars(port_cls).items():
            if name.startswith("_") or not callable(port_member):
                continue
            store_member = getattr(store_cls, name, None)
            assert store_member is not None, f"{store_cls.__name__} lacks port method {name}"
            port_params = list(inspect.signature(port_member).parameters)
            store_params = list(inspect.signature(store_member).parameters)
            assert port_params[1:] == store_params[1:], (store_cls.__name__, name)


def test_store_isolation_between_instances_and_clear() -> None:
    """Two stores never share state and ``clear`` resets the instance."""
    first = ConversationStore()
    second = ConversationStore()
    first.create("conv-1", title="T")
    assert second.get("conv-1") is None
    first.clear()
    assert first.get("conv-1") is None

    messages = MessageStore()
    now = datetime.now(UTC)
    messages.append(
        MessageRecord(
            message_id="m1",
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello",
            status=MessageStatus.COMPLETE,
            created_at=now,
            updated_at=now,
        )
    )
    assert MessageStore().list_for_conversation("conv-1") == []


# ============================================================
# END: Existing in-memory stores and the new ports
# ============================================================


# ============================================================
# BEGIN: Boundary type discipline
# ============================================================


def _annotation_root_modules(annotation: object) -> set[str]:
    """Collect top-level module names reachable from a type annotation."""
    modules: set[str] = set()
    pending = [annotation]
    while pending:
        current = pending.pop()
        module = getattr(current, "__module__", None)
        if module:
            modules.add(module.split(".")[0])
        pending.extend(arg for arg in get_args(current) if arg is not current)
    return modules


def test_conversation_port_types_are_ava_owned_or_stdlib_only() -> None:
    """No provider/framework/database type crosses either new port boundary."""
    port_methods = {
        ConversationRepository: [
            ConversationRepository.create,
            ConversationRepository.get,
            ConversationRepository.list,
            ConversationRepository.set_project,
            ConversationRepository.update_title,
        ],
        MessageRepository: [
            MessageRepository.append,
            MessageRepository.get,
            MessageRepository.list_for_conversation,
        ],
    }
    for port_cls, methods in port_methods.items():
        for method in methods:
            for annotation in get_type_hints(method).values():
                for module in _annotation_root_modules(annotation):
                    assert module in sys.stdlib_module_names or module == "ava", (
                        port_cls.__name__,
                        method.__name__,
                        module,
                    )


# ============================================================
# END: Boundary type discipline
# ============================================================
