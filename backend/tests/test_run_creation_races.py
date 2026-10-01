"""Phase 5.39 conversation-scoped run creation races.

Phase 5.33 established that a conversation has at most one active run, and that
a second request for the same conversation is refused with
``conversation_run_active``. Phase 5.39 stresses that rule under real contention
and proves two things that are easy to assume and easy to get wrong:

* the refusal is **atomic**, so exactly one of several racing creators wins even
  when all of them are inside the guard at the same time; and
* the loser leaks **nothing** — no run row, no assistant placeholder, no run
  event, no half-built lineage. A rejected request must be as absent as if it
  had never been made.

The same file covers whether the conversation guard is a *global* lock in
disguise. It is not: two conversations must be able to start runs at the same
time, because a user running one conversation must never be blocked by another.

Retry and regenerate are included because they are the other way to create a run
in a conversation, and the easiest way for a concurrency rule to be bypassed:
lineage resolution reads the prior run and then writes a new one, so the
active-run guard has to hold *after* resolution, not before. A retry must not be
a way around ``conversation_run_active``, and two simultaneous retries of the
same attempt must not both proceed.

Real relational persistence is used throughout, because the guard under test is a
``SELECT`` inside the same transaction as the ``INSERT``.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.conversations import MessageRole, MessageStatus
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories import (
    RelationalRunEventRepository,
    RelationalRunRepository,
)
from ava.repositories.message_repository import MessageRecord
from ava.repositories.run_repository import ActiveConversationRunError
from ava.services.run_lifecycle_service import RunLifecycleService
from ava.services.run_service import ConversationRunActiveError

#: Racing creators per conversation. Two is the minimum that can race; four
#: makes "exactly one winner" a real claim rather than a coin flip.
CREATORS = 4
#: How many rounds the same-conversation race repeats.
ROUNDS = 10

TERMINAL_EVENT_TYPES = {"run_completed", "run_failed", "run_cancelled"}


# ============================================================
# BEGIN: Harness
# ============================================================


def _app(tmp_path, name: str):
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / f"{name}.sqlite3"),
        attachment_storage="memory",
    )
    return create_app(settings=settings)


def _lifecycle(app: Any) -> RunLifecycleService:
    persistence = app.state.persistence
    return RunLifecycleService(
        run_repository=persistence.run_repository,
        run_event_repository=persistence.run_event_repository,
    )


def _conversation_with_user(client: TestClient, title: str) -> tuple[str, str]:
    conversation_id = client.post("/conversations", json={"title": title}).json()["conversation_id"]
    message_id = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "go", "role": "user"},
    ).json()["message_id"]
    return conversation_id, message_id


def _seed_settled_attempt(
    client: TestClient, app: Any, run_id: str, outcome: str
) -> str:
    """A terminal run with a durable user message and assistant placeholder.

    ``outcome`` is ``"failed"`` or ``"completed"``, which makes the attempt a
    valid retry/regenerate target.
    """
    conversation_id, user_message_id = _conversation_with_user(client, f"Prior {outcome}")
    persistence = app.state.persistence
    lifecycle = _lifecycle(app)
    lifecycle.create_run(
        run_id, conversation_id=conversation_id, source_user_message_id=user_message_id
    )
    assistant_message_id = f"assistant-{run_id}"
    persistence.run_repository.set_assistant_message_id(run_id, assistant_message_id)
    now = datetime.now(UTC)
    persistence.message_repository.append(
        MessageRecord(
            message_id=assistant_message_id,
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content="" if outcome == "failed" else "done",
            status=MessageStatus.FAILED if outcome == "failed" else MessageStatus.COMPLETE,
            source_run_id=run_id,
            created_at=now,
            updated_at=now,
        )
    )
    lifecycle.start(run_id)
    if outcome == "failed":
        lifecycle.fail(run_id, payload={"error_code": "agent_failed", "message": "boom"})
    else:
        lifecycle.complete(run_id)
    return conversation_id


def _footprint(app: Any) -> dict[str, int]:
    """Durable footprint of the whole database, for leak assertions."""
    database: SqliteDatabase = app.state.persistence.database
    with database.connect() as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("runs", "messages", "run_events")
        }


def _prepare(service: Any, request: RunRequest) -> str:
    """Prepare a run and classify the outcome for a race."""
    return "won" if _try_prepare(service, request) is not None else "rejected"


def _try_prepare(service: Any, request: RunRequest) -> Any | None:
    """Prepare a run, returning ``None`` when the conversation guard refuses it."""
    try:
        return service.prepare_run(request)
    except ConversationRunActiveError:
        return None


# ============================================================
# END: Harness
# ============================================================
# ============================================================
# BEGIN: Same-conversation concurrent creation
# ============================================================


@pytest.mark.parametrize("round_index", range(ROUNDS))
def test_concurrent_run_creation_in_one_conversation_admits_exactly_one(
    tmp_path, round_index
) -> None:
    """Racing creators for one conversation: one run, and the losers leak nothing.

    The guard is a ``SELECT`` inside the same transaction as the ``INSERT``, so
    the check and the write cannot interleave. Each round is independent and uses
    a fresh database, so a leak in one round cannot be masked by another.
    """
    app = _app(tmp_path, f"same-conversation-{round_index}")
    with TestClient(app) as client:
        conversation_id, user_message_id = _conversation_with_user(client, f"Round {round_index}")
        service = app.state.run_service
        barrier = threading.Barrier(CREATORS)

        def create(index: int) -> str:
            barrier.wait()
            return _prepare(
                service,
                RunRequest(
                    prompt=f"attempt {index}",
                    conversation_id=conversation_id,
                    source_user_message_id=user_message_id,
                ),
            )

        with ThreadPoolExecutor(max_workers=CREATORS) as pool:
            outcomes = list(pool.map(create, range(CREATORS)))

        assert outcomes.count("won") == 1, outcomes
        assert outcomes.count("rejected") == CREATORS - 1, outcomes

        runs = app.state.persistence.run_repository
        # Exactly one run row exists at all, and it is the winner's.
        run_ids = runs.list_run_ids()
        assert len(run_ids) == 1, run_ids
        winner = runs.get(run_ids[0])
        assert winner is not None
        assert winner.conversation_id == conversation_id
        assert winner.status is RunStatus.RUNNING
        assert {record.run_id for record in runs.list_active()} == {winner.run_id}

        # Exactly one assistant placeholder, owned by that run.
        messages = client.get(f"/conversations/{conversation_id}/messages").json()["messages"]
        assistants = [row for row in messages if row["role"] == "assistant"]
        assert len(assistants) == 1
        assert assistants[0]["source_run_id"] == winner.run_id

        # The run's own history is coherent and terminal-free.
        events = client.get(f"/runs/{winner.run_id}/events").json()
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert not {event["event_type"] for event in events} & TERMINAL_EVENT_TYPES


def test_a_rejected_creation_leaves_no_partial_lineage(tmp_path) -> None:
    """A refused creation is as absent as a request that was never made.

    This is the half of the concurrency rule that is easy to skip: not only must
    the second run not exist, but nothing else it might have written on the way to
    being refused must exist either — no placeholder, no event, no row.
    """
    app = _app(tmp_path, "no-partial-lineage")
    with TestClient(app) as client:
        conversation_id, user_message_id = _conversation_with_user(client, "No leak")
        service = app.state.run_service
        barrier = threading.Barrier(2)

        def create(index: int) -> str:
            barrier.wait()
            return _prepare(
                service,
                RunRequest(
                    prompt=f"attempt {index}",
                    conversation_id=conversation_id,
                    source_user_message_id=user_message_id,
                ),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, range(2)))
        assert outcomes.count("won") == 1, outcomes

        # The refusal is a refusal, not a silent success: the count is unchanged
        # for every table except the one the winner was entitled to touch.
        runs = app.state.persistence.run_repository
        assert len(runs.list_run_ids()) == 1

        messages = client.get(f"/conversations/{conversation_id}/messages").json()["messages"]
        assistants = [row for row in messages if row["role"] == "assistant"]
        assert len(assistants) == 1

        events = RelationalRunEventRepository(
            database=app.state.persistence.database
        ).get_events(assistants[0]["source_run_id"])
        assert not {event.event_type.value for event in events} & TERMINAL_EVENT_TYPES


# ============================================================
# END: Same-conversation concurrent creation
# ============================================================
# ============================================================
# BEGIN: Different-conversation creation
# ============================================================


def test_concurrent_creation_in_different_conversations_is_not_serialized_into_a_conflict(
    tmp_path,
) -> None:
    """A busy conversation must not block an unrelated one.

    If the guard were a process-wide lock, or if it consulted a global active-run
    count, this would fail with a spurious rejection. The point is that the
    conflict is scoped to a conversation.
    """
    app = _app(tmp_path, "different-conversations")
    with TestClient(app) as client:
        pairs = [_conversation_with_user(client, f"Parallel {index}") for index in range(3)]
        service = app.state.run_service
        barrier = threading.Barrier(len(pairs))

        def create(item: tuple[int, str, str]) -> str:
            index, conversation_id, user_message_id = item
            barrier.wait()
            return _prepare(
                service,
                RunRequest(
                    prompt=f"parallel {index}",
                    conversation_id=conversation_id,
                    source_user_message_id=user_message_id,
                ),
            )

        with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
            outcomes = list(pool.map(create, [(i, c, m) for i, (c, m) in enumerate(pairs)]))
        assert outcomes == ["won"] * len(pairs), outcomes

        runs = app.state.persistence.run_repository
        active = runs.list_active()
        assert len(active) == len(pairs)
        assert {record.conversation_id for record in active} == {
            conversation_id for conversation_id, _ in pairs
        }
        assert {record.status for record in active} == {RunStatus.RUNNING}


# ============================================================
# END: Different-conversation creation
# ============================================================
# ============================================================
# BEGIN: Retry and regenerate against the active-run guard
# ============================================================


@pytest.mark.parametrize("outcome", ["failed", "completed"])
def test_a_retry_target_cannot_bypass_the_active_run_guard(tmp_path, outcome) -> None:
    """A retry or regenerate is refused while the conversation is busy.

    Lineage resolution reads the prior attempt and then creates a new run, so the
    active-run guard has to hold *after* that read. Otherwise retry would be a
    way around the one-active-run rule, and the user would have two responses in
    flight in a conversation designed to hold one.
    """
    app = _app(tmp_path, f"retry-guard-{outcome}")
    with TestClient(app) as client:
        conversation_id = _seed_settled_attempt(client, app, "r1-settled", outcome)
        # An unrelated run is now active in the same conversation.
        _lifecycle(app).create_run("r2-active", conversation_id=conversation_id)
        before = _footprint(app)

        outcome_result = _prepare(
            app.state.run_service,
            RunRequest(
                prompt="again please",
                conversation_id=conversation_id,
                retry_of_run_id="r1-settled",
            ),
        )
        assert outcome_result == "rejected"
        assert _footprint(app) == before, "a refused retry must not write anything"


@pytest.mark.parametrize("outcome", ["failed", "completed"])
def test_concurrent_retries_of_one_attempt_admit_exactly_one(tmp_path, outcome) -> None:
    """Two users, or one impatient user, retrying at once: one new attempt.

    The prior attempt is immutable history either way; what must not happen is two
    new live runs branching from it in the same conversation.
    """
    app = _app(tmp_path, f"concurrent-retries-{outcome}")
    with TestClient(app) as client:
        conversation_id = _seed_settled_attempt(client, app, "prior-settled", outcome)
        service = app.state.run_service
        barrier = threading.Barrier(2)
        prior_before = client.get("/runs/prior-settled").json()

        # Two barriers: one before prepare_run and one after it, so both retries
        # are provably inside the service together rather than merely overlapping
        # somewhere in the same millisecond.
        after_prepare = threading.Barrier(2)
        prepared: list[Any] = []

        def raced_retry(index: int) -> str:
            barrier.wait()
            result = _try_prepare(
                service,
                RunRequest(
                    prompt=f"retry {index}",
                    conversation_id=conversation_id,
                    retry_of_run_id="prior-settled",
                ),
            )
            after_prepare.wait()
            if result is not None:
                prepared.append(result)
            return "rejected" if result is None else "won"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(raced_retry, range(2)))
        assert outcomes.count("won") == 1, outcomes
        assert outcomes.count("rejected") == 1, outcomes

        runs = app.state.persistence.run_repository
        created = [run_id for run_id in runs.list_run_ids() if run_id != "prior-settled"]
        assert len(created) == 1, created

        # Exactly one new run, branching from the prior attempt, and re-anchored
        # onto durable history: the stored request carries the prior turn's own
        # user message and its content, not the text the racing client sent.
        assert len(prepared) == 1
        request = prepared[0].request
        assert request.retry_of_run_id == "prior-settled"
        assert request.prompt == "go", request.prompt
        prior = runs.get("prior-settled")
        assert request.source_user_message_id == prior.source_user_message_id

        # The superseded attempt is untouched by the retry that branched from it.
        assert client.get("/runs/prior-settled").json() == prior_before


def test_a_retry_of_a_still_active_run_is_refused_before_any_write(tmp_path) -> None:
    """Branching a live attempt is refused, so two runs can never answer one turn."""
    app = _app(tmp_path, "retry-active-target")
    with TestClient(app) as client:
        conversation_id, user_message_id = _conversation_with_user(client, "Still going")
        lifecycle = _lifecycle(app)
        lifecycle.create_run("live", conversation_id=conversation_id, source_user_message_id=user_message_id)
        lifecycle.start("live")
        before = _footprint(app)

        with pytest.raises(Exception) as refused:
            app.state.run_service.prepare_run(
                RunRequest(
                    prompt="retry the live one",
                    conversation_id=conversation_id,
                    retry_of_run_id="live",
                )
            )
        assert "settle" in str(refused.value)
        assert _footprint(app) == before


# ============================================================
# END: Retry and regenerate against the active-run guard
# ============================================================
# ============================================================
# BEGIN: The guard at the repository boundary
# ============================================================


def test_the_conversation_active_run_guard_is_atomic_in_sql(tmp_path) -> None:
    """The check and the insert are one transaction, so the guard cannot interleave.

    This asserts the *mechanism* rather than a service-level symptom: a caller
    that reaches the repository directly, without the service's error mapping,
    still cannot create two active runs for one conversation.
    """
    database = SqliteDatabase(str(tmp_path / "repository-guard.sqlite3"))
    try:
        runs = RelationalRunRepository(database=database)
        barrier = threading.Barrier(CREATORS)

        def create(index: int) -> bool:
            barrier.wait()
            try:
                runs.create(f"racer-{index}", conversation_id="shared")
            except ActiveConversationRunError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=CREATORS) as pool:
            outcomes = list(pool.map(create, range(CREATORS)))
        assert outcomes.count(True) == 1, outcomes
        assert [record.status for record in runs.list_active()] == [RunStatus.PENDING]
    finally:
        database.dispose()


def test_a_settled_run_frees_the_conversation_for_a_new_attempt(tmp_path) -> None:
    """The guard tracks activity, not history.

    Once the run is terminal the conversation accepts a new one, so the rule
    cannot degrade into a permanent lock on a conversation that has finished
    work. A race between settling and creating is therefore not a deadlock: one
    of the two creators waits and then succeeds, rather than both failing.
    """
    database = SqliteDatabase(str(tmp_path / "guard-releases.sqlite3"))
    try:
        runs = RelationalRunRepository(database=database)
        events = RelationalRunEventRepository(database=database)
        lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
        runs.create("first", conversation_id="c1")
        assert lifecycle.start("first").status is RunStatus.RUNNING

        with pytest.raises(ActiveConversationRunError):
            runs.create("second", conversation_id="c1")

        lifecycle.complete("first")
        # Now the conversation is free.
        runs.create("second", conversation_id="c1")
        assert {record.run_id for record in runs.list_active()} == {"second"}
    finally:
        database.dispose()


def test_settling_and_creating_concurrently_always_ends_with_one_active_run(tmp_path) -> None:
    """A create racing the settlement of the current run cannot wedge the conversation.

    Whether the create lands before or after the settlement, the conversation
    must end with exactly one active run and no refusal that can never resolve.
    """
    database = SqliteDatabase(str(tmp_path / "settle-create.sqlite3"))
    try:
        runs = RelationalRunRepository(database=database)
        events = RelationalRunEventRepository(database=database)
        lifecycle = RunLifecycleService(run_repository=runs, run_event_repository=events)
        runs.create("first", conversation_id="c1")
        lifecycle.start("first")
        barrier = threading.Barrier(2)

        def settle() -> str:
            barrier.wait()
            try:
                lifecycle.complete("first")
            except Exception:
                return "rejected"
            return "settled"

        def create() -> str:
            barrier.wait()
            try:
                runs.create("second", conversation_id="c1")
            except ActiveConversationRunError:
                return "rejected"
            return "created"

        with ThreadPoolExecutor(max_workers=2) as pool:
            settle_future = pool.submit(settle)
            create_future = pool.submit(create)
            outcomes = [settle_future.result(), create_future.result()]

        # Whichever order the two landed in, the prior run is settled and the
        # conversation is not wedged: either the new run is already active, or
        # it was refused only because the conversation was still busy, and the
        # conversation accepts a retry immediately afterwards.
        assert outcomes.count("rejected") == 1, outcomes
        assert runs.get("first").status is RunStatus.COMPLETED

        active = {record.run_id for record in runs.list_active()}
        if "created" in outcomes:
            assert active == {"second"}, active
        else:
            assert active == set(), active
            assert runs.get("second") is None, "a refused create wrote a row anyway"
            runs.create("second", conversation_id="c1")
            assert {record.run_id for record in runs.list_active()} == {"second"}
    finally:
        database.dispose()


# ============================================================
# END: The guard at the repository boundary
# ============================================================
