"""AVA repository port contract tests (Steps 4.2–4.3).

Prove the persistence repository ports are:

* implementable by framework-free in-memory implementations;
* typed entirely with AVA-owned (or stdlib) domain/contract types;
* implemented by the existing in-memory ``RunStore`` / ``RunEventStore``
  adapters, which Step 4.3 made explicit subclasses of the ports;
* free of database, provider, and framework concepts.

No database is introduced or exercised here.
"""

import sys
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import get_args, get_type_hints

import pytest

from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.models import ModelHostingMode
from ava.contracts.responses import RunStatus
from ava.repositories import (
    TERMINAL_EVENT_TYPES,
    RunEventRepository,
    RunRecord,
    RunRepository,
)
from ava.services.run_event_store import RunEventStore
from ava.services.run_store import RunStore

# ============================================================
# BEGIN: In-memory port implementations (test fakes)
# ============================================================


class MemoryRunRepository(RunRepository):
    """Framework-free in-memory implementation used to prove the port shape.

    Intentionally mirrors ``RunStore`` semantics so the port contract is
    validated against the behavior the in-memory store now implements.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def create(self, run_id: str) -> RunRecord:
        if run_id in self._runs:
            raise ValueError(f"Run already exists: {run_id}")
        now = datetime.now(UTC)
        record = RunRecord(
            run_id=run_id,
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        self._runs[run_id] = record
        return record

    def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def update_status(self, run_id: str, status: RunStatus) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        updated = replace(record, status=status, updated_at=datetime.now(UTC))
        self._runs[run_id] = updated
        return updated

    def set_execution_selection(
        self,
        run_id: str,
        selection: RunExecutionSelection | None,
    ) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        updated = replace(record, execution_selection=selection, updated_at=datetime.now(UTC))
        self._runs[run_id] = updated
        return updated


class MemoryRunEventRepository(RunEventRepository):
    """Framework-free in-memory implementation used to prove the port shape.

    Intentionally mirrors ``RunEventStore`` semantics, including the
    single-terminal-event idempotency invariant.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[RunEvent]] = {}

    def append(self, event: RunEvent) -> RunEvent:
        existing = self._events.get(event.run_id, [])
        if event.event_type in TERMINAL_EVENT_TYPES and any(
            other.event_type in TERMINAL_EVENT_TYPES for other in existing
        ):
            return event
        self._events.setdefault(event.run_id, []).append(event)
        return event

    def get_events(self, run_id: str) -> list[RunEvent]:
        return list(self._events.get(run_id, []))

    def get_latest(self, run_id: str) -> RunEvent | None:
        events = self._events.get(run_id)
        return events[-1] if events else None


# ============================================================
# END: In-memory port implementations (test fakes)
# ============================================================


# ============================================================
# BEGIN: Port implementability
# ============================================================


def test_run_repository_is_an_abstract_contract() -> None:
    """The port is a contract, not a usable default implementation."""
    with pytest.raises(TypeError):
        RunRepository()  # type: ignore[abstract]


def test_run_event_repository_is_an_abstract_contract() -> None:
    with pytest.raises(TypeError):
        RunEventRepository()  # type: ignore[abstract]


def test_run_repository_is_implementable_by_in_memory_fake() -> None:
    """The port interface can be satisfied without any framework or database."""
    repo = MemoryRunRepository()

    record = repo.create("run-1")
    assert isinstance(repo, RunRepository)
    assert record.run_id == "run-1"
    assert record.status == RunStatus.PENDING

    with pytest.raises(ValueError):
        repo.create("run-1")

    updated = repo.update_status("run-1", RunStatus.RUNNING)
    assert updated is not None
    assert updated.status == RunStatus.RUNNING
    assert updated.updated_at >= updated.created_at

    selection = RunExecutionSelection(
        runtime_id="runtime-a",
        model_provider_id="provider-a",
        model_id="model-a",
        hosting_mode=ModelHostingMode.LOCAL,
    )
    with_selection = repo.set_execution_selection("run-1", selection)
    assert with_selection is not None
    assert with_selection.execution_selection == selection

    assert repo.get("ghost") is None
    assert repo.update_status("ghost", RunStatus.FAILED) is None


def test_run_event_repository_is_implementable_by_in_memory_fake() -> None:
    """The event port preserves order and the terminal-event invariant."""
    repo = MemoryRunEventRepository()

    events = [
        RunEvent(event_id="e1", run_id="r", event_type=EventType.RUN_STARTED),
        RunEvent(event_id="e2", run_id="r", event_type=EventType.MESSAGE_STARTED),
        RunEvent(event_id="e3", run_id="r", event_type=EventType.MESSAGE_CONTENT, payload={"content": "hi"}),
        RunEvent(event_id="e4", run_id="r", event_type=EventType.RUN_COMPLETED),
    ]
    for event in events:
        repo.append(event)

    assert [e.event_id for e in repo.get_events("r")] == ["e1", "e2", "e3", "e4"]
    assert repo.get_latest("r") is events[-1]

    # A second terminal event for an already-terminal run is ignored.
    repo.append(RunEvent(event_id="e5", run_id="r", event_type=EventType.RUN_FAILED))
    assert [e.event_id for e in repo.get_events("r")] == ["e1", "e2", "e3", "e4"]

    assert repo.get_events("unknown") == []
    assert repo.get_latest("unknown") is None


# ============================================================
# END: Port implementability
# ============================================================


# ============================================================
# BEGIN: Run record identity and semantics
# ============================================================


def test_run_records_are_frozen_ava_owned_snapshots() -> None:
    """RunRecord carries AVA-owned fields and is immutable."""
    now = datetime.now(UTC)
    record = RunRecord(run_id="run-9", status=RunStatus.PENDING, created_at=now, updated_at=now)

    assert record.run_id == "run-9"
    assert record.status == RunStatus.PENDING
    assert record.created_at == now
    assert record.execution_selection is None

    with pytest.raises(FrozenInstanceError):
        record.status = RunStatus.FAILED  # type: ignore[misc]


def test_run_identity_is_caller_supplied_and_never_minted() -> None:
    """Repositories never generate run ids; identity stays AVA/caller-owned."""
    repo = MemoryRunRepository()
    repo.create("run-alpha")
    repo.create("run-beta")

    assert repo.get("run-alpha") is not None
    assert repo.get("run-beta") is not None
    # A second create with the same id must not silently mint a new run.
    with pytest.raises(ValueError):
        repo.create("run-alpha")

    assert isinstance("run-alpha", str)


def test_event_identity_and_run_association_are_preserved() -> None:
    """Events keep AVA-owned ids and stay isolated to their run."""
    repo = MemoryRunEventRepository()
    alpha = RunEvent(event_id="id-1", run_id="a", event_type=EventType.RUN_STARTED)
    beta = RunEvent(event_id="id-2", run_id="b", event_type=EventType.RUN_STARTED)
    repo.append(alpha)
    repo.append(beta)

    assert [e.event_id for e in repo.get_events("a")] == ["id-1"]
    assert [e.event_id for e in repo.get_events("b")] == ["id-2"]
    assert repo.get_events("c") == []
    assert alpha.run_id == "a"


# ============================================================
# END: Run record identity and semantics
# ============================================================


# ============================================================
# BEGIN: Terminal event vocabulary
# ============================================================


def test_terminal_event_types_are_the_ava_owned_terminal_set() -> None:
    """The shared terminal set matches the documented run lifecycle."""
    assert frozenset(
        {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}
    ) == TERMINAL_EVENT_TYPES
    for event_type in TERMINAL_EVENT_TYPES:
        assert event_type in EventType
    assert EventType.RUN_STARTED not in TERMINAL_EVENT_TYPES
    assert EventType.MESSAGE_CONTENT not in TERMINAL_EVENT_TYPES


# ============================================================
# END: Terminal event vocabulary
# ============================================================


# ============================================================
# BEGIN: Existing in-memory stores and the new ports
# ============================================================


def test_run_store_records_are_the_same_run_record_type() -> None:
    """No duplicate run-record type exists: the store already returns the port's record."""
    from ava.repositories import RunRecord as PortRunRecord
    from ava.services.run_store import RunRecord as StoreRunRecord

    assert StoreRunRecord is PortRunRecord
    record = RunStore().create("run-1")
    assert isinstance(record, PortRunRecord)


def test_run_store_now_implements_run_repository() -> None:
    """Step 4.3 makes ``RunStore`` an explicit ``RunRepository`` implementation."""
    assert issubclass(RunStore, RunRepository)
    store = RunStore()
    assert isinstance(store, RunRepository)


def test_run_event_store_now_implements_run_event_repository() -> None:
    """Step 4.3 makes ``RunEventStore`` an explicit ``RunEventRepository`` implementation."""
    assert issubclass(RunEventStore, RunEventRepository)
    store = RunEventStore()
    assert isinstance(store, RunEventRepository)


def test_existing_stores_already_expose_the_port_surfaces() -> None:
    """Shape guard: stores expose every port method with matching params.

    Step 4.2 pre-validated the alignment so Step 4.3 conformance was a
    declaration, not a redesign. This stays on as a shape regression guard.
    (Stores may expose extra observability helpers such as ``clear``.)
    """
    import inspect

    for store_cls, port_cls in ((RunStore, RunRepository), (RunEventStore, RunEventRepository)):
        for name, port_member in vars(port_cls).items():
            if name.startswith("_") or not callable(port_member):
                continue
            store_member = getattr(store_cls, name, None)
            assert store_member is not None, f"{store_cls.__name__} lacks port method {name}"
            port_params = list(inspect.signature(port_member).parameters)
            store_params = list(inspect.signature(store_member).parameters)
            # Both are unbound methods; drop ``self`` before comparing.
            assert port_params[1:] == store_params[1:], (store_cls.__name__, name)


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


def test_repository_port_types_are_ava_owned_or_stdlib_only() -> None:
    """No provider/framework/database type crosses either port boundary."""
    port_methods = {
        RunRepository: [
            RunRepository.create,
            RunRepository.get,
            RunRepository.update_status,
            RunRepository.set_execution_selection,
        ],
        RunEventRepository: [
            RunEventRepository.append,
            RunEventRepository.get_events,
            RunEventRepository.get_latest,
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