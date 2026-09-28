"""Run/run-event persistence activation tests (Step 4.8).

``AVA_PERSISTENCE=memory`` (the default) selects the in-memory stores;
``AVA_PERSISTENCE=relational`` selects the durable relational adapters. The
application selects persistence only through ``create_application_persistence`` in the
composition layer; ``RunService`` consumes only the two repository ports.

The durability proof is the application-level restart: a run and its event
stream written through one application survive ``dispose()`` and are re-read
through a second application over the same database file. The behavioral
equivalence tests drive the same run-domain scenarios through both
compositions to show the two implementations are interchangeable.
"""

import asyncio
import sqlite3
from uuid import uuid4

import pytest

from ava.agents.adapters.mock.mock_agent import MockAgentAdapter
from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.conversations import RunContext
from ava.contracts.events import EventType, RunEvent
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.models import ModelHostingMode
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.infrastructure.composition import ApplicationPersistence, create_application_persistence
from ava.infrastructure.persistence.repositories import (
    RelationalProviderConnectionRepository,
    RelationalRunEventRepository,
    RelationalRunRepository,
    RelationalRuntimeConfigurationRepository,
)
from ava.services.provider_connection_store import ProviderConnectionStore
from ava.services.run_event_store import RunEventStore
from ava.services.run_service import RunService
from ava.services.run_store import RunStore
from ava.services.runtime_configuration_store import RuntimeConfigurationStore

PROMPT = "Hello AVA"

# ============================================================
# BEGIN: Helpers
# ============================================================


def relational_settings(database_url: str) -> Settings:
    """Build relational Settings pointing at ``database_url``."""
    return Settings(
        persistence_provider="relational",
        persistence_database_url=database_url,
    )


def memory_settings() -> Settings:
    """Build the default (memory) Settings."""
    return Settings()


MODE_TO_SETTINGS = {
    "memory": lambda path: memory_settings(),
    "relational": lambda path: relational_settings(str(path / "ava.sqlite3")),
}


def compose_persistence(mode: str, tmp_path) -> ApplicationPersistence:
    """Build the persistence selection the application would compose."""
    return create_application_persistence(MODE_TO_SETTINGS[mode](tmp_path))


def compose_service(mode: str, tmp_path, adapter) -> tuple[RunService, ApplicationPersistence]:
    """Compose the RunService the application wires, over the selected persistence."""
    persistence = compose_persistence(mode, tmp_path)
    service = RunService(
        adapter,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )
    return service, persistence


def run_event_types(service: RunService, run_id: str) -> list[EventType]:
    """Return the event types recorded for a run through the service."""
    events = service.get_run_events(run_id)
    assert events is not None
    return [event.event_type for event in events]


class SelectionMockAgent(MockAgentAdapter):
    """A mock agent that reports an execution selection for its runs."""

    def __init__(self, selection: RunExecutionSelection) -> None:
        super().__init__()
        self._selection = selection

    async def start_run(
        self, run_id: str, request: RunRequest, *, context: RunContext | None = None
    ):
        result = await super().start_run(run_id, request, context=context)
        return result.model_copy(update={"execution_selection": self._selection})


# ============================================================
# END: Helpers
# ============================================================


# ============================================================
# BEGIN: Composition Selection
# ============================================================


def test_default_persistence_provider_selects_the_in_memory_stores() -> None:
    """The unconfigured default stays memory: RunStore/RunEventStore, no database."""
    persistence = create_application_persistence(memory_settings())
    assert isinstance(persistence.run_repository, RunStore)
    assert isinstance(persistence.run_event_repository, RunEventStore)
    assert isinstance(persistence.provider_connection_repository, ProviderConnectionStore)
    assert isinstance(persistence.runtime_configuration_repository, RuntimeConfigurationStore)
    assert persistence.database is None


def test_default_application_installs_the_in_memory_stores() -> None:
    """A default-created application wires the in-memory stores through composition."""
    app = create_app()
    persistence = app.state.persistence
    assert isinstance(persistence.run_repository, RunStore)
    assert isinstance(persistence.run_event_repository, RunEventStore)
    assert persistence.database is None


def test_relational_settings_select_the_relational_adapters(tmp_path) -> None:
    """Relational settings wire the durable adapters and an owned database."""
    persistence = create_application_persistence(
        relational_settings(str(tmp_path / "ava.sqlite3"))
    )
    assert isinstance(persistence.run_repository, RelationalRunRepository)
    assert isinstance(persistence.run_event_repository, RelationalRunEventRepository)
    assert isinstance(persistence.provider_connection_repository, RelationalProviderConnectionRepository)
    assert isinstance(persistence.runtime_configuration_repository, RelationalRuntimeConfigurationRepository)
    assert persistence.database is not None
    persistence.dispose()


def test_relational_application_wires_the_relational_adapters(tmp_path) -> None:
    """A relational-configured application selects the durable adapters."""
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))
    app = create_app(settings=settings)
    persistence = app.state.persistence
    assert isinstance(persistence.run_repository, RelationalRunRepository)
    assert isinstance(persistence.run_event_repository, RelationalRunEventRepository)
    assert isinstance(persistence.provider_connection_repository, RelationalProviderConnectionRepository)
    assert isinstance(persistence.runtime_configuration_repository, RelationalRuntimeConfigurationRepository)
    assert persistence.database is not None
    persistence.dispose()


def test_unknown_persistence_provider_fails_construction() -> None:
    """An unknown provider is a configuration error, never a silent fallback."""
    with pytest.raises(ValueError):
        create_application_persistence(Settings(persistence_provider="bogus"))


def test_unavailable_relational_database_fails_application_construction(tmp_path) -> None:
    """A relational database that cannot be opened fails startup, not runtime."""
    settings = relational_settings(str(tmp_path))
    with pytest.raises(sqlite3.OperationalError):
        create_app(settings=settings)


def test_run_persistence_dispose_is_safe_to_repeat(tmp_path) -> None:
    """dispose() is idempotent so shutdown can never double-close a resource."""
    persistence = compose_persistence("relational", tmp_path)
    persistence.dispose()
    persistence.dispose()


# ============================================================
# END: Composition Selection
# ============================================================


# ============================================================
# BEGIN: Application Restart Durability
# ============================================================


def test_run_persists_across_application_restarts(tmp_path) -> None:
    """A completed run and its event stream survive a full application restart.

    The first application writes the run over the relational composition; its
    lifespan shutdown disposes the database. A second application over the same
    database file must expose the identical run snapshot and event sequence.
    """
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))

    with _client(settings) as client:
        body = client.post("/runs", json={"prompt": PROMPT}).json()
        assert body["status"] == "running"
        body = client.get(f"/runs/{body['run_id']}").json()
        assert body["status"] == "completed"
        run_id = body["run_id"]
        first_events = [e["event_type"] for e in client.get(f"/runs/{run_id}/events").json()]

    with _client(settings) as client:
        run = client.get(f"/runs/{run_id}")
        assert run.status_code == 200
        assert run.json()["status"] == "completed"
        events = client.get(f"/runs/{run_id}/events").json()
        assert [e["event_type"] for e in events] == first_events
        assert [e["event_type"] for e in events] == [
            "run_started",
            "message_started",
            "message_content",
            "run_completed",
        ]
        assert events[2]["payload"]["content"] == f"AVA mock agent received: {PROMPT}"


def test_failed_run_persists_across_application_restarts(tmp_path) -> None:
    """A failed run and its run_failed payload survive the restart."""
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))
    adapter = MockAgentAdapter(fail_on_prompt=PROMPT)

    persistence = create_application_persistence(settings)
    service = RunService(
        adapter,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )
    async def start_failing_run() -> str:
        response = await service.start_run(RunRequest(prompt=PROMPT))
        return response.run_id

    run_id = asyncio.run(start_failing_run())
    persistence.dispose()

    with _client(settings) as client:
        run = client.get(f"/runs/{run_id}")
        assert run.status_code == 200
        assert run.json()["status"] == "failed"
        events = client.get(f"/runs/{run_id}/events").json()
        assert [e["event_type"] for e in events] == [
            "run_started", "message_started", "run_failed",
        ]
        assert events[-1]["payload"]["error_code"] == "agent_failed"
        assert events[-1]["payload"]["recoverable"] is False


def test_cancelled_run_persists_across_application_restarts(tmp_path) -> None:
    """A cancelled run and its run_cancelled event survive the restart."""
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))
    adapter = MockAgentAdapter(run_delay=0.1)
    persistence = create_application_persistence(settings)
    service = RunService(
        adapter,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )

    async def cancel_during_run() -> str:
        task = asyncio.create_task(service.start_run(RunRequest(prompt=PROMPT)))
        await asyncio.sleep(0.01)
        (run_id,) = adapter.active_run_ids()
        cancel_response = await service.cancel_run(run_id)
        await task
        assert cancel_response.status == RunStatus.CANCELLED
        return run_id

    run_id = asyncio.run(cancel_during_run())
    persistence.dispose()

    with _client(settings) as client:
        run = client.get(f"/runs/{run_id}")
        assert run.status_code == 200
        assert run.json()["status"] == "cancelled"
        events = client.get(f"/runs/{run_id}/events").json()
        assert [e["event_type"] for e in events] == [
            "run_started", "message_started", "run_cancel_requested", "run_cancelled",
        ]


def test_multiple_run_event_streams_persist_isolated(tmp_path) -> None:
    """Two runs stay event-isolated across an application restart."""
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))

    with _client(settings) as client:
        first = client.post("/runs", json={"prompt": "run one"}).json()
        second = client.post("/runs", json={"prompt": "run two"}).json()
        first_events = [e["event_type"] for e in client.get(f"/runs/{first['run_id']}/events").json()]
        second_events = [e["event_type"] for e in client.get(f"/runs/{second['run_id']}/events").json()]

    with _client(settings) as client:
        for run_id, expected in ((first["run_id"], first_events), (second["run_id"], second_events)):
            run = client.get(f"/runs/{run_id}")
            assert run.status_code == 200
            assert run.json()["status"] == "completed"
            events = client.get(f"/runs/{run_id}/events").json()
            assert [e["event_type"] for e in events] == expected
            assert all(e["run_id"] == run_id for e in events)


# ============================================================
# END: Application Restart Durability
# ============================================================


# ============================================================
# BEGIN: Behavioral Equivalence (memory vs relational)
# ============================================================


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_completed_run_lifecycle_matches_in_both_modes(mode, tmp_path) -> None:
    """A successful run emits the same lifecycle in both persistence modes."""

    service, persistence = compose_service(mode, tmp_path, MockAgentAdapter())
    try:
        async def scenario():
            response = await service.start_run(RunRequest(prompt=PROMPT))
            assert response.status == RunStatus.COMPLETED
            assert run_event_types(service, response.run_id) == [
                EventType.RUN_STARTED,
                EventType.MESSAGE_STARTED,
                EventType.MESSAGE_CONTENT,
                EventType.RUN_COMPLETED,
            ]

        asyncio.run(scenario())
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_failed_run_lifecycle_matches_in_both_modes(mode, tmp_path) -> None:
    """A failed run emits run_started → run_failed with the safe payload."""

    service, persistence = compose_service(
        mode, tmp_path, MockAgentAdapter(fail_on_prompt=PROMPT)
    )
    try:
        async def scenario():
            response = await service.start_run(RunRequest(prompt=PROMPT))
            assert response.status == RunStatus.FAILED
            assert run_event_types(service, response.run_id) == [
                EventType.RUN_STARTED,
                EventType.MESSAGE_STARTED,
                EventType.RUN_FAILED,
            ]

        asyncio.run(scenario())
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_cancelled_run_lifecycle_matches_in_both_modes(mode, tmp_path) -> None:
    """A cancelled run emits started → cancel_requested → cancelled in both modes."""

    adapter = MockAgentAdapter(run_delay=0.1)
    service, persistence = compose_service(mode, tmp_path, adapter)
    try:
        async def scenario():
            task = asyncio.create_task(service.start_run(RunRequest(prompt=PROMPT)))
            await asyncio.sleep(0.01)
            (run_id,) = adapter.active_run_ids()
            cancel_response = await service.cancel_run(run_id)
            start_response = await task
            assert cancel_response.status == RunStatus.CANCELLED
            assert start_response.status == RunStatus.CANCELLED
            assert run_event_types(service, run_id) == [
                EventType.RUN_STARTED,
                EventType.MESSAGE_STARTED,
                EventType.RUN_CANCEL_REQUESTED,
                EventType.RUN_CANCELLED,
            ]

        asyncio.run(scenario())
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_terminal_runs_are_sealed_in_both_modes(mode, tmp_path) -> None:
    """A completed run reports its recorded status without new events."""

    service, persistence = compose_service(mode, tmp_path, MockAgentAdapter())
    try:
        async def scenario():
            response = await service.start_run(RunRequest(prompt=PROMPT))
            sealed = await service.cancel_run(response.run_id)
            assert sealed.status == RunStatus.COMPLETED
            assert run_event_types(service, response.run_id)[-1] == EventType.RUN_COMPLETED

        asyncio.run(scenario())
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_unknown_run_reads_and_cancel_are_consistent(mode, tmp_path) -> None:
    """Unknown runs behave identically across modes (no events, idempotent cancel)."""

    service, persistence = compose_service(mode, tmp_path, MockAgentAdapter())
    try:
        run_id = str(uuid4())
        async def scenario():
            assert service.get_run(run_id) is None
            assert service.get_run_events(run_id) is None
            cancel_response = await service.cancel_run(run_id)
            assert cancel_response.status == RunStatus.CANCELLED
            assert persistence.run_event_repository.get_events(run_id) == []
            assert service.get_run(run_id) is None

        asyncio.run(scenario())
    finally:
        persistence.dispose()


@pytest.mark.parametrize("mode", ["memory", "relational"])
def test_second_terminal_event_append_is_ignored(mode, tmp_path) -> None:
    """A redundant terminal append is idempotent in both modes."""

    service, persistence = compose_service(mode, tmp_path, MockAgentAdapter())
    try:
        async def scenario():
            response = await service.start_run(RunRequest(prompt=PROMPT))
            original = run_event_types(service, response.run_id)
            assert original[-1] == EventType.RUN_COMPLETED
            duplicate = RunEvent(
                event_id=str(uuid4()),
                run_id=response.run_id,
                event_type=EventType.RUN_COMPLETED,
            )
            persistence.run_event_repository.append(duplicate)
            assert run_event_types(service, response.run_id) == original

        asyncio.run(scenario())
    finally:
        persistence.dispose()


# ============================================================
# END: Behavioral Equivalence
# ============================================================


# ============================================================
# BEGIN: Execution Selection Durability
# ============================================================


def test_execution_selection_persists_across_application_restarts(tmp_path) -> None:
    """A run's resolved execution identity survives the restart with full fidelity."""
    settings = relational_settings(str(tmp_path / "ava.sqlite3"))
    selection = RunExecutionSelection(
        runtime_id="native",
        model_provider_id="local",
        model_id="model-a",
        hosting_mode=ModelHostingMode.LOCAL,
    )
    adapter = SelectionMockAgent(selection)
    persistence = create_application_persistence(settings)
    service = RunService(
        adapter,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )

    async def start_selected_run() -> str:
        response: RunResponse = await service.start_run(RunRequest(prompt=PROMPT))
        assert response.execution_selection == selection
        return response.run_id

    run_id = asyncio.run(start_selected_run())
    persistence.dispose()

    with _client(settings) as client:
        run = client.get(f"/runs/{run_id}")
        assert run.status_code == 200
        body = run.json()
        assert body["status"] == "completed"
        assert body["execution_selection"] == {
            "runtime_id": "native",
            "model_provider_id": "local",
            "model_id": "model-a",
            "hosting_mode": "local",
            "contract_version": body["contract_version"],
        }


# ============================================================
# END: Execution Selection Durability
# ============================================================


def _client(settings: Settings):
    """A TestClient bound to an application composed over ``settings``."""
    from fastapi.testclient import TestClient

    return TestClient(create_app(settings=settings))
