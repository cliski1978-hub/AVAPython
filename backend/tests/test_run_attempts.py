"""Phase 5.31 retry / regenerate across persisted runs.

Drives the real run path over relational persistence — the real ``RunService``,
the real lifecycle authority, the real context construction service, and fake
agents — to pin the phase's central rule::

    old run          = immutable history
    retry / regenerate = a new run

Every assertion here is read back from authoritative persistence (the run,
event, and message repositories through their wire contracts) or from what the
agent was actually handed, never from an in-memory shortcut. No network is used.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from ava.agents.contracts import AgentPort, AgentRunResult
from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.attempts import can_be_superseded, can_regenerate, can_retry
from ava.contracts.conversations import ContextMessage, MessageRole
from ava.contracts.events import EventType
from ava.contracts.execution import RunExecutionSelection
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunResponse, RunStatus
from ava.services.run_lifecycle_service import RunLifecycleService
from ava.services.run_recovery_service import RESTART_INTERRUPTION_PAYLOAD
from ava.services.run_service import RunService

_TERMINAL_TIMEOUT_SECONDS = 5.0

# ============================================================
# BEGIN: Fakes
# ============================================================


@dataclass
class ScriptedAgent(AgentPort):
    """Agent whose per-run outcome, content, and received context the test scripts.

    ``outcomes`` and ``contents`` are consumed in order, so a test can make a
    first attempt fail and its retry succeed, or complete three regenerations in
    a row. The last entry repeats once the script is exhausted.
    """

    __test__ = False
    outcomes: list[RunStatus] = field(default_factory=list)
    contents: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    contexts: list[list[ContextMessage]] = field(default_factory=list)
    selections: list[RunExecutionSelection] = field(default_factory=list)
    _index: int = 0

    def name(self) -> str:
        return "scripted"

    def get_capabilities(self) -> set:
        return set()

    async def start_run(
        self, run_id: str, request: RunRequest, *, context: object = None
    ) -> AgentRunResult:
        del run_id
        index = self._index
        self._index += 1
        self.prompts.append(request.prompt)
        self.contexts.append(list(context.messages) if context is not None else [])
        status = (
            self.outcomes[index]
            if index < len(self.outcomes)
            else (self.outcomes[-1] if self.outcomes else RunStatus.COMPLETED)
        )
        content = (
            self.contents[index]
            if index < len(self.contents)
            else f"answer-{index + 1}"
        )
        selection = self.selections[index] if index < len(self.selections) else None
        return AgentRunResult(
            status=status, content=content, execution_selection=selection
        )

    async def cancel_run(self, run_id: str) -> RunResponse:
        return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)


class _BlockingAgent(AgentPort):
    """Agent that never returns until released, so its run stays active.

    It is released only by the test itself. ``TestClient`` runs a request to
    completion before returning, so a run driven over HTTP with this agent would
    never let the response come back — which is exactly the property these tests
    need. Dispatch happens through :func:`_abandoned_run` instead.
    """

    __test__ = False

    def __init__(self) -> None:
        self.run_id: str | None = None
        self.released = False

    def name(self) -> str:
        return "blocking"

    def get_capabilities(self) -> set:
        return set()

    async def start_run(
        self, run_id: str, request: RunRequest, *, context: object = None
    ) -> AgentRunResult:
        del request, context
        self.run_id = run_id
        while not self.released:
            await asyncio.sleep(0.001)
        return AgentRunResult(status=RunStatus.CANCELLED)

    async def cancel_run(self, run_id: str) -> RunResponse:
        self.released = True
        return RunResponse(run_id=run_id, status=RunStatus.CANCELLED)


def _abandoned_run(
    app, conversation_id: str, source: str, prompt: str = "hello"
) -> str:
    """Dispatch a real run and walk away from it, leaving durable ``running``.

    This is a genuine in-flight execution, not a fabricated record: the run
    service dispatched it, the lifecycle authority started it, and the agent is
    still blocked. Closing the loop abandons the local task exactly the way a
    process crash abandons a run, which is what the retry guard has to survive.
    """
    service = app.state.run_service
    request = RunRequest(
        prompt=prompt, conversation_id=conversation_id, source_user_message_id=source
    )

    async def scenario() -> str:
        task = asyncio.create_task(service.start_run(request))
        agent = service._agent  # type: ignore[attr-defined]
        for _ in range(2_000):
            if getattr(agent, "run_id", None) is not None:
                break
            await asyncio.sleep(0.001)
        run_id = getattr(agent, "run_id", None)
        assert run_id is not None, "the run never reached the agent"
        task.cancel()
        return run_id

    return asyncio.run(scenario())


def _settings(database: Path) -> Settings:
    return Settings(
        persistence_provider="relational",
        persistence_database_url=str(database),
        attachment_storage="memory",
    )


def _app(tmp_path: Path, agent: AgentPort, name: str = "attempts"):
    """Build an app whose run service runs ``agent`` against a real database."""
    app = create_app(settings=_settings(tmp_path / f"{name}.sqlite3"))
    persistence = app.state.persistence
    app.state.run_service = RunService(
        agent,
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
        conversation_repository=persistence.conversation_repository,
        message_repository=persistence.message_repository,
        context_service=app.state.context_construction_service,
    )
    app.state.lifecycle = RunLifecycleService(
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )
    return app


def _turn(client: TestClient, *, content: str = "hello", title: str = "Attempts"):
    """Create a conversation holding one durable user message."""
    conversation_id = client.post("/conversations", json={"title": title}).json()[
        "conversation_id"
    ]
    message = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content, "role": "user"},
    ).json()
    return conversation_id, message["message_id"]


def _add_turn(client: TestClient, conversation_id: str, content: str) -> str:
    return client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content, "role": "user"},
    ).json()["message_id"]


def _payload(conversation_id: str, source: str, prompt: str = "hello") -> dict:
    return {
        "prompt": prompt,
        "conversation_id": conversation_id,
        "source_user_message_id": source,
    }


def _first_attempt(
    client: TestClient, conversation_id: str, source: str, prompt: str = "hello"
) -> dict:
    """Start the first attempt for a turn — the ordinary ``POST /runs`` path."""
    return client.post("/runs", json=_payload(conversation_id, source, prompt)).json()


def _new_attempt(
    client: TestClient, conversation_id: str, source: str, prior_run_id: str, **extra
) -> dict:
    """Branch a new attempt from ``prior_run_id`` — the retry/regenerate path."""
    return client.post(
        "/runs",
        json={**_payload(conversation_id, source), "retry_of_run_id": prior_run_id, **extra},
    ).json()


def _settled(client: TestClient, run_id: str) -> dict:
    """Wait for a started run to reach a terminal status, then return it.

    ``POST /runs`` returns while the run is still executing, so every assertion
    about an outcome waits for durable convergence first. A run that never
    settles fails the test rather than hanging.
    """
    deadline = time.monotonic() + _TERMINAL_TIMEOUT_SECONDS
    while True:
        stored = client.get(f"/runs/{run_id}").json()
        if stored["status"] in {"completed", "failed", "cancelled"}:
            return stored
        if time.monotonic() > deadline:
            raise AssertionError(
                f"run {run_id} never settled; last status was {stored['status']}"
            )
        time.sleep(0.005)


def _record(app, run_id: str):
    return app.state.lifecycle.get(run_id)


def _events(client: TestClient, run_id: str) -> list[dict]:
    return list(client.get(f"/runs/{run_id}/events").json())


def _event_types(client: TestClient, run_id: str) -> list[str]:
    return [event["event_type"] for event in _events(client, run_id)]


def _messages(client: TestClient, conversation_id: str) -> list[dict]:
    return list(
        client.get(f"/conversations/{conversation_id}/messages").json()["messages"]
    )


def _by_role(client: TestClient, conversation_id: str, role: str) -> list[dict]:
    return [message for message in _messages(client, conversation_id) if message["role"] == role]


def _failed_payload(client: TestClient, run_id: str) -> dict:
    failed = [e for e in _events(client, run_id) if e["event_type"] == "run_failed"]
    assert len(failed) == 1, f"expected exactly one run_failed fact, got {failed}"
    return failed[0]["payload"]

def _context_texts(messages: list[ContextMessage]) -> list[tuple[str, str]]:
    return [(message.role.value, message.content) for message in messages]


# ============================================================
# END: Fakes
# ============================================================


# ============================================================
# BEGIN: Eligibility Policy
# ============================================================


def test_retry_and_regenerate_are_disjoint_policies() -> None:
    """Two user intents, two narrow and non-overlapping status sets."""
    assert can_retry(RunStatus.FAILED)
    assert can_retry(RunStatus.CANCELLED)
    assert can_regenerate(RunStatus.COMPLETED)

    for status in RunStatus:
        assert not (can_retry(status) and can_regenerate(status))


def test_an_active_run_is_never_a_new_attempt_target() -> None:
    """A turn that is still executing cannot be branched."""
    for status in (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_FOR_APPROVAL):
        assert not can_be_superseded(status)
        assert not can_retry(status)
        assert not can_regenerate(status)


def test_every_terminal_status_is_supersedable() -> None:
    for status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        assert can_be_superseded(status)


def test_no_status_is_both_a_valid_retry_and_a_valid_regenerate_target() -> None:
    """Regenerating a failure or retrying a success is not a defined action."""
    assert not can_regenerate(RunStatus.FAILED)
    assert not can_regenerate(RunStatus.CANCELLED)
    assert not can_retry(RunStatus.COMPLETED)


# ============================================================
# END: Eligibility Policy
# ============================================================


# ============================================================
# BEGIN: New Run Identity
# ============================================================


def test_a_new_attempt_creates_a_new_run_and_a_new_assistant_response(tmp_path) -> None:
    agent = ScriptedAgent(
        outcomes=[RunStatus.FAILED, RunStatus.COMPLETED],
        contents=["partial then failed", "second attempt"],
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, first["run_id"])
        settled = _settled(client, second["run_id"])

        # New run identity, new assistant response, same source user message.
        assert second["run_id"] != first["run_id"]
        assert second["assistant_message_id"] != first["assistant_message_id"]
        assert settled["source_user_message_id"] == source
        assert settled["status"] == RunStatus.COMPLETED

        # Exactly one user message: a new attempt never duplicates the turn.
        assert len(_by_role(client, conversation_id, "user")) == 1
        assert len(_by_role(client, conversation_id, "assistant")) == 2


def test_repeated_new_attempts_never_duplicate_the_turn(tmp_path) -> None:
    agent = ScriptedAgent(
        outcomes=[RunStatus.COMPLETED] * 3, contents=["one", "two", "three"]
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        third = _new_attempt(client, conversation_id, source, second["run_id"])
        for run_id in (first["run_id"], second["run_id"], third["run_id"]):
            _settled(client, run_id)

        assert len({first["run_id"], second["run_id"], third["run_id"]}) == 3
        assert len(
            {
                first["assistant_message_id"],
                second["assistant_message_id"],
                third["assistant_message_id"],
            }
        ) == 3
        assert len(_by_role(client, conversation_id, "user")) == 1
        assert [m["content"] for m in _by_role(client, conversation_id, "assistant")] == [
            "one",
            "two",
            "three",
        ]


def test_the_new_response_uses_the_durable_prompt_not_the_client_supplied_one(
    tmp_path,
) -> None:
    """A client cannot smuggle different text into a new attempt."""
    agent = ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2)
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="the durable prompt")
        first = _first_attempt(
            client, conversation_id, source, prompt="the durable prompt"
        )
        response = client.post(
            "/runs",
            json={
                **_payload(conversation_id, source, "a different prompt from the client"),
                "retry_of_run_id": first["run_id"],
            },
        )
        assert response.status_code == 202
        _settled(client, first["run_id"])
        _settled(client, response.json()["run_id"])

        assert agent.prompts == ["the durable prompt", "the durable prompt"]


def test_a_conflicting_source_user_message_is_refused(tmp_path) -> None:
    agent = ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2)
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="first turn")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        other_conversation, other_source = _turn(client, content="other", title="Other")

        response = client.post(
            "/runs",
            json={
                **_payload(other_conversation, other_source, "other"),
                "retry_of_run_id": first["run_id"],
            },
        )

        assert response.status_code == 409
        assert response.json()["error_code"] == "run_not_supersedable"
        assert "different conversation" in response.json()["message"]
        # The prior attempt is untouched by the refusal.
        assert _record(app, first["run_id"]).status is RunStatus.COMPLETED
        assert len(agent.prompts) == 1


def test_a_retry_target_answering_a_different_source_in_one_conversation_is_refused(
    tmp_path,
) -> None:
    """Lineage is the prior run's own source, not a client-chosen turn."""
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2))
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="first turn")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        other_source = _add_turn(client, conversation_id, "second turn")

        response = client.post(
            "/runs",
            json={
                **_payload(conversation_id, other_source, "second turn"),
                "retry_of_run_id": first["run_id"],
            },
        )

        assert response.status_code == 409
        assert "different source user message" in response.json()["message"]


# ============================================================
# END: New Run Identity
# ============================================================


# ============================================================
# BEGIN: Old Run Immutability
# ============================================================


def test_the_prior_run_is_immutable_across_a_new_attempt(tmp_path) -> None:
    app = _app(
        tmp_path,
        ScriptedAgent(
            outcomes=[RunStatus.FAILED, RunStatus.COMPLETED],
            contents=["first partial", "second"],
        ),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])

        before_record = _record(app, first["run_id"])
        before_events = _events(client, first["run_id"])
        before_assistant = _by_role(client, conversation_id, "assistant")[0]

        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        after_record = _record(app, first["run_id"])
        assert after_record.status is before_record.status is RunStatus.FAILED
        assert after_record.created_at == before_record.created_at
        assert after_record.updated_at == before_record.updated_at
        assert after_record.cancellation_requested_at == before_record.cancellation_requested_at
        assert after_record.assistant_message_id == before_record.assistant_message_id
        assert after_record.source_user_message_id == before_record.source_user_message_id
        assert _events(client, first["run_id"]) == before_events
        assert _by_role(client, conversation_id, "assistant")[0] == before_assistant


def test_a_prior_failure_record_does_not_carry_into_the_new_run(tmp_path) -> None:
    app = _app(
        tmp_path,
        ScriptedAgent(
            outcomes=[RunStatus.FAILED, RunStatus.COMPLETED],
            contents=["broken", "fixed"],
        ),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        prior_failure = _failed_payload(client, first["run_id"])
        assert prior_failure["error_code"] == "agent_failed"

        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        # The old run still owns the old failure; the new one owns none.
        assert _failed_payload(client, first["run_id"]) == prior_failure
        assert _event_types(client, second["run_id"])[-1] == EventType.RUN_COMPLETED.value
        assert "run_failed" not in _event_types(client, second["run_id"])


def test_a_prior_run_is_never_reset_from_its_terminal_status(tmp_path) -> None:
    """No failed -> pending, completed -> running, or cancelled -> running."""
    app = _app(
        tmp_path,
        ScriptedAgent(outcomes=[RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED]),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        assert _record(app, first["run_id"]).status is RunStatus.COMPLETED

        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])
        third = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, third["run_id"])

        # Every later attempt is a new run; the original never moves again.
        assert len({first["run_id"], second["run_id"], third["run_id"]}) == 3
        assert _record(app, first["run_id"]).status is RunStatus.COMPLETED
        assert _record(app, second["run_id"]).status is RunStatus.CANCELLED


# ============================================================
# END: Old Run Immutability
# ============================================================


# ============================================================
# BEGIN: Fresh State Per Attempt
# ============================================================


def test_the_new_run_starts_with_no_cancellation_intent(tmp_path) -> None:
    """A cancelled attempt's intent must never leak into its retry."""
    app = _app(tmp_path, _BlockingAgent())
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        # Cancel a genuinely in-flight run, so the intent is durable history
        # rather than a late no-op against an already-settled record.
        running_id = _abandoned_run(app, conversation_id, source)
        client.post(f"/runs/{running_id}/cancel")
        _settled(client, running_id)
        assert _record(app, running_id).status is RunStatus.CANCELLED
        assert _record(app, running_id).cancellation_requested_at is not None

        app.state.run_service._agent = ScriptedAgent(  # type: ignore[attr-defined]
            outcomes=[RunStatus.COMPLETED], contents=["retried after cancel"]
        )
        second = _new_attempt(client, conversation_id, source, running_id)
        settled = _settled(client, second["run_id"])

        assert settled["cancellation_requested_at"] is None
        assert _record(app, second["run_id"]).cancellation_requested_at is None
        # The old intent remains historical truth.
        assert _record(app, running_id).cancellation_requested_at is not None
        # And the new run published no cancellation fact of its own.
        assert "run_cancelled" not in _event_types(client, second["run_id"])


def test_the_new_run_restarts_its_event_sequence_at_one(tmp_path) -> None:
    app = _app(
        tmp_path,
        ScriptedAgent(
            outcomes=[RunStatus.FAILED, RunStatus.COMPLETED],
            contents=["partial", "second"],
        ),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        first_sequences = [event["sequence"] for event in _events(client, first["run_id"])]
        second_sequences = [event["sequence"] for event in _events(client, second["run_id"])]

        # Each run owns a complete, gap-free sequence starting at 1. The new
        # run did not continue the old run's log, and the old run's log did not
        # absorb the new run's facts.
        assert first_sequences == list(range(1, len(first_sequences) + 1))
        assert second_sequences == list(range(1, len(second_sequences) + 1))
        assert second_sequences[0] == 1
        assert first_sequences[-1] >= 1
        # Event identity is per run and never shared across attempts.
        assert {e["event_id"] for e in _events(client, first["run_id"])}.isdisjoint(
            {e["event_id"] for e in _events(client, second["run_id"])}
        )
        # The prior run's log is exactly as long as it was before the new run.
        assert len(first_sequences) == 3


def test_the_new_run_carries_fresh_timestamps(tmp_path) -> None:
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2))
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        time.sleep(0.01)
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        assert (
            _record(app, second["run_id"]).created_at
            > _record(app, first["run_id"]).created_at
        )


def test_a_new_response_never_inherits_the_prior_response_content(tmp_path) -> None:
    """A failed attempt keeps its own empty response; the retry gets its own text."""
    app = _app(
        tmp_path,
        ScriptedAgent(
            outcomes=[RunStatus.FAILED, RunStatus.COMPLETED],
            contents=["never persisted", "new full text"],
        ),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        assistants = _by_role(client, conversation_id, "assistant")
        # A failed attempt never publishes partial content, and the retry does
        # not start from anything the failed attempt produced.
        assert assistants[0]["message_id"] == first["assistant_message_id"]
        assert assistants[0]["content"] == ""
        assert "message_content" not in _event_types(client, first["run_id"])
        assert assistants[1]["message_id"] == second["assistant_message_id"]
        assert assistants[1]["content"] == "new full text"


def test_each_assistant_response_is_linked_to_its_own_run_only(tmp_path) -> None:
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2))
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        assistants = _by_role(client, conversation_id, "assistant")
        assert assistants[0]["source_run_id"] == first["run_id"]
        assert assistants[1]["source_run_id"] == second["run_id"]
        assert _record(app, first["run_id"]).assistant_message_id == assistants[0]["message_id"]
        assert _record(app, second["run_id"]).assistant_message_id == assistants[1]["message_id"]


# ============================================================
# END: Fresh State Per Attempt
# ============================================================


# ============================================================
# BEGIN: Lineage and Guards
# ============================================================


def test_an_active_run_cannot_be_superseded(tmp_path) -> None:
    """A stale client cannot branch a still-executing turn."""
    app = _app(tmp_path, _BlockingAgent())
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        running_id = _abandoned_run(app, conversation_id, source)
        assert _record(app, running_id).status is RunStatus.RUNNING

        response = client.post(
            "/runs",
            json={**_payload(conversation_id, source), "retry_of_run_id": running_id},
        )

        assert response.status_code == 409
        assert response.json()["error_code"] == "run_not_supersedable"
        assert "running" in response.json()["message"]
        # The refused attempt never ran, and the in-flight run is untouched.
        assert _record(app, running_id).status is RunStatus.RUNNING
        assert "run_started" in _event_types(client, running_id)
        assert len(_by_role(client, conversation_id, "assistant")) == 1


def test_a_waiting_run_cannot_be_superseded(tmp_path) -> None:
    """Approval is a live state, so it is not a new-attempt target either."""
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2))
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        # A run the lifecycle authority holds in approval, durably.
        waiting_id = app.state.lifecycle.create_run(
            "waiting-attempt",
            conversation_id=conversation_id,
            source_user_message_id=source,
        ).run_id
        app.state.lifecycle.transition(waiting_id, RunStatus.WAITING_FOR_APPROVAL)
        assert _record(app, waiting_id).status is RunStatus.WAITING_FOR_APPROVAL

        response = client.post(
            "/runs",
            json={**_payload(conversation_id, source), "retry_of_run_id": waiting_id},
        )

        assert response.status_code == 409
        assert "waiting_for_approval" in response.json()["message"]
        assert _record(app, waiting_id).status is RunStatus.WAITING_FOR_APPROVAL


def test_a_pending_run_cannot_be_superseded(tmp_path) -> None:
    """Even before execution starts, the attempt must settle first."""
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.COMPLETED]))
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        # A run accepted for the same turn that has not started executing yet.
        # Created through the lifecycle authority so it is genuine durable
        # state, not a fabricated record.
        pending_id = app.state.lifecycle.create_run(
            "pending-attempt",
            conversation_id=conversation_id,
            source_user_message_id=source,
        ).run_id
        assert _record(app, pending_id).status is RunStatus.PENDING

        response = client.post(
            "/runs",
            json={**_payload(conversation_id, source), "retry_of_run_id": pending_id},
        )

        assert response.status_code == 409
        assert "pending" in response.json()["message"]
        assert _record(app, pending_id).status is RunStatus.PENDING


def test_an_unknown_new_attempt_target_is_refused(tmp_path) -> None:
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.COMPLETED]))
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        response = client.post(
            "/runs", json={**_payload(conversation_id, source), "retry_of_run_id": "nope"}
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "run_not_supersedable"
        assert "does not exist" in response.json()["message"]


def test_the_new_run_inherits_the_prior_runs_source_user_message(tmp_path) -> None:
    """Lineage comes from persistence even when the client omits it."""
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2))
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="durable")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])

        response = client.post(
            "/runs",
            json={
                "prompt": "durable",
                "conversation_id": conversation_id,
                "retry_of_run_id": first["run_id"],
            },
        )
        second = response.json()
        _settled(client, second["run_id"])

        assert second["source_user_message_id"] == source
        assert _record(app, second["run_id"]).source_user_message_id == source


def test_a_first_submission_is_unaffected_by_the_new_attempt_field(tmp_path) -> None:
    """The shared creation path still serves an ordinary first submission."""
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.COMPLETED]))
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        settled = _settled(client, first["run_id"])

        assert settled["status"] == RunStatus.COMPLETED
        assert settled["source_user_message_id"] == source
        assert len(_by_role(client, conversation_id, "assistant")) == 1


def test_the_new_attempt_never_creates_a_second_user_message(tmp_path) -> None:
    """One turn, one user message, however many attempts it takes."""
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.FAILED] * 4))
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="one prompt")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        for _ in range(3):
            newest = _new_attempt(client, conversation_id, source, first["run_id"])
            _settled(client, newest["run_id"])
            first = newest

        assert len(_by_role(client, conversation_id, "user")) == 1
        assert len(_by_role(client, conversation_id, "assistant")) == 4


# ============================================================
# END: Lineage and Guards
# ============================================================


# ============================================================
# BEGIN: Configuration Resolution
# ============================================================


def test_a_new_attempt_never_inherits_the_prior_runs_resolved_execution(tmp_path) -> None:
    """The prior run's resolved execution is history, not an input.

    The strongest observable form of "not inherited": the first attempt resolves
    a concrete runtime and model, the new attempt resolves nothing, and the new
    run records no execution at all rather than the old run's identity.
    """
    app = _app(
        tmp_path,
        ScriptedAgent(
            outcomes=[RunStatus.COMPLETED] * 2,
            selections=[
                RunExecutionSelection(
                    runtime_id="legacy-runtime",
                    model_provider_id="legacy-provider",
                    model_id="legacy-model",
                ),
                None,
            ],
        ),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        assert _record(app, first["run_id"]).execution_selection is not None
        assert (
            _record(app, first["run_id"]).execution_selection.runtime_id
            == "legacy-runtime"
        )

        second = _new_attempt(client, conversation_id, source, first["run_id"])
        settled = _settled(client, second["run_id"])

        assert settled["execution_selection"] is None
        assert _record(app, second["run_id"]).execution_selection is None


def test_a_new_attempt_resolves_the_execution_its_own_request_names(tmp_path) -> None:
    """A new attempt records its own resolution, not the previous run's."""
    app = _app(
        tmp_path,
        ScriptedAgent(
            outcomes=[RunStatus.COMPLETED] * 2,
            selections=[
                RunExecutionSelection(runtime_id="old-runtime", model_id="old-model"),
                RunExecutionSelection(runtime_id="new-runtime", model_id="new-model"),
            ],
        ),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        settled = _settled(client, second["run_id"])

        assert _record(app, first["run_id"]).execution_selection.runtime_id == "old-runtime"
        assert settled["execution_selection"]["runtime_id"] == "new-runtime"
        assert _record(app, second["run_id"]).execution_selection.model_id == "new-model"


def test_a_new_attempt_does_not_inherit_a_cancelled_runs_workspace_intent(tmp_path) -> None:
    """Workspace is resolved per run, from the current request."""
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.CANCELLED, RunStatus.COMPLETED]))
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        settled = _settled(client, second["run_id"])

        assert settled["status"] == RunStatus.COMPLETED
        # A cancelled prior run leaves no marker the new run must clear.
        assert settled["cancellation_requested_at"] is None


# ============================================================
# END: Configuration Resolution
# ============================================================


# ============================================================
# BEGIN: Context Construction
# ============================================================


def test_regenerating_a_completed_response_excludes_it_from_context(tmp_path) -> None:
    """U1 A1, new attempt for A1 -> context is U1, never U1 A1 U1."""
    agent = ScriptedAgent(
        outcomes=[RunStatus.COMPLETED, RunStatus.COMPLETED],
        contents=["first answer", "second answer"],
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="Explain")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        assert _context_texts(agent.contexts[0]) == [("user", "Explain")]
        # The superseded completed response is not prior history.
        assert _context_texts(agent.contexts[1]) == [("user", "Explain")]


def test_retrying_a_failed_response_excludes_its_partial_from_context(tmp_path) -> None:
    agent = ScriptedAgent(
        outcomes=[RunStatus.FAILED, RunStatus.COMPLETED],
        contents=["partial answer", "full answer"],
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="Explain")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        # The failed partial is durable history but never model context.
        assert _context_texts(agent.contexts[1]) == [("user", "Explain")]


def test_retrying_a_cancelled_response_excludes_its_partial_from_context(tmp_path) -> None:
    agent = ScriptedAgent(
        outcomes=[RunStatus.CANCELLED, RunStatus.COMPLETED],
        contents=["partial", "full"],
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="Explain")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        assert _context_texts(agent.contexts[1]) == [("user", "Explain")]


def test_a_new_attempt_on_the_latest_turn_keeps_earlier_turns_as_history(tmp_path) -> None:
    """U1 A1 U2 A2, new attempt for A2 -> history U1 A1, current U2. No old A2."""
    agent = ScriptedAgent(
        outcomes=[RunStatus.COMPLETED, RunStatus.COMPLETED],
        contents=["answer one", "answer two"],
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, first_source = _turn(client, content="First question")
        first = _first_attempt(client, conversation_id, first_source)
        _settled(client, first["run_id"])

        second_source = _add_turn(client, conversation_id, "Second question")
        second = client.post(
            "/runs",
            json=_payload(conversation_id, second_source, "Second question"),
        ).json()
        _settled(client, second["run_id"])

        agent.contexts.clear()
        third = _new_attempt(client, conversation_id, second_source, second["run_id"])
        _settled(client, third["run_id"])

        assert _context_texts(agent.contexts[0]) == [
            ("user", "First question"),
            ("assistant", "answer one"),
            ("user", "Second question"),
        ]


def test_regenerating_the_second_turn_reuses_its_durable_source_not_the_first(
    tmp_path,
) -> None:
    """U1/A1/U2/A2 -> regenerate A2 executes U2 and preserves both lineages."""
    agent = ScriptedAgent(
        outcomes=[RunStatus.COMPLETED] * 3,
        contents=["answer to hello ava", "answer to test 123", "regenerated test 123"],
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, first_source = _turn(client, content="hello ava")
        first = _first_attempt(client, conversation_id, first_source, "hello ava")
        _settled(client, first["run_id"])

        second_source = _add_turn(client, conversation_id, "test 123")
        second = _first_attempt(client, conversation_id, second_source, "test 123")
        _settled(client, second["run_id"])

        before_regenerate = _messages(client, conversation_id)
        assistant_by_run = {
            message["source_run_id"]: message
            for message in before_regenerate
            if message["role"] == "assistant"
        }
        assert assistant_by_run[first["run_id"]]["source_run_id"] == first["run_id"]
        assert assistant_by_run[second["run_id"]]["source_run_id"] == second["run_id"]
        assert _settled(client, first["run_id"])["source_user_message_id"] == first_source
        assert _settled(client, second["run_id"])["source_user_message_id"] == second_source

        regenerated = _new_attempt(
            client, conversation_id, second_source, second["run_id"], prompt="test 123"
        )
        settled = _settled(client, regenerated["run_id"])

        assert settled["run_id"] != second["run_id"]
        assert settled["source_user_message_id"] == second_source
        assert agent.prompts == ["hello ava", "test 123", "test 123"]
        assert _context_texts(agent.contexts[-1]) == [
            ("user", "hello ava"),
            ("assistant", "answer to hello ava"),
            ("user", "test 123"),
        ]
        regenerated_assistant = next(
            message
            for message in _by_role(client, conversation_id, "assistant")
            if message["source_run_id"] == regenerated["run_id"]
        )
        assert regenerated_assistant["content"] == "regenerated test 123"


def test_regenerating_a_non_latest_turn_preserves_later_run_lineage(tmp_path) -> None:
    """A new A2 is linked to A; the later B run and assistant remain untouched."""
    agent = ScriptedAgent(
        outcomes=[RunStatus.COMPLETED] * 3,
        contents=["Assistant A", "Assistant B", "Assistant A2"],
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, first_source = _turn(client, content="hello ava")
        first = _first_attempt(client, conversation_id, first_source, "hello ava")
        _settled(client, first["run_id"])
        second_source = _add_turn(client, conversation_id, "test 123")
        second = _first_attempt(client, conversation_id, second_source, "test 123")
        _settled(client, second["run_id"])

        regenerated = _new_attempt(
            client, conversation_id, first_source, first["run_id"], prompt="hello ava"
        )
        settled = _settled(client, regenerated["run_id"])

        assert settled["source_user_message_id"] == first_source
        assert _settled(client, second["run_id"])["source_user_message_id"] == second_source
        assistants = {
            message["source_run_id"]: message
            for message in _by_role(client, conversation_id, "assistant")
        }
        assert assistants[first["run_id"]]["source_user_message_id"] == first_source
        assert assistants[second["run_id"]]["source_user_message_id"] == second_source
        assert assistants[regenerated["run_id"]]["source_user_message_id"] == first_source
        assert assistants[second["run_id"]]["content"] == "Assistant B"
        assert agent.prompts == ["hello ava", "test 123", "hello ava"]


def test_repeated_new_attempts_never_accumulate_superseded_variants(tmp_path) -> None:
    """U1 A1 A2 A3 all durable; a later turn's context sees only A3."""
    agent = ScriptedAgent(
        outcomes=[RunStatus.COMPLETED] * 4,
        contents=["one", "two", "three", "final"],
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="First question")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])
        third = _new_attempt(client, conversation_id, source, second["run_id"])
        _settled(client, third["run_id"])

        # Durable history really does hold all three responses.
        assert [
            message["content"] for message in _by_role(client, conversation_id, "assistant")
        ] == ["one", "two", "three"]

        later_source = _add_turn(client, conversation_id, "Follow up")
        agent.contexts.clear()
        later = client.post(
            "/runs", json=_payload(conversation_id, later_source, "Follow up")
        ).json()
        _settled(client, later["run_id"])

        assert _context_texts(agent.contexts[0]) == [
            ("user", "First question"),
            ("assistant", "three"),
            ("user", "Follow up"),
        ]


def test_the_current_source_user_appears_exactly_once_every_time(tmp_path) -> None:
    agent = ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 3)
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="Only once")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])
        third = _new_attempt(client, conversation_id, source, second["run_id"])
        _settled(client, third["run_id"])

        for context in agent.contexts:
            assert _context_texts(context) == [("user", "Only once")]


def test_a_failed_new_attempt_leaves_the_lineage_clean_for_the_next_one(tmp_path) -> None:
    """R1 completed -> R2 failed -> R3 completed, all on one source user message."""
    agent = ScriptedAgent(
        outcomes=[RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.COMPLETED],
        contents=["one", "partial two", "three"],
    )
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="Prompt")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])
        third = _new_attempt(client, conversation_id, source, second["run_id"])
        _settled(client, third["run_id"])

        assert _record(app, second["run_id"]).status is RunStatus.FAILED
        assert _record(app, third["run_id"]).status is RunStatus.COMPLETED
        assert len(_by_role(client, conversation_id, "user")) == 1
        # The failed attempt published no content and is not rewritten by the
        # retry; each response holds only what its own run produced.
        assert [
            message["content"] for message in _by_role(client, conversation_id, "assistant")
        ] == ["one", "", "three"]
        for context in agent.contexts:
            assert _context_texts(context) == [("user", "Prompt")]


def test_assistant_context_is_scoped_to_its_own_conversation(tmp_path) -> None:
    """A prior attempt in another conversation never leaks into this context."""
    agent = ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2)
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        other_id, other_source = _turn(client, content="Other conversation", title="Other")
        other = client.post(
            "/runs", json=_payload(other_id, other_source, "Other conversation")
        ).json()
        _settled(client, other["run_id"])

        agent.contexts.clear()
        conversation_id, source = _turn(client, content="This conversation", title="This")
        _first_attempt(client, conversation_id, source)
        _settled(client, other["run_id"])
        del conversation_id, source

        assert _context_texts(agent.contexts[0]) == [("user", "This conversation")]


# ============================================================
# END: Context Construction
# ============================================================


# ============================================================
# BEGIN: Lifecycle Interaction
# ============================================================


def test_execution_interrupted_is_retryable_history_not_a_resume(tmp_path) -> None:
    """Phase 5.30's settlement is ordinary terminal history.

    A run the backend lost is a ``failed`` run carrying an
    ``execution_interrupted`` reason. It is retried like any other failure, and
    the retry is a full new run — the interrupted one is never resumed.
    """
    agent = ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2)
    app = _app(tmp_path, agent)
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="Interrupted turn")

        # A run the backend lost: durable, executing, and then settled by the
        # real cold-start recovery authority.
        lifecycle = app.state.lifecycle
        lost_id = lifecycle.create_run(
            "lost-run",
            conversation_id=conversation_id,
            source_user_message_id=source,
        ).run_id
        lifecycle.start(lost_id)
        summary = app.state.run_recovery_service.recover_stranded_runs()

        assert (summary.active_found, summary.settled_failed) == (1, 1)
        assert _record(app, lost_id).status is RunStatus.FAILED
        assert _failed_payload(client, lost_id) == RESTART_INTERRUPTION_PAYLOAD

        # It is retryable like any other failure, and only one agent call was
        # made in total: the lost run never reached an agent, and its retry is
        # not a resume of it.
        retried = _new_attempt(client, conversation_id, source, lost_id)
        settled = _settled(client, retried["run_id"])

        assert retried["run_id"] != lost_id
        assert settled["status"] == RunStatus.COMPLETED
        assert settled["source_user_message_id"] == source
        assert settled["assistant_message_id"] is not None
        assert len(agent.prompts) == 1
        assert _event_types(client, lost_id)[-1] == EventType.RUN_FAILED.value
        assert [e["sequence"] for e in _events(client, retried["run_id"])][0] == 1


def test_a_new_attempt_runs_the_normal_lifecycle_event_sequence(tmp_path) -> None:
    app = _app(tmp_path, ScriptedAgent(outcomes=[RunStatus.COMPLETED] * 2))
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        assert _event_types(client, second["run_id"]) == [
            EventType.RUN_STARTED.value,
            EventType.MESSAGE_STARTED.value,
            EventType.MESSAGE_CONTENT.value,
            EventType.RUN_COMPLETED.value,
        ]


def test_cancelling_the_new_run_leaves_the_prior_one_unchanged(tmp_path) -> None:
    app = _app(
        tmp_path, ScriptedAgent(outcomes=[RunStatus.FAILED, RunStatus.CANCELLED])
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        before_events = _events(client, first["run_id"])

        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])
        client.post(f"/runs/{second['run_id']}/cancel")

        assert _record(app, second["run_id"]).status is RunStatus.CANCELLED
        assert _record(app, first["run_id"]).status is RunStatus.FAILED
        assert _record(app, first["run_id"]).cancellation_requested_at is None
        # The prior run's event log never grew a cancellation fact.
        assert _events(client, first["run_id"]) == before_events
        assert "run_cancelled" not in _event_types(client, first["run_id"])


def test_replay_returns_only_the_new_runs_facts(tmp_path) -> None:
    app = _app(
        tmp_path,
        ScriptedAgent(outcomes=[RunStatus.FAILED, RunStatus.COMPLETED]),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        replayed = _events(client, second["run_id"])
        assert {event["run_id"] for event in replayed} == {second["run_id"]}
        # The prior run's facts are not folded into the new run's replay.
        assert {e["event_id"] for e in _events(client, first["run_id"])}.isdisjoint(
            {e["event_id"] for e in replayed}
        )


def test_a_resume_cursor_on_the_new_run_reads_only_its_own_tail(tmp_path) -> None:
    app = _app(
        tmp_path,
        ScriptedAgent(outcomes=[RunStatus.FAILED, RunStatus.COMPLETED]),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        tail = client.get(
            f"/runs/{second['run_id']}/events", params={"after_sequence": 1}
        ).json()
        assert [event["sequence"] for event in tail] == [2, 3, 4]
        # Every fact the cursor returns belongs to the new run, and the prior
        # run's facts are unreachable through it.
        assert {event["run_id"] for event in tail} == {second["run_id"]}
        assert {event["run_id"] for event in _events(client, first["run_id"])} == {
            first["run_id"]
        }
        assert _event_types(client, first["run_id"])[-1] == EventType.RUN_FAILED.value


def test_a_cursor_past_the_prior_run_length_never_reaches_back_into_it(tmp_path) -> None:
    """Replay is run-scoped: the old run's higher cursor reads nothing new."""
    app = _app(
        tmp_path,
        ScriptedAgent(
            outcomes=[RunStatus.COMPLETED, RunStatus.FAILED],
            contents=["first", "second"],
        ),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        prior_length = len(_events(client, first["run_id"]))

        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])
        new_length = len(_events(client, second["run_id"]))
        # The prior run got further than the new one, so its cursor is ahead of
        # the new run's end — the case that would leak if replay were shared.
        assert prior_length > new_length

        beyond_new_run = client.get(
            f"/runs/{second['run_id']}/events", params={"after_sequence": prior_length}
        ).json()
        assert beyond_new_run == []
        # And the same cursor on the prior run is simply its own tail.
        prior_tail = client.get(
            f"/runs/{first['run_id']}/events", params={"after_sequence": prior_length}
        ).json()
        assert prior_tail == []


# ============================================================
# END: Lifecycle Interaction
# ============================================================


# ============================================================
# BEGIN: Message Status Projection
# ============================================================


def test_each_assistant_response_keeps_its_own_projected_status(tmp_path) -> None:
    app = _app(
        tmp_path, ScriptedAgent(outcomes=[RunStatus.FAILED, RunStatus.COMPLETED])
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        assistants = _by_role(client, conversation_id, "assistant")
        # A1 still projects failed; A2 projects complete. Nothing overwrote A1.
        assert assistants[0]["message_id"] == first["assistant_message_id"]
        assert assistants[0]["status"] == "failed"
        assert assistants[1]["message_id"] == second["assistant_message_id"]
        assert assistants[1]["status"] == "complete"


def test_a_cancelled_response_keeps_its_own_status_after_a_retry(tmp_path) -> None:
    app = _app(
        tmp_path, ScriptedAgent(outcomes=[RunStatus.CANCELLED, RunStatus.FAILED])
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client)
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        assistants = _by_role(client, conversation_id, "assistant")
        assert assistants[0]["status"] == "cancelled"
        assert assistants[1]["message_id"] == second["assistant_message_id"]
        assert assistants[1]["status"] == "failed"
        assert all(
            message["role"] == MessageRole.ASSISTANT.value for message in assistants
        )


# ============================================================
# END: Message Status Projection
# ============================================================


# ============================================================
# BEGIN: Restart and Recovery
# ============================================================


def test_a_stranded_run_is_retryable_after_a_restart(tmp_path) -> None:
    """Phase 5.30 settlement plus Phase 5.31 retry, over one real database.

    The app is closed with a run still executing — a genuine process-local
    strand. A second app over the same database performs cold-start recovery
    and the interrupted run is then retried as a normal new run.
    """
    first_app = _app(tmp_path, _BlockingAgent(), name="restart")
    with TestClient(first_app) as client:
        conversation_id, source = _turn(client, content="Stranded turn")
        stranded_id = _abandoned_run(
            first_app, conversation_id, source, prompt="Stranded turn"
        )
        assert first_app.state.lifecycle.get(stranded_id).status is RunStatus.RUNNING

    # Cold start over the same durable data.
    second_app = create_app(settings=_settings(tmp_path / "restart.sqlite3"))
    with TestClient(second_app) as client:
        recovery = second_app.state.run_recovery_summary
        assert recovery.active_found == 1
        assert recovery.settled_failed == 1

        # The stranded run is now ordinary terminal failure history.
        events = _events(client, stranded_id)
        failed = [e for e in events if e["event_type"] == "run_failed"]
        assert len(failed) == 1
        assert failed[0]["payload"] == RESTART_INTERRUPTION_PAYLOAD

        # And it is retryable, as a full new run.
        second_app.state.run_service._agent = ScriptedAgent(  # type: ignore[attr-defined]
            outcomes=[RunStatus.COMPLETED], contents=["answered after restart"]
        )
        retried = client.post(
            "/runs",
            json={
                **_payload(conversation_id, source, "Stranded turn"),
                "retry_of_run_id": stranded_id,
            },
        ).json()
        settled = _settled(client, retried["run_id"])

        assert retried["run_id"] != stranded_id
        assert settled["status"] == RunStatus.COMPLETED
        assert settled["source_user_message_id"] == source
        assert len(_by_role(client, conversation_id, "user")) == 1
        assert [event["sequence"] for event in _events(client, retried["run_id"])][0] == 1
        # The interrupted run's own facts are unchanged and never resumed.
        assert _event_types(client, stranded_id)[-1] == EventType.RUN_FAILED.value


def test_a_refresh_between_attempts_preserves_both_responses(tmp_path) -> None:
    """Rehydration reads durable history: both responses, newest visible."""
    app = _app(
        tmp_path,
        ScriptedAgent(
            outcomes=[RunStatus.COMPLETED, RunStatus.COMPLETED],
            contents=["first", "second"],
        ),
    )
    with TestClient(app) as client:
        conversation_id, source = _turn(client, content="Refresh me")
        first = _first_attempt(client, conversation_id, source)
        _settled(client, first["run_id"])
        second = _new_attempt(client, conversation_id, source, first["run_id"])
        _settled(client, second["run_id"])

        # A refresh is a fresh read of the same durable graph.
        rehydrated = _messages(client, conversation_id)
        assistants = [m for m in rehydrated if m["role"] == "assistant"]
        assert [m["content"] for m in assistants] == ["first", "second"]
        assert assistants[-1]["source_run_id"] == second["run_id"]
        # The newest response is the one a client would act on.
        assert assistants[-1]["status"] == "complete"

        # And it is still retryable/regenerable after rehydration.
        third = _new_attempt(client, conversation_id, source, second["run_id"])
        assert _settled(client, third["run_id"])["status"] == RunStatus.COMPLETED


# ============================================================
# END: Restart and Recovery
# ============================================================
