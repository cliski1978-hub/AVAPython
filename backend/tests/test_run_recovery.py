"""Phase 5.30 cold-start stranded-run recovery.

A restart cannot be silent about lost work. These tests pin what AVA does with
a run that is still active in the database when a fresh process starts: it
settles the run through the lifecycle authority, it says *why* it did, and it
does not touch anything the user can still see.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.events import EventType, RunEvent
from ava.contracts.responses import RunStatus
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
    assert runs.get("active").updated_at > before.updated_at
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


def test_a_port_without_active_listing_settles_nothing_instead_of_crashing() -> None:
    """``list_active`` defaults to empty so older ports stay source-compatible.

    A third-party repository that predates cold-start recovery must degrade to
    "nothing to converge" rather than break application startup.
    """

    class LegacyRunRepository(RunRepository):
        """Minimal port implementation without the recovery query."""

        def __init__(self) -> None:
            self._records: dict[str, RunRecord] = {}

        def create(self, run_id, *, conversation_id=None, source_user_message_id=None):
            now = datetime.now(UTC)
            self._records[run_id] = RunRecord(
                run_id=run_id, status=RunStatus.PENDING, conversation_id=conversation_id,
                source_user_message_id=source_user_message_id, execution_selection=None,
                cancellation_requested_at=None, created_at=now, updated_at=now,
            )
            return self._records[run_id]

        def get(self, run_id):
            return self._records.get(run_id)

        def list_run_ids(self):
            return list(self._records)

        def update_status(self, run_id, status):
            record = self._records.get(run_id)
            if record is None:
                return None
            updated = record.__class__(**{**record.__dict__, "status": status})
            self._records[run_id] = updated
            return updated

        def set_execution_selection(self, run_id, selection):
            del selection
            return self._records.get(run_id)

        def set_assistant_message_id(self, run_id, message_id):
            del message_id
            return self._records.get(run_id)

        def request_cancellation(self, run_id, *, requested_at=None):
            del run_id, requested_at
            return None

        def compare_and_set_status(self, run_id, *, from_status, to_status):
            del run_id, from_status, to_status
            return None

    runs = LegacyRunRepository()
    runs.create("run")
    assert list(runs.list_active()) == []  # the compatibility default

    events = RunEventStore()
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    summary = RunRecoveryService(run_repository=runs, lifecycle=lifecycle).recover_stranded_runs()

    assert (summary.active_found, summary.settled_failed) == (0, 0)
    assert events.get_events("run") == []
    assert runs.get("run").status is RunStatus.PENDING


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
