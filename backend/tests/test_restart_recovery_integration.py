"""Step 4.15 restart/recovery integration tests.

Prove the full Phase 4 durable-state story survives a clean application
restart end to end through the real API chain — relational metadata
(``AVA_PERSISTENCE=relational``, file-backed SQLite) plus local attachment
content (``AVA_ATTACHMENT_STORAGE=local``), no persisted content in memory
on either side:

* application A seeds representative state through the HTTP routes: a
  non-default-title conversation, a user message, a completed run with its
  ordered run events, an assistant message linked to that run, a document with
  two immutable revisions, and two stored attachments (document-owned binary +
  conversation-owned small) with their physical content;
* the application and its persistence are disposed and discarded entirely;
* a brand-new application over the *same* SQLite file and *same* content root
  restores every domain bit-exactly (identities, timestamps, statuses, roles,
  ordering, event payloads, revision history, attachment bytes), with list
  counts unchanged — no duplicates and no synthetic records synthesized during
  startup;
* the recovered application keeps writing durably (one new document revision
  plus one new message), and a *second* restart (A→B→C) preserves the original
  state *and* the post-recovery writes;
* every restart bootstrap exercises the real migration runner and stays at
  schema version 3 (v0001..v0003) with nothing pending — the normal migration
  path, never bypassed.

The run is created through ``POST /runs`` against the deterministic mock
agent adapter, so the completed run's status, execution selection, and event
sequence are reproducible without any live inference.
"""

from dataclasses import dataclass
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ava.api.app import create_app
from ava.configuration.settings import Settings

BINARY_PAYLOAD = bytes(range(256)) * 100  # multi-chunk, non-UTF8-safe binary

USER_PROMPT = "Let's plan the durable workspace"
RUN_PROMPT = "Plan the work"
ASSISTANT_CONTENT = f"AVA mock agent received: {RUN_PROMPT}"
POST_RECOVERY_MESSAGE = "Ping after recovery"

DOC_SEED = "<p>Plan the durable workspace</p>"
DOC_UPDATED = "<h2>Revisions persist</h2><p>exact HTML survives restart</p>"
DOC_POST_RECOVERY = "<p>Written after recovery</p>"

EXPECTED_RUN_EVENT_TYPES = [
    "run_started",
    "message_started",
    "message_content",
    "run_completed",
]


@dataclass(frozen=True)
class DurableState:
    """Authoritative snapshot of every entity seeded by ``_seed``.

    Captured *before* the first restart (constraint #6): the test never reads
    post-restart values to decide what to expect. Attachment bytes travel
    separately because raw binary content is not part of the metadata wire
    contract.
    """

    conversation: dict[str, Any]
    user_message: dict[str, Any]
    assistant_message: dict[str, Any]
    run: dict[str, Any]
    events: list[dict[str, Any]]
    document: dict[str, Any]
    revisions: list[dict[str, Any]]
    document_attachment: dict[str, Any]
    document_attachment_bytes: bytes
    conversation_attachment: dict[str, Any]
    conversation_attachment_bytes: bytes


def _settings(tmp_path, suffix: str = "") -> Settings:
    """Build the Step 4.15 primary configuration: relational + local, all temp."""
    return Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / f"ava{suffix}.sqlite3"),
        attachment_storage="local",
        attachment_storage_root=str(tmp_path / "content"),
    )


def _upload(client: TestClient, *, content: bytes, file_name: str, media_type: str, **owner: str) -> dict[str, Any]:
    response = client.post(
        "/attachments",
        files={"file": (file_name, content, media_type)},
        data=owner or None,
    )
    assert response.status_code == 201, f"[attachment:{owner}] upload failed: {response.text}"
    return dict(response.json())


def _seed(client: TestClient) -> DurableState:
    """Seed the representative durable state through the real HTTP routes."""
    # Conversation with a non-default title.
    conversation = client.post("/conversations", json={"title": "Phase 4 plan"}).json()

    # A user message.
    user_message = client.post(
        f"/conversations/{conversation['conversation_id']}/messages",
        json={"content": USER_PROMPT, "role": "user"},
    ).json()

    # A completed run via the deterministic mock agent, with its 4 ordered events.
    run = client.post("/runs", json={"prompt": RUN_PROMPT}).json()
    assert run["status"] == "completed", "[run] seed run did not complete"
    events = client.get(f"/runs/{run['run_id']}/events").json()
    assert [event["event_type"] for event in events] == EXPECTED_RUN_EVENT_TYPES, "[run event] seed sequence deviated"

    # An assistant message linked to the run (cross-domain reference).
    assistant_content = next(
        event["payload"]["content"] for event in events if event["event_type"] == "message_content"
    )
    assistant_message = client.post(
        f"/conversations/{conversation['conversation_id']}/messages",
        json={"content": assistant_content, "role": "assistant", "source_run_id": run["run_id"]},
    ).json()
    assert assistant_message["source_run_id"] == run["run_id"], "[message] seed link to run lost"

    # A document with two immutable revisions (create records rev 1, update records rev 2).
    document = client.post("/documents", json={"title": "Durable doc", "content": DOC_SEED}).json()
    updated = client.patch(f"/documents/{document['document_id']}", json={"content": DOC_UPDATED})
    assert updated.status_code == 200, "[document] seed update failed"
    document = updated.json()
    assert document["content"] == DOC_UPDATED, "[document] seed content not applied"
    revisions = client.get(f"/documents/{document['document_id']}/revisions").json()["revisions"]
    assert [revision["revision_number"] for revision in revisions] == [1, 2], "[document revision] seed history wrong"

    # Stored attachments: a document-owned binary blob plus a conversation-owned one.
    document_attachment = _upload(
        client,
        content=BINARY_PAYLOAD,
        file_name="data.bin",
        media_type="application/octet-stream",
        owner_type="document",
        owner_id=document["document_id"],
    )
    conversation_attachment = _upload(
        client,
        content=b"planning note",
        file_name="note.txt",
        media_type="text/plain",
        owner_type="conversation",
        owner_id=conversation["conversation_id"],
    )

    return DurableState(
        conversation=conversation,
        user_message=user_message,
        assistant_message=assistant_message,
        run=run,
        events=events,
        document=document,
        revisions=revisions,
        document_attachment=document_attachment,
        document_attachment_bytes=BINARY_PAYLOAD,
        conversation_attachment=conversation_attachment,
        conversation_attachment_bytes=b"planning note",
    )


def _schema_info(app: FastAPI) -> tuple[list[int], int]:
    """Return the applied schema versions and the number of pending migrations.

    Infrastructure-only introspection (constraint #33): verifies the migrated
    database at schema version 3 with nothing pending, exercising the normal
    bootstrap path rather than bypassing it.
    """
    from ava.infrastructure.persistence.migrations.runner import MigrationRunner
    from ava.infrastructure.persistence.migrations.versions import default_registry

    runner = MigrationRunner(app.state.persistence.database, default_registry())
    applied = [migration.version for migration in runner.applied_migrations()]
    pending = runner.pending_migrations()
    return applied, len(pending)


def _assert_schema_at_v3(app: FastAPI) -> None:
    applied, pending = _schema_info(app)
    assert applied == [1, 2, 3], f"[migrations] applied versions changed across restart: {applied}"
    assert pending == 0, f"[migrations] unexpected pending migrations after startup: {pending}"


def _revisions_of(client: TestClient, document_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/documents/{document_id}/revisions")
    assert response.status_code == 200, "[document revision] recovery read failed"
    return cast(list[dict[str, Any]], response.json()["revisions"])


def _assert_original_state(client: TestClient, state: DurableState, *, post_recovery: bool = False) -> None:
    """Assert every originally seeded domain survives bit-exactly, with stable counts.

    Runs against the API (constraint #30), so the checks double as the
    frontend hydration contract (constraint #31: list conversations/documents
    after restart). Every assertion message is prefixed with its domain to keep
    failures diagnosable (constraint #37).

    ``post_recovery`` relaxes the message/revision *count* checks: after a
    recovered application has written new state, those two collections contain
    the seeded items plus the post-recovery additions — the seeded prefix must
    still be bit-exact, and the caller asserts the additions separately.
    """
    # Conversation: single object, single listing, exact body.
    conversation = client.get(f"/conversations/{state.conversation['conversation_id']}")
    assert conversation.status_code == 200, "[conversation] recovery read failed"
    assert conversation.json() == state.conversation, "[conversation] body changed across restart"

    conversations = client.get("/conversations").json()["conversations"]
    assert conversations == [state.conversation], "[conversation] list changed or duplicated on startup"

    # Messages: both roles, seed append order, exact bodies, cross-domain link intact.
    messages = client.get(
        f"/conversations/{state.conversation['conversation_id']}/messages"
    ).json()["messages"]
    assert messages[:2] == [state.user_message, state.assistant_message], (
        "[message] order or body changed across restart"
    )
    assert messages[1]["source_run_id"] == state.run["run_id"], "[message] run linkage lost across restart"
    if not post_recovery:
        assert len(messages) == 2, "[message] count changed or synthesized on startup"

    # Run: terminal status and execution selection stable.
    run = client.get(f"/runs/{state.run['run_id']}")
    assert run.status_code == 200, "[run] recovery read failed"
    assert run.json() == state.run, "[run] status or execution selection changed across restart"

    # Run events: same event ids/types/payloads in the same append order, no synthesis.
    events = client.get(f"/runs/{state.run['run_id']}/events").json()
    assert events == state.events, "[run event] sequence, payload, or count changed across restart"

    # Document: content and timestamps exact; single listing. After a
    # post-recovery write the *identity* and ``created_at`` stay stable while
    # the authoritative body moves to the newly written content (asserted by the
    # caller); otherwise the seeded body must be bit-exact.
    document = client.get(f"/documents/{state.document['document_id']}")
    assert document.status_code == 200, "[document] recovery read failed"
    if post_recovery:
        assert document.json()["document_id"] == state.document["document_id"], "[document] identity changed"
        assert document.json()["created_at"] == state.document["created_at"], "[document] created_at changed"
        assert document.json()["title"] == state.document["title"], "[document] title changed"
    else:
        assert document.json() == state.document, "[document] content changed across restart"

    documents = client.get("/documents").json()["documents"]
    if post_recovery:
        assert documents == [document.json()], "[document] list not single or body diverged"
    else:
        assert documents == [state.document], "[document] list changed or duplicated on startup"

    # Revisions: the seeded history is bit-stable (nothing synthesized at rest).
    revisions = _revisions_of(client, state.document["document_id"])
    assert revisions[:2] == state.revisions, "[document revision] seeded history changed on startup"
    if not post_recovery:
        assert len(revisions) == 2, "[document revision] count changed or synthesized on startup"

    # Attachments: metadata and bytes stable, listed once under each owner.
    for label, attachment, content, owner_type, owner_id, expected_state in (
        ("document", state.document_attachment, state.document_attachment_bytes, "document",
         state.document["document_id"], state.document_attachment),
        ("conversation", state.conversation_attachment, state.conversation_attachment_bytes, "conversation",
         state.conversation["conversation_id"], state.conversation_attachment),
    ):
        metadata = client.get(f"/attachments/{attachment['attachment_id']}")
        assert metadata.status_code == 200, f"[attachment:{label}] recovery read failed"
        assert metadata.json() == expected_state, f"[attachment:{label}] metadata changed across restart"

        body = client.get(f"/attachments/{attachment['attachment_id']}/content")
        assert body.status_code == 200, f"[attachment:{label}] content read failed"
        assert body.content == content, f"[attachment:{label}] bytes changed across restart"

        listed = client.get("/attachments", params={"owner_type": owner_type, "owner_id": owner_id})
        assert listed.json()["attachments"] == [attachment], (
            f"[attachment:{label}] not listed exactly once after restart"
        )


def test_seeded_durable_state_survives_a_clean_restart(tmp_path) -> None:
    """One fresh application restores every seeded domain over the same stores (A→B)."""
    settings = _settings(tmp_path)

    first_app = create_app(settings=settings)
    first = TestClient(first_app)
    with first:
        state = _seed(first)
        _assert_schema_at_v3(first_app)

    # Dispose and discard the entire application + persistence.
    first_app.state.persistence.dispose()
    del first
    del first_app

    second_app = create_app(settings=settings)
    second = TestClient(second_app)
    with second:
        _assert_schema_at_v3(second_app)
        _assert_original_state(second, state)

    # Physical proof under the unchanged content root (constraint #34): the
    # document attachment's bytes live on disk at the id-derived key.
    physical = (
        tmp_path
        / "content"
        / "attachments"
        / state.document_attachment["attachment_id"]
        / "content"
    )
    assert physical.is_file()
    assert physical.read_bytes() == state.document_attachment_bytes


def test_recovered_application_continues_writing_across_a_second_restart(tmp_path) -> None:
    """Post-recovery writes survive a second restart while original state stays bit-exact (A→B→C)."""
    settings = _settings(tmp_path, suffix="-rw")

    app_a = create_app(settings=settings)
    client_a = TestClient(app_a)
    with client_a:
        state = _seed(client_a)
        _assert_schema_at_v3(app_a)
    app_a.state.persistence.dispose()
    del client_a
    del app_a

    # Restart one: recover and, only then, write new durable state.
    app_b = create_app(settings=settings)
    client_b = TestClient(app_b)
    allocated_rev3: dict[str, Any] | None = None
    with client_b:
        _assert_schema_at_v3(app_b)
        _assert_original_state(client_b, state)

        # The document update appends exactly one new revision.
        updated = client_b.patch(
            f"/documents/{state.document['document_id']}",
            json={"content": DOC_POST_RECOVERY},
        )
        assert updated.status_code == 200, "[document] post-recovery write failed"
        assert updated.json()["content"] == DOC_POST_RECOVERY, "[document] post-recovery content not applied"

        post_recovery_revisions = _revisions_of(client_b, state.document["document_id"])
        assert len(post_recovery_revisions) == 3, "[document revision] post-recovery write did not append one revision"
        assert post_recovery_revisions[0] == state.revisions[0], "[document revision] rev 1 mutated by later write"
        assert post_recovery_revisions[1] == state.revisions[1], "[document revision] rev 2 mutated by later write"
        assert post_recovery_revisions[2]["revision_number"] == 3, "[document revision] rev 3 number wrong"
        assert post_recovery_revisions[2]["content"] == DOC_POST_RECOVERY, "[document revision] rev 3 content wrong"
        allocated_rev3 = post_recovery_revisions[2]

        # And a new user message appended after the seeded pair.
        appended = client_b.post(
            f"/conversations/{state.conversation['conversation_id']}/messages",
            json={"content": POST_RECOVERY_MESSAGE, "role": "user"},
        )
        assert appended.status_code == 201, "[message] post-recovery write failed"
        assert _schema_info(app_b)[0] == [1, 2, 3], "[migrations] write churn touched the schema"

    assert allocated_rev3 is not None
    app_b.state.persistence.dispose()
    del client_b
    del app_b

    # Restart two: original and post-recovery state both survive.
    app_c = create_app(settings=settings)
    client_c = TestClient(app_c)
    with client_c:
        _assert_schema_at_v3(app_c)
        _assert_original_state(client_c, state, post_recovery=True)

        document = client_c.get(f"/documents/{state.document['document_id']}")
        assert document.json()["content"] == DOC_POST_RECOVERY, "[document] post-recovery write lost after restart"

        revisions = _revisions_of(client_c, state.document["document_id"])
        assert revisions == [state.revisions[0], state.revisions[1], allocated_rev3], (
            "[document revision] history not stable across the second restart"
        )

        messages = client_c.get(
            f"/conversations/{state.conversation['conversation_id']}/messages"
        ).json()["messages"]
        assert messages[:2] == [state.user_message, state.assistant_message], "[message] seeded messages changed"
        assert messages[-1]["content"] == POST_RECOVERY_MESSAGE, "[message] post-recovery message lost"
        assert len(messages) == 3, "[message] count not exactly seeded + post-recovery after restart"