"""Cold-start stranded-run recovery.

A restart cannot be silent about lost work. These tests pin what AVA does with
a run that is still active in the database when a fresh process starts: it
settles the run through the lifecycle authority, it says *why* it did, and it
does not touch anything the user can still see.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import ExecutionMode
from ava.contracts.responses import RunStatus
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import (
    RelationalRunEventRepository,
    RelationalRunRepository,
)
from ava.repositories.message_repository import MessageRecord
from ava.repositories.run_repository import RunRecord, RunRepository
from ava.services.assistant_response_service import AssistantResponseService
from ava.services.run_event_store import RunEventStore
from ava.services.run_lifecycle_service import RunLifecycleService
from ava.services.run_recovery_service import (
    RESTART_INTERRUPTION_PAYLOAD,
    RunRecoveryService,
)
from ava.services.run_store import RunStore

_ACTIVE = (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_FOR_APPROVAL)


def _recovery() -> tuple[RunStore, RunEventStore, RunLifecycleService, RunRecoveryService]:
    runs, events = RunStore(), RunEventStore()
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    return runs, events, lifecycle, RunRecoveryService(run_repository=runs, lifecycle=lifecycle)


# ============================================================
# BEGIN: Convergence policy
# ============================================================


def test_cold_start_fails_every_process_local_active_run_once() -> None:
    runs, events, lifecycle, recovery = _recovery()
    active_runs = (
        ("pending", RunStatus.PENDING),
        ("running", RunStatus.RUNNING),
        ("waiting", RunStatus.WAITING_FOR_APPROVAL),
    )
    for run_id, status in active_runs:
        lifecycle.create_run(run_id)
        if status is not RunStatus.PENDING:
            lifecycle.transition(run_id, status)
    lifecycle.request_cancellation("running")

    summary = recovery.recover_stranded_runs()

    assert summary.active_found == 3
    assert summary.settled_failed == 3
    for run_id in ("pending", "running", "waiting"):
        assert runs.get(run_id).status is RunStatus.FAILED
        failed = [event for event in events.get_events(run_id) if event.event_type is EventType.RUN_FAILED]
        assert len(failed) == 1
        assert failed[0].payload == RESTART_INTERRUPTION_PAYLOAD
    assert runs.get("running").cancellation_requested_at is not None
    assert recovery.recover_stranded_runs().active_found == 0
    assert len(events.get_events("running")) == 3  # start, cancel intent, recovery failure


def test_recovery_preserves_terminal_runs_and_continues_event_sequence() -> None:
    runs, events, lifecycle, recovery = _recovery()
    lifecycle.create_run("active")
    lifecycle.start("active")
    events.append(RunEvent(event_id="content", run_id="active", event_type=EventType.MESSAGE_CONTENT,
                           payload={"message_id": "assistant", "content": "Hello\n世界"}))
    before = runs.get("active")
    lifecycle.create_run("terminal")
    lifecycle.start("terminal")
    lifecycle.complete("terminal")
    terminal_updated = runs.get("terminal").updated_at

    recovery.recover_stranded_runs()

    assert runs.get("active").status is RunStatus.FAILED
    assert runs.get("active").created_at == before.created_at
    assert runs.get("active").updated_at >= before.updated_at
    assert [event.sequence for event in events.get_events("active")] == [1, 2, 3]
    assert events.get_events("active")[-1].event_type is EventType.RUN_FAILED
    assert runs.get("terminal").status is RunStatus.COMPLETED
    assert runs.get("terminal").updated_at == terminal_updated


def test_cancellation_intent_survives_recovery_without_becoming_cancellation() -> None:
    """A recorded request is preserved evidence, not a cancellation outcome.

    The runtime that would have acknowledged the request died with the process,
    so AVA never observed a stop. Turning the request into ``cancelled`` would
    claim an outcome nobody witnessed.
    """
    runs, events, lifecycle, recovery = _recovery()
    lifecycle.create_run("requested")
    lifecycle.start("requested")
    requested_at = lifecycle.request_cancellation("requested").cancellation_requested_at

    recovery.recover_stranded_runs()

    record = runs.get("requested")
    assert record.status is RunStatus.FAILED
    assert record.cancellation_requested_at == requested_at
    assert record.cancellation_requested is True
    types = [event.event_type for event in events.get_events("requested")]
    assert types == [EventType.RUN_STARTED, EventType.RUN_CANCEL_REQUESTED, EventType.RUN_FAILED]
    assert EventType.RUN_CANCELLED not in types


def test_a_lost_status_write_is_not_repaired_by_a_synthesized_fact() -> None:
    """A committed status without its event is history, not an invitation to invent.

    The event/event-status atomicity gap is documented and cross-repository. What
    matters here is the recovery consequence: once the status is terminal, a
    later startup finds nothing active and must not append a second failure.
    """
    runs, events, lifecycle, recovery = _recovery()
    lifecycle.create_run("run")
    lifecycle.start("run")

    def refuse(event: RunEvent) -> None:
        if event.event_type is EventType.RUN_FAILED:
            raise OSError("event store unavailable")
        events.append(event)

    original, events.append = events.append, refuse
    try:
        recovery.recover_stranded_runs()
    except OSError:
        pass  # The append failure surfaces; the status write already committed.
    finally:
        events.append = original

    assert runs.get("run").status is RunStatus.FAILED
    assert [event.event_type for event in events.get_events("run")] == [EventType.RUN_STARTED]

    # A second cold start sees a terminal run and adds nothing.
    summary = recovery.recover_stranded_runs()
    assert summary.active_found == 0
    assert [event.event_type for event in events.get_events("run")] == [EventType.RUN_STARTED]


class _MinimalRunRepository(RunRepository):
    """A lightweight double with the current Run creation contract.

    It deliberately implements neither ``list_active`` nor ``list_run_ids``. It
    exists to prove the compatibility contract holds: adding active-run
    discovery to the port must not force existing test doubles to change.
    """

    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}

    def create(
        self,
        run_id,
        *,
        conversation_id=None,
        source_user_message_id=None,
        execution_mode=ExecutionMode.CHAT,
    ):
        now = datetime.now(UTC)
        self.runs[run_id] = RunRecord(
            run_id=run_id, status=RunStatus.PENDING, conversation_id=conversation_id,
            source_user_message_id=source_user_message_id, execution_selection=None,
            execution_mode=execution_mode,
            cancellation_requested_at=None, created_at=now, updated_at=now,
        )
        return self.runs[run_id]

    def get(self, run_id):
        return self.runs.get(run_id)

    def update_status(self, run_id, status):
        record = self.runs.get(run_id)
        if record is None:
            return None
        updated = replace(record, status=status, updated_at=datetime.now(UTC))
        self.runs[run_id] = updated
        return updated

    def set_execution_selection(self, run_id, selection):
        del selection
        return self.runs.get(run_id)

    def request_cancellation(self, run_id, *, requested_at):
        record = self.runs.get(run_id)
        if record is None or not record.status.is_active:
            return None
        updated = replace(record, cancellation_requested_at=requested_at)
        self.runs[run_id] = updated
        return updated

    def compare_and_set_status(self, run_id, *, expected_status, status):
        record = self.runs.get(run_id)
        if record is None or record.status is not expected_status:
            return None
        return self.update_status(run_id, status)


class _EnumerableRunRepository(_MinimalRunRepository):
    """The same double plus the one generic method discovery needs."""

    def list_run_ids(self):
        return list(self.runs)


def test_a_pre_5_30_test_double_stays_instantiable_and_is_never_faked_empty() -> None:
    """Compatibility means "still works", not "reports nothing to recover".

    The regression this phase hit was making ``list_active`` abstract, which
    broke every lightweight double at instantiation. The compatible fix must not
    swing to the opposite failure: a repository that genuinely holds active runs
    may never answer an empty active set, or recovery would declare a database
    of stranded runs healthy.
    """
    runs = _MinimalRunRepository()
    runs.create("run")
    assert runs.get("run").status is RunStatus.PENDING

    # Not a silent "nothing to do": an unsupported capability is reported.
    with pytest.raises(NotImplementedError, match="cannot be answered with an empty result"):
        list(runs.list_active())


def test_the_default_active_listing_is_correct_for_any_enumerable_repository() -> None:
    """``list_active``'s default is a working generic query, not a placeholder."""
    runs = _EnumerableRunRepository()
    for run_id in ("zulu", "alpha", "mike"):
        runs.create(run_id)
    runs.update_status("alpha", RunStatus.RUNNING)
    runs.update_status("mike", RunStatus.WAITING_FOR_APPROVAL)
    runs.create("settled")
    runs.update_status("settled", RunStatus.COMPLETED)
    runs.request_cancellation("alpha", requested_at=datetime(2026, 5, 6, 7, 1, tzinfo=UTC))

    before = dict(runs.runs)
    active = list(runs.list_active())

    # Every active state is returned; equal/coarse timestamps use a stable key.
    assert {record.run_id for record in active} == {"zulu", "alpha", "mike"}
    assert {record.run_id: record.status for record in active} == {
        "zulu": RunStatus.PENDING,
        "alpha": RunStatus.RUNNING,
        "mike": RunStatus.WAITING_FOR_APPROVAL,
    }
    # Intent is not an outcome, and the call changed nothing.
    assert runs.get("alpha").cancellation_requested_at is not None
    assert runs.runs == before
    # Deterministic: the same state always produces the same order.
    assert [record.run_id for record in runs.list_active()] == [
        record.run_id for record in active
    ]


def test_recovery_over_the_default_listing_still_goes_through_the_authority() -> None:
    """A double that only implements the generic method is fully recoverable."""
    runs = _EnumerableRunRepository()
    events = RunEventStore()
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    lifecycle.create_run("stranded")
    lifecycle.request_cancellation("stranded")

    summary = RunRecoveryService(
        run_repository=runs, lifecycle=lifecycle
    ).recover_stranded_runs()

    assert (summary.active_found, summary.settled_failed) == (1, 1)
    assert runs.get("stranded").status is RunStatus.FAILED
    assert runs.get("stranded").cancellation_requested_at is not None
    assert [event.event_type for event in events.get_events("stranded")] == [
        EventType.RUN_CANCEL_REQUESTED,
        EventType.RUN_FAILED,
    ]


# ============================================================
# END: Convergence policy
# ============================================================
# ============================================================
# BEGIN: Application startup
# ============================================================


def test_startup_settles_a_stranded_run_before_serving_requests(tmp_path) -> None:
    """The real lifespan path: durable content, intent, and a truthful failure."""
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "restart.sqlite3"),
        attachment_storage="memory",
    )

    first = create_app(settings=settings)
    with TestClient(first) as client:
        conversation_id = client.post("/conversations", json={"title": "Stranded"}).json()[
            "conversation_id"
        ]
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "keep going", "role": "user"},
        ).json()
        runs = first.state.persistence.run_repository
        events = first.state.persistence.run_event_repository
        messages = first.state.persistence.message_repository
        lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
        lifecycle.create_run(
            "stranded",
            conversation_id=conversation_id,
            source_user_message_id=message["message_id"],
        )
        runs.set_assistant_message_id("stranded", "assistant-1")
        now = datetime.now(UTC)
        messages.append(
            MessageRecord(
                message_id="assistant-1",
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="",
                status=MessageStatus.PENDING,
                source_run_id="stranded",
                created_at=now,
                updated_at=now,
            )
        )
        lifecycle.start("stranded")
        output = AssistantResponseService(
            run_repository=runs, run_event_repository=events, message_repository=messages
        )
        output.start_message("stranded", "assistant-1")
        output.record_snapshot(
            run_id="stranded",
            message_id="assistant-1",
            conversation_id=conversation_id,
            content="Half an ans",
        )
        requested_at = client.post("/runs/stranded/cancel").json()["cancellation_requested_at"]
        assert requested_at, "the cancellation request must be durable before the restart"
    first.state.persistence.dispose()

    second = create_app(settings=settings)
    with TestClient(second) as client:
        summary = second.state.run_recovery_summary
        assert (summary.active_found, summary.settled_failed) == (1, 1)

        run = client.get("/runs/stranded").json()
        assert run["status"] == "failed"
        assert run["cancellation_requested_at"] == requested_at

        history = client.get("/runs/stranded/events").json()
        assert [event["event_type"] for event in history] == [
            "run_started",
            "message_started",
            "message_content",
            "run_cancel_requested",
            "run_failed",
        ]
        assert history[-1]["payload"] == RESTART_INTERRUPTION_PAYLOAD

        # Partial text is truthful history and must survive untouched.
        rows = client.get(f"/conversations/{conversation_id}/messages").json()["messages"]
        assistant = next(row for row in rows if row["role"] == "assistant")
        assert assistant["content"] == "Half an ans"
        assert assistant["source_run_id"] == "stranded"
        assert assistant["status"] == "failed"
    second.state.persistence.dispose()

    third = create_app(settings=settings)
    with TestClient(third) as client:
        assert third.state.run_recovery_summary.active_found == 0
        assert len(client.get("/runs/stranded/events").json()) == 5
    third.state.persistence.dispose()


# ============================================================
# END: Application startup
# ============================================================


# ============================================================
# END: Application startup
# ============================================================
# ============================================================
# BEGIN: Replay and transport after recovery
# ============================================================


def test_replay_after_recovery_returns_only_persisted_facts(tmp_path) -> None:
    """5.26's rule, applied to a recovery settlement: no synthesized history."""
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "replay.sqlite3"),
        attachment_storage="memory",
    )
    first = create_app(settings=settings)
    with TestClient(first):
        runs = first.state.persistence.run_repository
        lifecycle = RunLifecycleService(
            run_repository=runs,
            run_event_repository=first.state.persistence.run_event_repository,
        )
        lifecycle.create_run("stranded")
        lifecycle.start("stranded")
    first.state.persistence.dispose()

    second = create_app(settings=settings)
    with TestClient(second) as client:
        full = client.get("/runs/stranded/events?after_sequence=0").json()
        assert [event["event_type"] for event in full] == ["run_started", "run_failed"]
        assert [event["sequence"] for event in full] == [1, 2]
        # The recovery fact is a real event, so the cursor reaches it.
        assert [
            event["event_type"]
            for event in client.get("/runs/stranded/events?after_sequence=1").json()
        ] == ["run_failed"]
        assert client.get("/runs/stranded/events?after_sequence=2").json() == []
    second.state.persistence.dispose()


def test_a_resuming_client_receives_the_recovery_event_and_closes(tmp_path) -> None:
    """A frontend disconnected across the restart resumes onto the real fact.

    This is 5.28 meeting 5.30: the cursor stops before the recovery event, the
    resumed stream delivers exactly that event, and the stream closes on it
    because it is terminal.
    """
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "resume.sqlite3"),
        attachment_storage="memory",
    )
    first = create_app(settings=settings)
    with TestClient(first):
        runs = first.state.persistence.run_repository
        lifecycle = RunLifecycleService(
            run_repository=runs,
            run_event_repository=first.state.persistence.run_event_repository,
        )
        lifecycle.create_run("stranded")
        lifecycle.start("stranded")
        # Fact 1 is what the client already processed before the restart.
        assert len(first.state.persistence.run_event_repository.get_events("stranded")) == 1
    first.state.persistence.dispose()

    second = create_app(settings=settings)
    with TestClient(second) as client:
        body = client.get("/runs/stranded/stream?after_sequence=1").text
        frames = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
        assert [frame["event_type"] for frame in frames] == ["run_failed"]
        assert frames[0]["sequence"] == 2
        assert frames[0]["payload"] == RESTART_INTERRUPTION_PAYLOAD
    second.state.persistence.dispose()


# ============================================================
# END: Replay and transport after recovery
# ============================================================
# ============================================================
# BEGIN: Independence guarantees
# ============================================================


def test_recovery_never_touches_execution_provider_or_model_code(tmp_path) -> None:
    """A hard acceptance criterion, proven rather than asserted.

    Every boundary an execution would cross is instrumented: the agent, the
    runtime, the model provider, and the runtime registry. Recovery is lifecycle
    convergence only, so none of them may be reached.
    """
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "no-execution.sqlite3"),
        attachment_storage="memory",
    )
    first = create_app(settings=settings)
    with TestClient(first):
        runs = first.state.persistence.run_repository
        lifecycle = RunLifecycleService(
            run_repository=runs,
            run_event_repository=first.state.persistence.run_event_repository,
        )
        lifecycle.create_run("stranded")
        lifecycle.start("stranded")
    first.state.persistence.dispose()

    called: list[str] = []
    second = create_app(settings=settings)
    agent = second.state.run_service._agent  # noqa: SLF001 - observation only
    runtime_registry = second.state.runtime_registry
    model_registry = second.state.model_provider_registry

    def forbid(name: str, original):
        def wrapper(*args, **kwargs):
            called.append(name)
            return original(*args, **kwargs)

        return wrapper

    for name, target, attribute in (
        ("agent.start_run", agent, "start_run"),
        ("agent.start_run_streaming", agent, "start_run_streaming"),
        ("agent.cancel_run", agent, "cancel_run"),
        ("runtime.resolve", runtime_registry, "get"),
        ("provider.health", model_registry, "register"),
    ):
        setattr(target, attribute, forbid(name, getattr(target, attribute)))

    with TestClient(second) as client:
        assert client.get("/runs/stranded").json()["status"] == "failed"

    assert called == [], f"recovery reached execution code: {called}"


def test_startup_readiness_follows_recovery_so_no_client_sees_a_stale_running_run(
    tmp_path,
) -> None:
    """The first ordinary read after startup already sees the settled state."""
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "readiness.sqlite3"),
        attachment_storage="memory",
    )
    first = create_app(settings=settings)
    with TestClient(first):
        runs = first.state.persistence.run_repository
        lifecycle = RunLifecycleService(
            run_repository=runs,
            run_event_repository=first.state.persistence.run_event_repository,
        )
        lifecycle.create_run("stranded")
        lifecycle.start("stranded")
    first.state.persistence.dispose()

    second = create_app(settings=settings)
    # No TestClient context: the lifespan has not run yet, so nothing is settled.
    assert second.state.persistence.run_repository.get("stranded").status is RunStatus.RUNNING
    with TestClient(second) as client:
        assert second.state.run_recovery_summary.settled_failed == 1
        assert client.get("/runs/stranded").json()["status"] == "failed"
    second.state.persistence.dispose()


def test_several_stranded_runs_across_conversations_are_handled_independently(
    tmp_path,
) -> None:
    """No cross-run contamination: each run keeps its own status, event, and content."""
    runs, events, lifecycle, recovery = _recovery()
    lifecycle.create_run("run-a", conversation_id="conversation-a")
    lifecycle.transition("run-a", RunStatus.RUNNING)
    lifecycle.create_run("run-b", conversation_id="conversation-b")
    lifecycle.request_cancellation("run-b")
    lifecycle.create_run("run-c", conversation_id="conversation-c")
    lifecycle.transition("run-c", RunStatus.RUNNING)
    events.append(
        RunEvent(
            event_id="content",
            run_id="run-c",
            event_type=EventType.MESSAGE_CONTENT,
            payload={"message_id": "assistant", "content": "kept"},
        )
    )
    lifecycle.complete("run-c")

    summary = recovery.recover_stranded_runs()

    assert (summary.active_found, summary.settled_failed) == (2, 2)
    assert runs.get("run-a").status is RunStatus.FAILED
    assert runs.get("run-a").cancellation_requested_at is None
    assert runs.get("run-b").status is RunStatus.FAILED
    assert runs.get("run-b").cancellation_requested_at is not None
    # The finished run is not visited at all.
    assert runs.get("run-c").status is RunStatus.COMPLETED
    assert [event.event_type for event in events.get_events("run-c")] == [
        EventType.RUN_STARTED,
        EventType.MESSAGE_CONTENT,
        EventType.RUN_COMPLETED,
    ]
    assert [event.event_type for event in events.get_events("run-a")] == [
        EventType.RUN_STARTED,
        EventType.RUN_FAILED,
    ]


def test_one_failing_settlement_does_not_roll_back_the_ones_that_succeeded() -> None:
    """A repository error stops the pass; committed settlements stay committed.

    AVA has no cross-run transaction, and pretending otherwise would mean lying
    about durable state. Instead the failure is loud, and the next startup finds
    the already-terminal run and retries only what is still active.
    """
    runs, events, lifecycle, recovery = _recovery()
    for run_id in ("run-a", "run-b"):
        lifecycle.create_run(run_id)
        lifecycle.transition(run_id, RunStatus.RUNNING)

    original = runs.update_status

    def fail_second(run_id, status):
        if run_id == "run-b":
            raise OSError("persistence unavailable")
        return original(run_id, status)

    runs.update_status = fail_second
    try:
        with pytest.raises(OSError, match="persistence unavailable"):
            recovery.recover_stranded_runs()
    finally:
        del runs.update_status

    # The first run was already durable when the second one failed.
    assert runs.get("run-a").status is RunStatus.FAILED
    assert [event.event_type for event in events.get_events("run-a")][-1] is EventType.RUN_FAILED
    assert runs.get("run-b").status is RunStatus.RUNNING

    # The next cold start is idempotent for the settled run and retries the rest.
    summary = recovery.recover_stranded_runs()
    assert (summary.active_found, summary.settled_failed) == (1, 1)
    assert runs.get("run-b").status is RunStatus.FAILED
    assert [event.event_type for event in events.get_events("run-a")].count(
        EventType.RUN_FAILED
    ) == 1


# ============================================================
# END: Independence guarantees
# ============================================================


# ============================================================
# END: Independence guarantees
# ============================================================
# ============================================================
# BEGIN: Persistence interaction
# ============================================================


def test_a_recovery_settlement_rolls_back_with_its_enclosing_transaction(tmp_path) -> None:
    """Recovery writes through the same transaction lock as everything else.

    Phase 5.26 made SQLite transactions reentrant through savepoints. A recovery
    settlement must behave like any other lifecycle write inside an outer unit of
    work: no self-deadlock on the reentrant lock, and no committed status that
    the enclosing transaction then discards.
    """
    path = str(tmp_path / "rollback.sqlite3")
    database = SqliteDatabase(path)
    runs = RelationalRunRepository(database=database)
    events = RelationalRunEventRepository(database=database)
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    recovery = RunRecoveryService(run_repository=runs, lifecycle=lifecycle)
    lifecycle.create_run("stranded")
    lifecycle.transition("stranded", RunStatus.RUNNING)

    with pytest.raises(OSError, match="outer rollback"), database.transaction():
        recovery.recover_stranded_runs()
        assert runs.get("stranded").status is RunStatus.FAILED
        raise OSError("outer rollback")

    # The outer rollback undid the status and the recovery fact together, so the
    # run is still exactly where the previous process left it.
    assert runs.get("stranded").status is RunStatus.RUNNING
    assert [event.event_type for event in events.get_events("stranded")] == [
        EventType.RUN_STARTED
    ]

    # A later pass settles it for real, proving the lock was released cleanly.
    assert recovery.recover_stranded_runs().settled_failed == 1
    assert runs.get("stranded").status is RunStatus.FAILED
    database.dispose()


def test_a_startup_persistence_failure_prevents_the_application_from_serving(
    tmp_path,
) -> None:
    """A recovery failure must not leave a half-converged process answering reads.

    Silently swallowing it would serve ``running`` snapshots for executions that
    no longer exist, which is the exact lie this phase exists to remove.
    """
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "startup-failure.sqlite3"),
        attachment_storage="memory",
    )
    first = create_app(settings=settings)
    with TestClient(first):
        runs = first.state.persistence.run_repository
        lifecycle = RunLifecycleService(
            run_repository=runs,
            run_event_repository=first.state.persistence.run_event_repository,
        )
        lifecycle.create_run("stranded")
        lifecycle.transition("stranded", RunStatus.RUNNING)
    first.state.persistence.dispose()

    second = create_app(settings=settings)
    original = second.state.run_recovery_service._runs.list_active  # noqa: SLF001

    def refuse():
        raise OSError("database unavailable")

    second.state.run_recovery_service._runs.list_active = refuse  # type: ignore[method-assign]
    try:
        with pytest.raises(OSError, match="database unavailable"), TestClient(second):
            pass
    finally:
        second.state.run_recovery_service._runs.list_active = original  # type: ignore[method-assign]
        second.state.persistence.dispose()


# ============================================================
# END: Persistence interaction
# ============================================================
