"""Phase 5.24: intent ordering, persistence, races, and public snapshots."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.events import EventType
from ava.contracts.responses import RunResponse, RunStatus
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.migrations import MigrationRunner, default_registry
from ava.infrastructure.persistence.migrations.registry import MigrationRegistry
from ava.infrastructure.persistence.repositories import RelationalRunEventRepository, RelationalRunRepository
from ava.services.run_event_store import RunEventStore
from ava.services.run_lifecycle_service import InvalidRunTransitionError, RunLifecycleService
from ava.services.run_service import CancellationRequestError, RunService
from ava.services.run_store import RunStore

T1 = datetime(2026, 9, 27, tzinfo=UTC)


@pytest.fixture(params=["memory", "relational"])
def stores(request, tmp_path):
    database = None
    if request.param == "memory":
        runs, events = RunStore(), RunEventStore()
    else:
        database = SqliteDatabase(str(tmp_path / "cancel.sqlite3"))
        runs = RelationalRunRepository(database=database)
        events = RelationalRunEventRepository(database=database)
    lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
    yield runs, events, lifecycle
    if database:
        database.dispose()


def service_for(stores, agent=None):
    runs, events, lifecycle = stores
    return RunService(agent or MockAgentAdapter(), run_repository=runs,
                      run_event_repository=events, lifecycle=lifecycle)


@pytest.mark.parametrize("status", list(RunStatus))
def test_repository_request_guard_and_stable_timestamp(stores, status):
    runs, _, _ = stores
    original = runs.create("run")
    runs.update_status("run", status)
    first = runs.request_cancellation("run", requested_at=T1)
    assert (first is not None) == status.is_active
    before = runs.get("run")
    assert before.cancellation_requested_at == (T1 if status.is_active else None)
    assert runs.request_cancellation("run", requested_at=T1 + timedelta(days=1)) is None
    assert runs.get("run") == before
    assert before.created_at == original.created_at
    assert before.status == status
    assert runs.request_cancellation("unknown", requested_at=T1) is None


@pytest.mark.parametrize("status", [RunStatus.PENDING, RunStatus.WAITING_FOR_APPROVAL])
def test_locally_controlled_runs_cancel_without_agent(stores, status):
    runs, events, lifecycle = stores
    lifecycle.create_run("run")
    lifecycle.transition("run", status)
    agent = MockAgentAdapter()

    async def forbidden(run_id):
        pytest.fail("locally controlled runs must not call an agent")

    agent.cancel_run = forbidden
    response = asyncio.run(service_for(stores, agent).cancel_run("run"))
    assert response.status == RunStatus.CANCELLED
    assert response.cancellation_requested_at == runs.get("run").cancellation_requested_at
    assert response.cancellation_requested
    assert [e.event_type for e in events.get_events("run")] == [
        EventType.RUN_CANCEL_REQUESTED, EventType.RUN_CANCELLED,
    ]


@pytest.mark.parametrize("outcome", ["cancelled", "running", "raises", "completed", "failed"])
def test_runtime_observes_committed_intent_and_outcome_races(stores, outcome):
    runs, events, lifecycle = stores
    lifecycle.create_run("run")
    lifecycle.start("run")
    agent = MockAgentAdapter()

    async def cancel(run_id):
        assert runs.get(run_id).cancellation_requested_at is not None
        if outcome == "raises":
            raise RuntimeError("private SDK detail")
        if outcome in ("completed", "failed"):
            lifecycle.transition(run_id, RunStatus(outcome))
            return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)
        return RunResponse(run_id=run_id, status=RunStatus(outcome))

    agent.cancel_run = cancel
    service = service_for(stores, agent)
    first = asyncio.run(service.cancel_run("run"))
    expected = RunStatus.RUNNING if outcome == "raises" else RunStatus(outcome)
    assert first.status == expected
    second = asyncio.run(service.cancel_run("run"))
    assert second.cancellation_requested_at == first.cancellation_requested_at
    assert runs.get("run").status == expected
    types = [e.event_type for e in events.get_events("run")]
    assert types.count(EventType.RUN_CANCEL_REQUESTED) == 1
    if expected.is_terminal:
        with pytest.raises(InvalidRunTransitionError):
            lifecycle.transition("run", RunStatus.FAILED if expected == RunStatus.CANCELLED else RunStatus.CANCELLED)
    if expected == RunStatus.CANCELLED:
        with pytest.raises(InvalidRunTransitionError):
            lifecycle.complete("run")


@pytest.mark.parametrize("reply", ["running", "raises"])
def test_cancel_reads_fresh_status_after_await(stores, reply):
    _, _, lifecycle = stores
    lifecycle.create_run("run")
    lifecycle.start("run")
    agent = MockAgentAdapter()

    async def cancel(run_id):
        lifecycle.complete(run_id)
        if reply == "raises":
            raise RuntimeError("runtime already finished")
        return RunResponse(run_id=run_id, status=RunStatus.RUNNING)

    agent.cancel_run = cancel
    assert asyncio.run(service_for(stores, agent).cancel_run("run")).status == RunStatus.COMPLETED


def test_terminal_wins_before_intent_write(stores, monkeypatch):
    runs, events, lifecycle = stores
    lifecycle.create_run("run")
    lifecycle.start("run")
    original = runs.request_cancellation

    def racing_write(run_id, *, requested_at):
        lifecycle.complete(run_id)
        return original(run_id, requested_at=requested_at)

    monkeypatch.setattr(runs, "request_cancellation", racing_write)
    response = asyncio.run(service_for(stores).cancel_run("run"))
    assert response.status == RunStatus.COMPLETED
    assert response.cancellation_requested_at is None
    assert EventType.RUN_CANCEL_REQUESTED not in [e.event_type for e in events.get_events("run")]


def test_persistence_failure_is_typed_and_does_not_invoke_runtime(stores, monkeypatch):
    runs, _, lifecycle = stores
    lifecycle.create_run("run")
    lifecycle.start("run")
    agent = MockAgentAdapter()

    def fail(*args, **kwargs):
        raise OSError("private database detail")

    async def forbidden(run_id):
        pytest.fail("runtime must not be invoked before successful persistence")

    monkeypatch.setattr(runs, "request_cancellation", fail)
    agent.cancel_run = forbidden
    with pytest.raises(CancellationRequestError, match="Unable to persist"):
        asyncio.run(service_for(stores, agent).cancel_run("run"))
    assert runs.get("run").cancellation_requested_at is None


def test_missing_event_does_not_erase_intent_or_block_runtime(stores, monkeypatch):
    runs, events, lifecycle = stores
    lifecycle.create_run("run")
    lifecycle.start("run")
    original = events.append

    def append(event):
        if event.event_type == EventType.RUN_CANCEL_REQUESTED:
            raise OSError("event store unavailable")
        return original(event)

    monkeypatch.setattr(events, "append", append)
    service = service_for(stores)
    response = asyncio.run(service.cancel_run("run"))
    assert response.status == RunStatus.RUNNING  # No live mock handle.
    assert response.cancellation_requested_at == runs.get("run").cancellation_requested_at
    assert response.cancellation_requested


def test_restart_preserves_intent_and_never_invents_a_cancellation(tmp_path):
    """A lost handle is still not proof that the run stopped.

    The intent must survive a restart untouched, and neither the restart nor a
    second cancel may turn a stranded run into ``cancelled``. The run does leave
    ``running`` here, but only because Phase 5.30 truthfully fails work whose
    execution owner was lost -- never because AVA asked a runtime that no longer
    had a handle and believed the answer.
    """
    settings = Settings(persistence_provider="relational", attachment_storage="memory",
                        persistence_database_url=str(tmp_path / "restart.sqlite3"))
    first = create_app(settings=settings)
    with TestClient(first) as client:
        runs = first.state.persistence.run_repository
        lifecycle = RunLifecycleService(run_repository=runs,
                                       run_event_repository=first.state.persistence.run_event_repository)
        lifecycle.create_run("stranded")
        lifecycle.start("stranded")
        response = client.post("/runs/stranded/cancel").json()
        assert response["status"] == "running"
        assert response["cancellation_requested_at"]
        requested_at = response["cancellation_requested_at"]
    first.state.persistence.dispose()
    second = create_app(settings=settings)
    with TestClient(second) as client:
        after_restart = client.get("/runs/stranded").json()
        assert after_restart["cancellation_requested_at"] == requested_at
        assert after_restart["status"] != "cancelled"
        assert after_restart["status"] == "failed"
        again = client.post("/runs/stranded/cancel").json()
        assert again["cancellation_requested_at"] == requested_at
        assert again["status"] == "failed"
    second.state.persistence.dispose()


@pytest.mark.parametrize("status", list(RunStatus))
def test_api_cancel_reports_actual_status_and_stable_intent(status):
    app = create_app(settings=Settings(persistence_provider="memory"))
    with TestClient(app) as client:
        runs = app.state.persistence.run_repository
        runs.create("run")
        runs.update_status("run", status)
        first = client.post("/runs/run/cancel")
        assert first.status_code == 200
        body = first.json()
        expected = "cancelled" if status in (RunStatus.PENDING, RunStatus.WAITING_FOR_APPROVAL) else status.value
        assert body["status"] == expected
        assert bool(body["cancellation_requested_at"]) == status.is_active
        assert client.post("/runs/run/cancel").json() == body
        assert client.get("/runs/run").json() == body
        unknown = client.post("/runs/unknown/cancel").json()
        assert unknown["status"] == "cancelled"
        assert unknown["cancellation_requested_at"] is None
        assert client.get("/runs/unknown").status_code == 404


def test_api_persistence_failure_is_safe(monkeypatch):
    app = create_app(settings=Settings(persistence_provider="memory"))
    with TestClient(app) as client:
        runs = app.state.persistence.run_repository
        runs.create("run")

        def fail(*args, **kwargs):
            raise OSError("secret database path")

        monkeypatch.setattr(runs, "request_cancellation", fail)
        response = client.post("/runs/run/cancel")
        assert response.status_code == 503
        assert response.json()["error_code"] == "cancellation_request_failed"
        assert "secret" not in response.text


def test_v9_upgrade_preserves_existing_runs(tmp_path):
    database = SqliteDatabase(str(tmp_path / "upgrade.sqlite3"), auto_migrate=False)
    try:
        registry = MigrationRegistry()
        for migration in default_registry():
            if migration.version < 9:
                registry.register(migration)
        MigrationRunner(database, registry).migrate()
        with database.transaction() as connection:
            connection.execute("INSERT INTO runs (run_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                               ("old", "completed", T1.isoformat(), T1.isoformat()))
        MigrationRunner(database, default_registry()).migrate()
        record = RelationalRunRepository(database=database).get("old")
        assert record.status == RunStatus.COMPLETED
        assert record.created_at == T1
        assert record.cancellation_requested_at is None
    finally:
        database.dispose()


def test_concurrent_relational_requests_have_one_winner(tmp_path):
    database = SqliteDatabase(str(tmp_path / "concurrent.sqlite3"))
    try:
        runs = RelationalRunRepository(database=database)
        runs.create("run")
        def request(n):
            other = SqliteDatabase(str(tmp_path / "concurrent.sqlite3"))
            try:
                return RelationalRunRepository(database=other).request_cancellation(
                    "run", requested_at=T1 + timedelta(seconds=n))
            finally:
                other.dispose()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(request, range(8)))
        winners = [r for r in results if r is not None]
        assert len(winners) == 1
        assert runs.get("run").cancellation_requested_at == winners[0].cancellation_requested_at
    finally:
        database.dispose()


@pytest.mark.parametrize("winner", [RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED])
def test_linked_execution_races_preserve_placeholder_and_authoritative_projection(tmp_path, winner):
    from ava.agents.contracts import AgentRunResult
    from ava.contracts.requests import RunRequest

    app = create_app(settings=Settings(
        persistence_provider="relational", attachment_storage="memory",
        persistence_database_url=str(tmp_path / "linked.sqlite3")))
    with TestClient(app) as client:
        conversation = client.post("/conversations", json={"title": "Race"}).json()["conversation_id"]
        source = client.post(f"/conversations/{conversation}/messages",
                             json={"role": "user", "content": "hello"}).json()["message_id"]
        service = app.state.run_service
        agent = MockAgentAdapter()
        service._agent = agent

        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            ids = []

            async def start(run_id, request, *, context=None):
                ids.append(run_id)
                entered.set()
                await release.wait()
                return AgentRunResult(status=RunStatus.FAILED if winner == RunStatus.FAILED else RunStatus.COMPLETED,
                                      content="answer")

            async def cancel(run_id):
                assert service.get_run(run_id).cancellation_requested_at is not None
                if winner != RunStatus.CANCELLED:
                    release.set()
                    await task
                return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)

            agent.start_run, agent.cancel_run = start, cancel
            task = asyncio.create_task(service.start_run(RunRequest(
                prompt="hello", conversation_id=conversation, source_user_message_id=source)))
            await entered.wait()
            cancelled = await service.cancel_run(ids[0])
            release.set()
            result = await task
            assert cancelled.status == result.status == winner
            assert cancelled.cancellation_requested_at == result.cancellation_requested_at
            return result

        result = asyncio.run(scenario())
        rows = client.get(f"/conversations/{conversation}/messages").json()["messages"]
        assistant = next(row for row in rows if row["role"] == "assistant")
        assert assistant["message_id"] == result.assistant_message_id
        assert assistant["status"] == ("complete" if winner == RunStatus.COMPLETED else winner.value)
        assert assistant["content"] == ("answer" if winner == RunStatus.COMPLETED else "")
        events = service.get_run_events(result.run_id)
        assert result.cancellation_requested_at is not None
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert sum(e.event_type == EventType.RUN_CANCEL_REQUESTED for e in events) == 1
        request_sequence = next(
            event.sequence for event in events if event.event_type == EventType.RUN_CANCEL_REQUESTED
        )
        terminal = service.get_run_events(result.run_id, after_sequence=request_sequence)
        assert [e.event_type for e in events if e.event_type in {
            EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED,
        }] == [EventType(f"run_{winner.value}")]
        assert terminal[-1].event_type == EventType(f"run_{winner.value}")
