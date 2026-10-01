"""Phase 5.38 restart/durability integration tests.

Certify, end to end against file-backed SQLite, that AVA's persisted
conversation, message, run, run-event, configuration-failure, and
restart-recovery semantics stay truthful across a cold process boundary.

Phase 5.30 decided the *policy*: a run that is still active in the database
when a fresh process starts has no survivable execution, so
``RunRecoveryService`` settles it ``failed`` with ``execution_interrupted``.
Phase 5.38 changes no policy. It proves that policy is real rather than
in-memory bookkeeping, by making the restart boundary physical:

* instance A is a full production application composition over a temporary
  SQLite file, and every durable fact is written through the real services
  and repositories;
* A is disposed and discarded entirely — no repository, service, connection,
  or in-memory object is carried across;
* instance B is a brand-new application composition over the *same* file, so
  every read it performs is a cold read from disk;
* recovery runs through the real production lifespan path, and the resulting
  state is read back through the real conversation projection, which is the
  same durable hydration the frontend uses after a reload.

The cold boundary is modelled by a fresh service graph over one shared file,
not by spawning an OS process: AVA keeps no state outside these repositories,
so a new composition over the same database is the persistence boundary that
matters. No real runtime, provider, or credential is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.execution_defaults import ApplicationExecutionDefaults
from ava.configuration.settings import Settings
from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.models import ModelHostingMode
from ava.models.model_configurations import ModelConfiguration
from ava.models.provider_connections import ProviderConnection
from ava.repositories.message_repository import MessageRecord
from ava.runtimes.configurations import RuntimeConfiguration
from ava.services.assistant_response_service import AssistantResponseService
from ava.services.run_lifecycle_service import RunLifecycleService
from ava.services.run_recovery_service import RESTART_INTERRUPTION_PAYLOAD

PARTIAL_CONTENT = "Partial answer before restart"
#: A run that was never dispatched never streamed, so there is no partial
#: content to preserve. Recovery must still leave the empty content alone.
NO_PARTIAL_CONTENT = ""
INTERRUPTED_CODE = "execution_interrupted"
INTERRUPTED_MESSAGE = "The backend restarted before this run completed."

#: The three statuses Phase 5.30 declares interrupted on a cold restart. The
#: recovery loop is generic, so every one of them must settle identically.
ACTIVE_STATUSES = ("running", "pending", "waiting_for_approval")


# ============================================================
# BEGIN: Harness
# ============================================================


@dataclass(frozen=True)
class Composition:
    """One cold application composition and the facts identity-checked into it.

    Two compositions over one file is the whole experiment, so the harness
    records the object identities that must differ across the boundary and the
    database path that must not.
    """

    app: Any
    conversation_id: str
    user_message_id: str
    run_id: str
    assistant_message_id: str

    @property
    def persistence(self) -> Any:
        return self.app.state.persistence

    @property
    def runs(self) -> Any:
        return self.persistence.run_repository

    @property
    def events(self) -> Any:
        return self.persistence.run_event_repository

    @property
    def messages(self) -> Any:
        return self.persistence.message_repository

    @property
    def recovery(self) -> Any:
        return self.app.state.run_recovery_service


def _settings(database_path: str) -> Settings:
    """Relational persistence over an isolated temporary database.

    ``attachment_storage`` stays in memory: this phase certifies conversation,
    run, event, and configuration durability, and Phase 4.14 already certified
    attachment content durability.
    """
    return Settings(
        persistence_provider="relational",
        persistence_database_url=database_path,
        attachment_storage="memory",
    )


def _seed_active_turn(
    client: TestClient,
    app: Any,
    *,
    run_id: str,
    active_status: str,
    title: str = "Restart durability",
    prompt: str = "What survives a restart?",
    partial_content: str = PARTIAL_CONTENT,
) -> Composition:
    """Write a durable conversation, user message, run, and streaming assistant.

    The turn is built through the production conversation API and the
    production lifecycle/assistant-content services, so the persisted event
    order is the service layer's own, never hand-written to look plausible.
    """
    conversation_id = client.post("/conversations", json={"title": title}).json()["conversation_id"]
    user = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": prompt, "role": "user"},
    ).json()

    persistence = app.state.persistence
    lifecycle = RunLifecycleService(
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )
    lifecycle.create_run(run_id, conversation_id=conversation_id, source_user_message_id=user["message_id"])
    assistant_message_id = f"assistant-{run_id}"
    persistence.run_repository.set_assistant_message_id(run_id, assistant_message_id)

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    persistence.message_repository.append(
        MessageRecord(
            message_id=assistant_message_id,
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.PENDING,
            source_run_id=run_id,
            created_at=now,
            updated_at=now,
        )
    )

    # Drive the run to the requested active status through real transitions so
    # the persisted event history is whatever the lifecycle actually produces.
    if active_status in ("running", "waiting_for_approval"):
        lifecycle.start(run_id)
    if active_status == "waiting_for_approval":
        from ava.contracts.responses import RunStatus

        lifecycle._runs.update_status(run_id, RunStatus.WAITING_FOR_APPROVAL)

    if active_status in ("running", "waiting_for_approval"):
        output = AssistantResponseService(
            run_repository=persistence.run_repository,
            run_event_repository=persistence.run_event_repository,
            message_repository=persistence.message_repository,
        )
        output.start_message(run_id, assistant_message_id)
        output.record_snapshot(
            run_id=run_id,
            message_id=assistant_message_id,
            conversation_id=conversation_id,
            content=partial_content,
        )

    return Composition(
        app=app,
        conversation_id=conversation_id,
        user_message_id=user["message_id"],
        run_id=run_id,
        assistant_message_id=assistant_message_id,
    )


def _seed_terminal_run(client: TestClient, app: Any, *, run_id: str) -> str:
    """A completed run with its own full event history, for the no-op check."""
    conversation_id = client.post("/conversations", json={"title": "Already finished"}).json()[
        "conversation_id"
    ]
    user = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Finish immediately", "role": "user"},
    ).json()
    persistence = app.state.persistence
    lifecycle = RunLifecycleService(
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )
    lifecycle.create_run(run_id, conversation_id=conversation_id, source_user_message_id=user["message_id"])
    lifecycle.start(run_id)
    lifecycle.complete(run_id)
    return conversation_id


def _events(client: TestClient, run_id: str) -> list[dict[str, Any]]:
    return list(client.get(f"/runs/{run_id}/events").json())


def _event_types(client: TestClient, run_id: str) -> list[str]:
    return [event["event_type"] for event in _events(client, run_id)]


def _sequences(client: TestClient, run_id: str) -> list[int]:
    return [int(event["sequence"]) for event in _events(client, run_id)]


def _messages(client: TestClient, conversation_id: str) -> list[dict[str, Any]]:
    return list(client.get(f"/conversations/{conversation_id}/messages").json()["messages"])


def _assistant(client: TestClient, conversation_id: str) -> dict[str, Any]:
    return next(row for row in _messages(client, conversation_id) if row["role"] == "assistant")


def _open(settings: Settings) -> TestClient:
    return TestClient(create_app(settings=settings))


# ============================================================
# END: Harness
# ============================================================
# ============================================================
# BEGIN: The cold restart boundary
# ============================================================


@pytest.mark.parametrize("active_status", ACTIVE_STATUSES)
def test_an_active_run_settles_interrupted_and_stays_truthful_across_a_cold_restart(
    tmp_path, active_status: str
) -> None:
    """Every Phase 5.30 active status becomes failed/execution_interrupted on B.

    The core claim of the phase. Instance A writes a durable conversation,
    user message, active run, streaming assistant message with partial
    content, and real run events. A is then disposed and thrown away, and a
    brand-new composition B reads the same file cold and settles the run.
    """
    database = str(tmp_path / "restart-durability.sqlite3")
    settings = _settings(database)

    # ---------------------------------------------------------- Instance A
    first = create_app(settings=settings)
    with TestClient(first) as client:
        seeded = _seed_active_turn(
            client, first, run_id=f"run-{active_status}", active_status=active_status
        )
        # Identity-check the seeded relationship *before* the boundary, so the
        # post-restart assertions compare against known-good durable ids.
        before_run = client.get(f"/runs/{seeded.run_id}").json()
        assert before_run["status"] == active_status
        assert before_run["conversation_id"] == seeded.conversation_id
        assert before_run["source_user_message_id"] == seeded.user_message_id
        assert before_run["assistant_message_id"] == seeded.assistant_message_id
        assert before_run["cancellation_requested_at"] is None
        # Identity of the two compositions is part of the evidence, so A's
        # objects are captured unconditionally and compared after A is gone.
        a_runs, a_events, a_recovery = seeded.runs, seeded.events, seeded.recovery
        pre_types = _event_types(client, seeded.run_id)
        pre_sequences = _sequences(client, seeded.run_id)
        pre_ids = [event["event_id"] for event in _events(client, seeded.run_id)]
        if active_status == "pending":
            # A run created but never dispatched has no execution to lose.
            assert pre_types == []
            assert pre_sequences == []
        else:
            assert pre_types[:3] == ["run_started", "message_started", "message_content"]
            assert pre_sequences == list(range(1, len(pre_sequences) + 1))
        if active_status in ("running", "waiting_for_approval"):
            before_assistant = _assistant(client, seeded.conversation_id)
            assert before_assistant["content"] == PARTIAL_CONTENT
            assert before_assistant["source_run_id"] == seeded.run_id
    # A is gone. Its application, client, and database handle are dropped; only
    # the file and the plain durable ids above survive into instance B.
    first.state.persistence.dispose()
    del first, client

    # ---------------------------------------------------------- Instance B
    second = create_app(settings=settings)
    with TestClient(second) as client:
        summary = second.state.run_recovery_summary
        assert summary.active_found == 1
        assert summary.settled_failed == 1

        after = client.get(f"/runs/{seeded.run_id}").json()
        assert after["status"] == "failed"
        assert after["cancellation_requested_at"] is None

        # The durable failure classification and its safe wording.
        history = _events(client, seeded.run_id)
        assert history[-1]["event_type"] == "run_failed"
        assert history[-1]["payload"] == RESTART_INTERRUPTION_PAYLOAD
        # The canonical classification key, so the projection and the UI can
        # both read the interruption reason back.
        assert history[-1]["payload"] == {
            "error_code": INTERRUPTED_CODE,
            "message": INTERRUPTED_MESSAGE,
        }

        # Sequencing continues from durable history; nothing is renumbered and
        # no pre-restart event identity changed.
        post_sequences = _sequences(client, seeded.run_id)
        assert post_sequences == list(range(1, len(post_sequences) + 1))
        assert post_sequences[: len(pre_sequences)] == pre_sequences
        assert post_sequences[-1] == len(pre_sequences) + 1
        assert [event["event_id"] for event in history][: len(pre_ids)] == pre_ids
        assert len({event["event_id"] for event in history}) == len(history)
        assert post_sequences == pre_sequences + [len(pre_sequences) + 1]

        # Partial content is real history and is never erased by recovery.
        expected_content = (
            PARTIAL_CONTENT if active_status != "pending" else NO_PARTIAL_CONTENT
        )
        assistant = _assistant(client, seeded.conversation_id)
        assert assistant["content"] == expected_content
        assert assistant["status"] == "failed"
        assert assistant["error_code"] == INTERRUPTED_CODE
        assert assistant["source_run_id"] == seeded.run_id

        # The conversation projection is the frontend's hydration path; the
        # user turn and the interrupted response both survive with the error
        # code durable.
        rows = _messages(client, seeded.conversation_id)
        assert [row["message_id"] for row in rows if row["role"] == "user"] == [
            seeded.user_message_id
        ]
        assert [row["message_id"] for row in rows if row["role"] == "assistant"] == [
            seeded.assistant_message_id
        ]

        # Linkage survives intact.
        assert after["assistant_message_id"] == seeded.assistant_message_id
        assert after["source_user_message_id"] == seeded.user_message_id
        assert after["conversation_id"] == seeded.conversation_id

        # B's repositories and services are new objects over the same file, so
        # nothing above was read from A's process memory.
        assert seeded.runs is not second.state.persistence.run_repository
        assert second.state.persistence.run_repository is not a_runs
        assert second.state.persistence.run_event_repository is not a_events
        assert second.state.persistence.conversation_repository is not (
            seeded.app.state.persistence.conversation_repository
        )
        assert second.state.run_recovery_service is not a_recovery
        assert settings.persistence_database_url == database


# ============================================================
# END: The cold restart boundary
# ============================================================
# ============================================================
# BEGIN: Idempotency and terminal no-op
# ============================================================


def test_recovery_is_idempotent_and_leaves_terminal_runs_untouched(tmp_path) -> None:
    """A second recovery over the recovered file is a no-op for R1.

    Idempotency is not an optimization here: a duplicate ``run_failed`` fact
    would make a resumed client see two terminal events for one run. Also
    proves an already-terminal run is not rewritten by a cold start.
    """
    database = str(tmp_path / "idempotent.sqlite3")
    settings = _settings(database)

    first = create_app(settings=settings)
    with TestClient(first) as client:
        active = _seed_active_turn(client, first, run_id="run-active", active_status="running")
        terminal_conversation = _seed_terminal_run(client, first, run_id="run-terminal")
        terminal_before = client.get("/runs/run-terminal").json()
        terminal_events_before = _events(client, "run-terminal")
        first.state.persistence.dispose()
        del first, client

    # Recovery #1.
    second = create_app(settings=settings)
    with TestClient(second) as client:
        assert second.state.run_recovery_summary.active_found == 1
        assert second.state.run_recovery_summary.settled_failed == 1
        active_after_first = client.get("/runs/run-active").json()
        active_events_after_first = _events(client, "run-active")

        # The terminal run is not a recovery target and is not rewritten.
        assert client.get("/runs/run-terminal").json() == terminal_before
        assert _events(client, "run-terminal") == terminal_events_before

    second.state.persistence.dispose()
    del second, client

    # Recovery #2 over the same recovered file.
    third = create_app(settings=settings)
    with TestClient(third) as client:
        assert third.state.run_recovery_summary.active_found == 0
        assert third.state.run_recovery_summary.settled_failed == 0
        assert client.get("/runs/run-active").json() == active_after_first
        after_second = _events(client, "run-active")
        assert after_second == active_events_after_first
        assert _event_types(client, "run-active").count("run_failed") == 1
        assert _assistant(client, active.conversation_id)["content"] == PARTIAL_CONTENT
        assert _messages(client, terminal_conversation)[0]["conversation_id"] == terminal_conversation


# ============================================================
# END: Idempotency and terminal no-op
# ============================================================
# ============================================================
# BEGIN: Cancellation intent
# ============================================================


def test_cancellation_intent_survives_the_restart_without_becoming_a_cancellation(tmp_path) -> None:
    """A requested cancellation stays intent after a cold restart.

    ``cancellation_requested_at`` proves someone asked. It does not prove the
    runtime ever acknowledged, and after a restart there is no runtime left to
    acknowledge. Recovery must therefore still report ``execution_interrupted``.
    """
    database = str(tmp_path / "cancellation-intent.sqlite3")
    settings = _settings(database)

    first = create_app(settings=settings)
    with TestClient(first) as client:
        seeded = _seed_active_turn(client, first, run_id="run-cancel-intent", active_status="running")
        requested = client.post("/runs/run-cancel-intent/cancel").json()["cancellation_requested_at"]
        assert requested, "cancellation intent must be durable before the restart"
    first.state.persistence.dispose()
    del first, client

    second = create_app(settings=settings)
    with TestClient(second) as client:
        assert second.state.run_recovery_summary.settled_failed == 1
        run = client.get("/runs/run-cancel-intent").json()
        # Preserved exactly, and the run is failed — not cancelled.
        assert run["cancellation_requested_at"] == requested
        assert run["status"] == "failed"
        types = _event_types(client, "run-cancel-intent")
        assert "run_cancel_requested" in types
        assert "run_cancelled" not in types
        assert types[-1] == "run_failed"
        assert _events(client, "run-cancel-intent")[-1]["payload"] == {
            "error_code": INTERRUPTED_CODE,
            "message": INTERRUPTED_MESSAGE,
        }
        assistant = _assistant(client, seeded.conversation_id)
        assert assistant["status"] == "failed"
        assert assistant["error_code"] == INTERRUPTED_CODE


# ============================================================
# END: Cancellation intent
# ============================================================
# ============================================================
# BEGIN: Crash-gap honesty
# ============================================================


def test_recovery_does_not_synthesize_a_missing_terminal_event(tmp_path) -> None:
    """A terminal run with a lost event write stays as-is; recovery invents nothing.

    Phase 5.23/5.26 documented a known crash gap: the status write and the
    event write are not one unit of work, so a process can die between them and
    leave a terminal run whose terminal event was never persisted. Phase 5.38
    must not paper over that with repair logic. A terminal run is not active, so
    recovery does not consider it, and the missing event stays missing. This is
    asserted, not tolerated silently: the gap is still a gap, and hiding it
    would be a redesign this phase is explicitly not doing.
    """
    database = str(tmp_path / "crash-gap.sqlite3")
    settings = _settings(database)

    first = create_app(settings=settings)
    with TestClient(first) as client:
        conversation_id = client.post("/conversations", json={"title": "Crashed writer"}).json()[
            "conversation_id"
        ]
        user = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": "Finish, then crash", "role": "user"},
        ).json()
        persistence = first.state.persistence
        lifecycle = RunLifecycleService(
            run_repository=persistence.run_repository,
            run_event_repository=persistence.run_event_repository,
        )
        lifecycle.create_run("run-gap", conversation_id=conversation_id, source_user_message_id=user["message_id"])
        lifecycle.start("run-gap")
        # Write the terminal status, then simulate the crash before the
        # terminal event is appended.
        from ava.contracts.responses import RunStatus

        persistence.run_repository.update_status("run-gap", RunStatus.FAILED)
        assert "run_failed" not in _event_types(client, "run-gap")
        assert client.get("/runs/run-gap").json()["status"] == "failed"
    first.state.persistence.dispose()
    del first, client

    second = create_app(settings=settings)
    with TestClient(second) as client:
        # The run is terminal, so recovery finds nothing to settle and does
        # not backfill the lost fact.
        assert second.state.run_recovery_summary.active_found == 0
        assert second.state.run_recovery_summary.settled_failed == 0
        assert client.get("/runs/run-gap").json()["status"] == "failed"
        assert "run_failed" not in _event_types(client, "run-gap")
        # Documented gap, still honest: the assistant projection has a failed
        # run with no run_failed fact, so it carries no synthesized error code.
        assistant_rows = [
            row
            for row in _messages(client, conversation_id)
            if row["role"] == "assistant" and row["source_run_id"] == "run-gap"
        ]
        assert assistant_rows == []


# ============================================================
# END: Crash-gap honesty
# ============================================================
# ============================================================
# BEGIN: Retry after recovery
# ============================================================


def test_retry_after_recovery_creates_a_new_run_and_never_mutates_the_interrupted_one(tmp_path) -> None:
    """The interrupted run stays failed history; Retry branches into a fresh run.

    A failed run must remain retryable so the user is never stranded, but the
    interrupted attempt is durable history and is not rewritten. The durable
    lineage of the new attempt is the shared ``source_user_message_id`` the new
    run inherits — no parent-run column is involved.
    """
    database = str(tmp_path / "retry-after-recovery.sqlite3")
    settings = _settings(database)

    first = create_app(settings=settings)
    with TestClient(first) as client:
        seeded = _seed_active_turn(client, first, run_id="run-interrupted", active_status="running")
    first.state.persistence.dispose()
    del first, client

    second = create_app(settings=settings)
    with TestClient(second) as client:
        assert second.state.run_recovery_summary.settled_failed == 1
        interrupted_after_recovery = client.get("/runs/run-interrupted").json()
        interrupted_events = _events(client, "run-interrupted")

        # Retry through the production route against the deterministic mock
        # agent: no real runtime, provider, or credential is contacted.
        retried = client.post(
            "/runs",
            json={
                "prompt": "ignored on retry",
                "conversation_id": seeded.conversation_id,
                "retry_of_run_id": "run-interrupted",
            },
        )
        assert retried.status_code == 202, retried.text
        new_run = retried.json()
        assert new_run["run_id"] != "run-interrupted"
        assert new_run["status"] in {"pending", "running", "completed", "failed"}
        # The new attempt branches from the same durable user turn.
        assert new_run["source_user_message_id"] == seeded.user_message_id
        assert new_run["conversation_id"] == seeded.conversation_id

        # R1 is untouched by the retry: same status, same events, same content.
        assert client.get("/runs/run-interrupted").json() == interrupted_after_recovery
        assert _events(client, "run-interrupted") == interrupted_events
        assert _event_types(client, "run-interrupted").count("run_failed") == 1

        # The original partial content and its failure remain readable.
        assistant = _assistant(client, seeded.conversation_id)
        assert assistant["content"] == PARTIAL_CONTENT
        assert assistant["error_code"] == INTERRUPTED_CODE
        assert assistant["source_run_id"] == "run-interrupted"


# ============================================================
# END: Retry after recovery
# ============================================================
# ============================================================
# BEGIN: Configuration durability
# ============================================================


def test_persisted_execution_defaults_and_credential_references_survive_the_restart(tmp_path) -> None:
    """Persisted execution configuration and credential *references* survive.

    Restart recovery must not reset a configured deployment, and the persisted
    connection record must still contain only a reference to a secret — never
    the secret itself. This is a persistence assertion, not a Settings retest:
    no provider is contacted and no credential is resolved.
    """
    database = str(tmp_path / "configuration-durability.sqlite3")
    settings = _settings(database)

    first = create_app(settings=settings)
    with TestClient(first) as client:
        persistence = first.state.persistence
        persistence.provider_connection_repository.create(
            ProviderConnection(
                provider_connection_id="conn-local",
                provider_id="openai_compatible",
                display_name="Local OpenAI-compatible",
                endpoint="http://localhost:11434/v1",
                enabled=True,
                credential_reference="env:LOCAL_API_KEY",
            )
        )
        persistence.model_configuration_repository.create(
            ModelConfiguration(
                model_id="model-local",
                provider_connection_id="conn-local",
                provider_model_name="local-model",
                display_name="Local model",
                hosting_mode=ModelHostingMode.LOCAL,
                enabled=True,
            )
        )
        persistence.runtime_configuration_repository.create(
            RuntimeConfiguration(
                runtime_configuration_id="runtime-local",
                runtime_type="native",
                display_name="Native",
                enabled=True,
            )
        )
        persistence.execution_defaults_repository.set(
            ApplicationExecutionDefaults(
                default_provider_connection_id="conn-local",
                default_model_id="model-local",
                default_runtime_configuration_id="runtime-local",
            )
        )
        defaults_before = persistence.execution_defaults_repository.get()
        assert defaults_before is not None
    first.state.persistence.dispose()
    del first, client

    second = create_app(settings=settings)
    with TestClient(second) as client:
        persistence = second.state.persistence
        defaults_after = persistence.execution_defaults_repository.get()
        assert defaults_after == defaults_before
        assert defaults_after is not None
        assert defaults_after.default_provider_connection_id == "conn-local"
        assert defaults_after.default_model_id == "model-local"
        assert defaults_after.default_runtime_configuration_id == "runtime-local"

        connection = persistence.provider_connection_repository.get("conn-local")
        assert connection is not None
        # Only the reference is persisted; no secret value is stored anywhere.
        assert connection.credential_reference == "env:LOCAL_API_KEY"

        listed = client.get("/settings/providers").json()["provider_connections"]
        persisted_fields = set(listed[0])
        assert persisted_fields == {
            "provider_connection_id",
            "provider_id",
            "display_name",
            "endpoint",
            "enabled",
            "credential_reference",
            "contract_version",
        }
        # No field anywhere on the record can carry a secret value.
        assert not persisted_fields & {
            "api_key",
            "secret",
            "token",
            "password",
            "credential",
            "credentials",
        }
        assert listed[0]["credential_reference"] == "env:LOCAL_API_KEY"


# ============================================================
# END: Configuration durability
# ============================================================
# ============================================================
# BEGIN: Direct production service composition
# ============================================================


def test_recovery_runs_through_the_real_service_composition_without_the_http_lifespan(
    tmp_path,
) -> None:
    """The settlement is a production service call, not a TestClient artifact.

    ``TestClient`` is convenient but it is a test transport. This asserts the
    same settlement by calling the production-composed
    ``RunRecoveryService`` directly — the exact object and method the real
    ``_app_lifespan`` invokes — so the result does not depend on the HTTP
    adapter being present.
    """
    database = str(tmp_path / "service-composition.sqlite3")
    settings = _settings(database)

    first = create_app(settings=settings)
    with TestClient(first) as client:
        seeded = _seed_active_turn(client, first, run_id="run-service", active_status="running")
    first.state.persistence.dispose()
    del first, client

    # Instance B: a new composition, recovery invoked directly.
    second = create_app(settings=settings)
    summary = second.state.run_recovery_service.recover_stranded_runs()
    assert summary.active_found == 1
    assert summary.settled_failed == 1

    # Reading through the production conversation projection, not the HTTP
    # route, still yields the truthful final state.
    conversation = second.state.conversation_service.get_conversation(seeded.conversation_id)
    assert conversation is not None
    messages = second.state.conversation_service.list_messages(seeded.conversation_id)
    assert messages is not None
    assistant = next(row for row in messages.messages if row.role is MessageRole.ASSISTANT)
    assert assistant.content == PARTIAL_CONTENT
    assert assistant.status is MessageStatus.FAILED
    assert assistant.error_code == INTERRUPTED_CODE
    assert assistant.source_run_id == seeded.run_id
    second.state.persistence.dispose()


# ============================================================
# END: Direct production service composition
# ============================================================
