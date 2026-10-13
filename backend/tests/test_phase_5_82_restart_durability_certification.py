"""Phase 5.82: cold application reconstruction over disposable durable stores."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from ava.api.app import create_app
from ava.configuration.execution_defaults import ApplicationExecutionDefaults
from ava.configuration.settings import Settings
from ava.contracts.attachments import AttachmentOwnerType
from ava.contracts.conversations import MessageRole, MessageStatus, RunContext
from ava.contracts.core_prompts import CreateCorePromptRequest
from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.contracts.projects import UpdateProjectExecutionDefaultsRequest
from ava.contracts.requests import RunRequest
from ava.models.model_configurations import ModelConfiguration
from ava.models.provider_connections import ProviderConnection
from ava.repositories.core_prompt_assignment import CorePromptScopeType
from ava.repositories.message_repository import MessageRecord
from ava.runtimes.configurations import RuntimeConfiguration
from ava.services.effective_prompt_resolver import PromptResolutionContext


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "phase-5-82.sqlite3"),
        project_file_storage="local",
        project_file_storage_root=str(tmp_path / "project-file-content"),
        attachment_storage="local",
        attachment_storage_root=str(tmp_path / "conversation-attachment-content"),
    )


def _record(record: Any) -> dict[str, Any]:
    value = asdict(record)
    return {key: (item.value if hasattr(item, "value") else item) for key, item in value.items()}


def _snapshot(app: Any, file_bytes: dict[str, bytes], attachment_bytes: dict[str, bytes]) -> dict[str, Any]:
    persistence = app.state.persistence
    conversations = list(persistence.conversation_repository.list())
    conversation_ids = [row.conversation_id for row in conversations]
    prompts = list(persistence.core_prompt_repository.list())
    runs = [persistence.run_repository.get(run_id) for run_id in persistence.run_repository.list_run_ids()]
    files = [
        item
        for project in persistence.project_repository.list()
        for item in persistence.project_file_repository.list_by_project(project.id)
    ]
    attachments = [
        item
        for conversation_id in conversation_ids
        for item in persistence.attachment_repository.list_for_owner(AttachmentOwnerType.CONVERSATION, conversation_id)
    ]
    return {
        "projects": [_record(row) for row in persistence.project_repository.list()],
        "folders": [_record(row) for row in persistence.conversation_folder_repository.list()],
        "conversations": [_record(row) for row in conversations],
        "messages": {
            conversation_id: [
                _record(row) for row in persistence.message_repository.list_for_conversation(conversation_id)
            ]
            for conversation_id in conversation_ids
        },
        "runs": [
            {
                **_record(run),
                "events": [
                    event.model_dump(mode="json") for event in persistence.run_event_repository.get_events(run.run_id)
                ],
            }
            for run in runs
        ],
        "core_prompts": [_record(row) for row in prompts],
        "core_prompt_assignments": {
            row.id: [_record(item) for item in persistence.core_prompt_assignment_repository.list_for_prompt(row.id)]
            for row in prompts
        },
        "application_execution_defaults": (
            _record(persistence.execution_defaults_repository.get())
            if persistence.execution_defaults_repository.get() is not None
            else None
        ),
        "project_files": [
            {
                "metadata": _record(row),
                "sha256": hashlib.sha256(file_bytes[row.id]).hexdigest(),
            }
            for row in files
        ],
        "conversation_attachments": [
            {
                "metadata": _record(row),
                "sha256": hashlib.sha256(attachment_bytes[row.attachment_id]).hexdigest(),
            }
            for row in attachments
        ],
    }


@pytest.mark.asyncio
async def test_phase_5_82_fresh_app_reconstructs_the_durable_phase_5_graph(tmp_path: Path) -> None:
    """Persist through A, dispose it, and compare cold reads/projections from B."""
    settings = _settings(tmp_path)
    app_a = create_app(settings=settings)
    expected_snapshot: dict[str, Any]
    ids: dict[str, str]
    content: dict[str, bytes]
    expected_resolution: Any
    expected_prompt_layers: Any
    expected_project_preference: Any
    try:
        async with (
            app_a.router.lifespan_context(app_a),
            AsyncClient(transport=ASGITransport(app=app_a), base_url="http://test") as client,
        ):
            f1 = (await client.post("/conversation-folders", json={"name": "F1"})).json()
            f2 = (await client.post("/conversation-folders", json={"name": "F2"})).json()
            p1 = (await client.post("/projects", json={"name": "P1", "instructions": "Follow P1 rules."})).json()
            p2 = (await client.post("/projects", json={"name": "P2", "instructions": ""})).json()
            p3 = (await client.post("/projects", json={"name": "P3"})).json()

            made = {}
            for key, title, folder, project in (
                ("c1", "C1 active", f1["id"], p1["id"]),
                ("c2", "C2 archived", f2["id"], p1["id"]),
                ("c3", "C3 ungrouped", None, None),
                ("c4", "C4 project two", f1["id"], p2["id"]),
            ):
                response = await client.post("/conversations", json={"title": title})
                conv = response.json()
                made[key] = conv["conversation_id"]
                if folder:
                    await client.patch(f"/conversations/{conv['conversation_id']}/folder", json={"folder_id": folder})
                if project:
                    await client.patch(
                        f"/conversations/{conv['conversation_id']}/project", json={"project_id": project}
                    )
            await client.patch(f"/conversations/{made['c1']}/pin", json={"is_pinned": True})
            await client.patch(f"/conversations/{made['c2']}/archive", json={"is_archived": True})

            # Multiple turns plus a completed run/event chain provide stable
            # history for both transcript hydration and execution context.
            user1 = (
                await client.post(
                    f"/conversations/{made['c1']}/messages", json={"role": "user", "content": "first question"}
                )
            ).json()
            assistant1 = (
                await client.post(
                    f"/conversations/{made['c1']}/messages", json={"role": "assistant", "content": "first answer"}
                )
            ).json()
            user2 = (
                await client.post(
                    f"/conversations/{made['c1']}/messages",
                    json={"role": "user", "content": "second question 日本語"},
                )
            ).json()
            assistant2 = (
                await client.post(
                    f"/conversations/{made['c1']}/messages",
                    json={"role": "assistant", "content": "second answer 🧭"},
                )
            ).json()
            lifecycle = app_a.state.run_lifecycle_service
            lifecycle.create_run(
                "durable-completed-run", conversation_id=made["c1"], source_user_message_id=user2["message_id"]
            )
            lifecycle.start("durable-completed-run")
            lifecycle.complete("durable-completed-run")

            # Project default model identity is tied to its configured
            # provider connection, and the global defaults use one valid trio.
            persistence = app_a.state.persistence
            connection = ProviderConnection("p5-provider", "openai-compatible", "Certification provider")
            model = ModelConfiguration(
                model_id="p5-model",
                provider_connection_id=connection.provider_connection_id,
                provider_model_name="certification-model",
                display_name="Certification model",
                hosting_mode=ModelHostingMode.COMPANY_HOSTED,
                capabilities=ModelCapabilities(chat=True),
                enabled=True,
            )
            runtime = RuntimeConfiguration("p5-runtime", "native", "Certification runtime", enabled=True)
            persistence.provider_connection_repository.create(connection)
            persistence.model_configuration_repository.create(model)
            persistence.runtime_configuration_repository.create(runtime)
            defaults = ApplicationExecutionDefaults(
                connection.provider_connection_id, model.model_id, runtime.runtime_configuration_id
            )
            persistence.execution_defaults_repository.set(defaults)
            app_a.state.project_execution_defaults_service.update(
                p1["id"], UpdateProjectExecutionDefaultsRequest(runtime_key="native", model_id=model.model_id)
            )
            app_a.state.project_execution_defaults_service.update(
                p2["id"], UpdateProjectExecutionDefaultsRequest(runtime_key="native", model_id=None)
            )

            prompt_enabled = app_a.state.core_prompt_service.create_core_prompt(
                CreateCorePromptRequest(name="Durable CORE", prompt_text="Preserve prompt order.", category="core")
            )
            prompt_disabled = app_a.state.core_prompt_service.create_core_prompt(
                CreateCorePromptRequest(name="Disabled CORE", prompt_text="Disabled text.", category="style")
            )
            prompt_inherited = app_a.state.core_prompt_service.create_core_prompt(
                CreateCorePromptRequest(
                    name="Inherited CORE", prompt_text="No explicit assignment.", category="research"
                )
            )
            app_a.state.core_prompt_service.set_enabled(prompt_disabled.id, False)
            assignments = app_a.state.core_prompt_assignment_service
            for scope, scope_id in (
                (CorePromptScopeType.GLOBAL, None),
                (CorePromptScopeType.PROJECT, p1["id"]),
                (CorePromptScopeType.FOLDER, f1["id"]),
                (CorePromptScopeType.CONVERSATION, made["c1"]),
            ):
                assignments.set_assignment(prompt_enabled.id, scope, scope_id, "enable")
            assignments.set_assignment(prompt_enabled.id, CorePromptScopeType.RUNTIME, "native", "disable")
            assignments.set_assignment(prompt_enabled.id, CorePromptScopeType.CAPABILITY, "runs", "enable")
            assignments.set_assignment(prompt_disabled.id, CorePromptScopeType.GLOBAL, None, "enable")

            content = {}
            for filename, raw in (
                ("brief.txt", b"durable text\n"),
                ("duplicate-one.txt", b"one"),
                ("duplicate-two.txt", b"two"),
                ("設計仕様書.bin", bytes([0, 255, 1, 128])),
                ("empty.txt", b""),
            ):
                record = app_a.state.project_file_service.create(
                    p1["id"], file_name=filename, content_type="application/octet-stream", source=BytesIO(raw)
                )
                content[record.id] = raw

            attachment_record = app_a.state.attachment_service.create_attachment(
                file_name="conversation-設計.bin",
                media_type="application/octet-stream",
                source=BytesIO(bytes([0, 17, 255, 128])),
                owner_type=AttachmentOwnerType.CONVERSATION,
                owner_id=made["c1"],
            )
            attachment_bytes = {attachment_record.attachment_id: bytes([0, 17, 255, 128])}

            expected_resolution = app_a.state.effective_prompt_resolver.resolve(
                PromptResolutionContext(
                    conversation_id=made["c1"], runtime_key="native", capabilities=frozenset({"runs"})
                )
            )
            run_context = app_a.state.execution_prompt_context_service.build(
                RunContext(conversation_id=made["c1"]), runtime_key="native", capabilities=frozenset()
            )
            expected_prompt_layers = run_context.prompt_layers
            expected_project_preference = app_a.state.project_execution_defaults_resolver.resolve_for_conversation(
                made["c1"]
            )
            expected_snapshot = _snapshot(app_a, content, attachment_bytes)
            ids = {"f1": f1["id"], "f2": f2["id"], "p1": p1["id"], "p2": p2["id"], **made}
            assert [row["content"] for row in expected_snapshot["messages"][made["c1"]]] == [
                "first question",
                "first answer",
                "second question 日本語",
                "second answer 🧭",
            ]
            assert user1["message_id"] and assistant1["message_id"] and assistant2["message_id"]
    finally:
        # The context manager disposes the connection. Calling dispose here is
        # idempotent and makes the cold boundary explicit even on assertion failure.
        app_a.state.persistence.dispose()

    app_b = create_app(settings=settings)
    try:
        async with app_b.router.lifespan_context(app_b):
            # Startup recovery only changes genuinely active runs. The graph's
            # terminal records and all event sequence numbers must be identical.
            actual_snapshot = _snapshot(app_b, content, attachment_bytes)
            assert actual_snapshot == expected_snapshot
            persistence = app_b.state.persistence
            assert persistence.conversation_repository.get(ids["c1"]).folder_id == ids["f1"]
            assert persistence.conversation_repository.get(ids["c2"]).folder_id == ids["f2"]
            assert persistence.conversation_repository.get(ids["c4"]).folder_id == ids["f1"]
            assert persistence.conversation_repository.get(ids["c3"]).folder_id is None
            assert persistence.conversation_repository.get(ids["c1"]).project_id == ids["p1"]
            assert persistence.conversation_repository.get(ids["c2"]).project_id == ids["p1"]
            assert persistence.conversation_repository.get(ids["c4"]).project_id == ids["p2"]
            assert persistence.project_repository.get(ids["p1"]).instructions == "Follow P1 rules."
            assert persistence.project_repository.get(ids["p2"]).instructions == ""
            assert persistence.project_repository.get(p3["id"]).instructions is None

            resolution = app_b.state.effective_prompt_resolver.resolve(
                PromptResolutionContext(
                    conversation_id=ids["c1"], runtime_key="native", capabilities=frozenset({"runs"})
                )
            )
            assert resolution == expected_resolution
            assert persistence.core_prompt_assignment_repository.list_for_prompt(prompt_inherited.id) == []
            rebuilt_context = app_b.state.execution_prompt_context_service.build(
                RunContext(conversation_id=ids["c1"]), runtime_key="native", capabilities=frozenset()
            )
            assert rebuilt_context.prompt_layers == expected_prompt_layers
            assert (
                app_b.state.project_execution_defaults_resolver.resolve_for_conversation(ids["c1"])
                == expected_project_preference
            )
            configured_defaults = persistence.execution_defaults_repository.get()
            assert configured_defaults == ApplicationExecutionDefaults("p5-provider", "p5-model", "p5-runtime")
            assert persistence.provider_connection_repository.get("p5-provider") is not None
            assert persistence.model_configuration_repository.get("p5-model").provider_connection_id == "p5-provider"
            assert persistence.runtime_configuration_repository.get("p5-runtime").runtime_type == "native"
            assert [
                message.content
                for message in app_b.state.context_construction_service.build_for_source(
                    conversation_id=ids["c1"],
                    source_user_message_id=expected_snapshot["messages"][ids["c1"]][2]["message_id"],
                ).messages
            ] == ["first question", "first answer", "second question 日本語"]
            retried = await app_b.state.run_service.start_run(
                RunRequest(
                    prompt="request text is replaced by durable source",
                    conversation_id=ids["c1"],
                    retry_of_run_id="durable-completed-run",
                )
            )
            assert retried.source_user_message_id == expected_snapshot["messages"][ids["c1"]][2]["message_id"]
            assert retried.status.value == "completed"

            # Canonical projection is reconstructed from backend state; C2 is
            # present in the all-conversations source but excluded from active.
            async with AsyncClient(transport=ASGITransport(app=app_b), base_url="http://test") as client:
                all_conversations = (await client.get("/conversations")).json()["conversations"]
                assert {row["conversation_id"] for row in all_conversations} == set(
                    ids[key] for key in ("c1", "c2", "c3", "c4")
                )

                def order_key(row: dict[str, Any]) -> tuple[bool, float, float, str]:
                    return (
                        not row["is_pinned"],
                        -datetime.fromisoformat(row["updated_at"]).timestamp(),
                        -datetime.fromisoformat(row["created_at"]).timestamp(),
                        row["conversation_id"],
                    )

                assert [row["conversation_id"] for row in all_conversations] == [
                    row["conversation_id"] for row in sorted(all_conversations, key=order_key)
                ]
                archived = next(row for row in all_conversations if row["conversation_id"] == ids["c2"])
                assert archived["is_archived"] is True and archived["folder_id"] == ids["f2"]
                searched = (await client.get("/conversations", params={"search": "C1 active"})).json()["conversations"]
                assert [row["conversation_id"] for row in searched] == [ids["c1"]]
                files = (await client.get(f"/projects/{ids['p1']}/files")).json()["files"]
                assert len(files) == 5
                assert len({row["id"] for row in files if row["file_name"].startswith("duplicate-")}) == 2
                for file_id, raw in content.items():
                    response = await client.get(f"/projects/{ids['p1']}/files/{file_id}/content")
                    assert response.content == raw
                    assert "content_ref" not in (await client.get(f"/projects/{ids['p1']}/files/{file_id}")).json()
                reopened_attachment = app_b.state.attachment_service.open_attachment_content(
                    attachment_record.attachment_id
                )
                try:
                    assert reopened_attachment.stream.read() == attachment_bytes[attachment_record.attachment_id]
                finally:
                    reopened_attachment.stream.close()

            with persistence.database.connect() as connection:
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
                assert connection.execute("SELECT MAX(version) FROM ava_schema_migrations").fetchone()[0] == 25
    finally:
        app_b.state.persistence.dispose()


@pytest.mark.asyncio
async def test_phase_5_82_startup_recovery_is_idempotent_for_partial_running_turn(tmp_path: Path) -> None:
    """The single-process recovery rule retains partial output and appends once."""
    settings = _settings(tmp_path)
    app_a = create_app(settings=settings)
    async with (
        app_a.router.lifespan_context(app_a),
        AsyncClient(transport=ASGITransport(app=app_a), base_url="http://test") as client,
    ):
        conversation = (await client.post("/conversations", json={"title": "Interrupted"})).json()
        conversation_id = conversation["conversation_id"]
        user = (
            await client.post(
                f"/conversations/{conversation_id}/messages", json={"role": "user", "content": "question"}
            )
        ).json()
        lifecycle = app_a.state.run_lifecycle_service
        lifecycle.create_run("partial-run", conversation_id=conversation_id, source_user_message_id=user["message_id"])
        lifecycle.start("partial-run")
        partial = app_a.state.persistence.message_repository.append(
            MessageRecord(
                message_id="partial-assistant",
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="partial bytes are durable",
                status=MessageStatus.STREAMING,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                source_run_id="partial-run",
            )
        )
        app_a.state.persistence.run_repository.set_assistant_message_id("partial-run", partial.message_id)
        pre_recovery_events = list(app_a.state.persistence.run_event_repository.get_events("partial-run"))
    app_a.state.persistence.dispose()

    app_b = create_app(settings=settings)
    try:
        async with app_b.router.lifespan_context(app_b):
            persistence = app_b.state.persistence
            assert persistence.run_repository.get("partial-run").status.value == "failed"
            message = persistence.message_repository.get(conversation_id, "partial-assistant")
            assert message is not None and message.content == "partial bytes are durable"
            after_first = list(persistence.run_event_repository.get_events("partial-run"))
            assert after_first[: len(pre_recovery_events)] == pre_recovery_events
            assert len(after_first) == len(pre_recovery_events) + 1
            assert after_first[-1].event_type.value == "run_failed"
    finally:
        app_b.state.persistence.dispose()

    app_c = create_app(settings=settings)
    try:
        async with app_c.router.lifespan_context(app_c):
            events_after_second_start = list(app_c.state.persistence.run_event_repository.get_events("partial-run"))
            assert events_after_second_start == after_first
            assert app_c.state.persistence.run_repository.get("partial-run").status.value == "failed"
    finally:
        app_c.state.persistence.dispose()


@pytest.mark.asyncio
async def test_phase_5_82_deleted_resources_and_cleanup_remain_deleted_after_restart(tmp_path: Path) -> None:
    """Cold reopen does not resurrect deleted resources or content refs."""
    settings = _settings(tmp_path)
    app_a = create_app(settings=settings)
    async with app_a.router.lifespan_context(app_a):
        p_keep = app_a.state.project_service.create_project(name="Keep")
        p_delete = app_a.state.project_service.create_project(name="Delete")
        folder_keep = app_a.state.conversation_folder_service.create_folder("Keep Folder")
        folder_delete = app_a.state.conversation_folder_service.create_folder("Delete Folder")
        conv_deleted = app_a.state.conversation_service.create_conversation(title="Delete conversation")
        conv_folder = app_a.state.conversation_service.create_conversation(title="Folder child")
        conv_project = app_a.state.conversation_service.create_conversation(title="Project child")
        app_a.state.conversation_folder_service.set_conversation_folder(conv_folder.conversation_id, folder_delete.id)
        app_a.state.conversation_service.set_project(conv_folder.conversation_id, p_keep.id)
        app_a.state.conversation_folder_service.set_conversation_folder(conv_project.conversation_id, folder_keep.id)
        app_a.state.conversation_service.set_project(conv_project.conversation_id, p_delete.id)

        prompt = app_a.state.core_prompt_service.create_core_prompt(
            CreateCorePromptRequest(name="Delete prompt", prompt_text="Gone after restart", category="core")
        )
        app_a.state.core_prompt_assignment_service.set_assignment(
            prompt.id, CorePromptScopeType.CONVERSATION, conv_deleted.conversation_id, "enable"
        )
        app_a.state.core_prompt_assignment_service.set_assignment(
            prompt.id, CorePromptScopeType.PROJECT, p_delete.id, "disable"
        )

        deleted_conversation_file = app_a.state.project_file_service.create(
            p_delete.id, file_name="project-owned.bin", content_type=None, source=BytesIO(b"owned by deleted project")
        )
        removed_file = app_a.state.project_file_service.create(
            p_keep.id, file_name="remove.txt", content_type=None, source=BytesIO(b"remove this one")
        )
        surviving_file = app_a.state.project_file_service.create(
            p_keep.id, file_name="surviving.txt", content_type=None, source=BytesIO(b"keep this sibling")
        )
        deleted_ref = deleted_conversation_file.content_ref
        removed_ref = removed_file.content_ref
        surviving_ref = surviving_file.content_ref

        # The conversation has a durable transcript, run, events and a scoped
        # assignment; the hard-delete coordinator owns their atomic cleanup.
        user = app_a.state.conversation_service.append_message(
            conv_deleted.conversation_id, content="delete with transcript", role=MessageRole.USER
        )
        conversation_attachment = app_a.state.attachment_service.create_attachment(
            file_name="conversation.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"conversation-owned"),
            owner_type=AttachmentOwnerType.CONVERSATION,
            owner_id=conv_deleted.conversation_id,
        )
        message_attachment = app_a.state.attachment_service.create_attachment(
            file_name="message.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"message-owned"),
            owner_type=AttachmentOwnerType.MESSAGE,
            owner_id=user.message_id,
        )
        app_a.state.run_lifecycle_service.create_run(
            "deleted-conversation-run",
            conversation_id=conv_deleted.conversation_id,
            source_user_message_id=user.message_id,
        )
        app_a.state.run_lifecycle_service.start("deleted-conversation-run")
        app_a.state.run_lifecycle_service.complete("deleted-conversation-run")

        assert app_a.state.conversation_service.delete_conversation(conv_deleted.conversation_id)
        app_a.state.conversation_folder_service.delete_folder(folder_delete.id)
        app_a.state.project_service.delete_project(p_delete.id)
        app_a.state.core_prompt_service.delete_core_prompt(prompt.id)
        app_a.state.project_file_service.delete(p_keep.id, removed_file.id)
    app_a.state.persistence.dispose()

    app_b = create_app(settings=settings)
    try:
        async with app_b.router.lifespan_context(app_b):
            persistence = app_b.state.persistence
            assert persistence.conversation_repository.get(conv_deleted.conversation_id) is None
            assert persistence.message_repository.list_for_conversation(conv_deleted.conversation_id) == []
            assert persistence.run_repository.get("deleted-conversation-run") is None
            assert persistence.run_event_repository.get_events("deleted-conversation-run") == []
            assert persistence.attachment_repository.get(conversation_attachment.attachment_id) is None
            assert persistence.attachment_repository.get(message_attachment.attachment_id) is None
            assert not app_b.state.attachment_content_store.exists(conversation_attachment.storage_key)
            assert not app_b.state.attachment_content_store.exists(message_attachment.storage_key)
            assert persistence.conversation_repository.get(conv_folder.conversation_id).folder_id is None
            assert persistence.conversation_repository.get(conv_folder.conversation_id).project_id == p_keep.id
            project_survivor = persistence.conversation_repository.get(conv_project.conversation_id)
            assert project_survivor is not None
            assert project_survivor.project_id is None
            assert project_survivor.folder_id == folder_keep.id
            assert persistence.conversation_folder_repository.get(folder_delete.id) is None
            assert persistence.conversation_folder_repository.get(folder_keep.id) == folder_keep
            assert persistence.project_repository.get(p_delete.id) is None
            assert persistence.core_prompt_repository.get(prompt.id) is None
            assert persistence.core_prompt_assignment_repository.list_for_prompt(prompt.id) == []
            assert persistence.project_file_repository.get(deleted_conversation_file.id) is None
            assert persistence.project_file_repository.get(removed_file.id) is None
            assert persistence.project_file_repository.get(surviving_file.id) == surviving_file
            assert not app_b.state.project_file_content_store.exists(deleted_ref)
            assert not app_b.state.project_file_content_store.exists(removed_ref)
            assert app_b.state.project_file_content_store.exists(surviving_ref)
            with app_b.state.project_file_service.open_content(p_keep.id, surviving_file.id) as handle:
                assert handle.read() == b"keep this sibling"
            with persistence.database.connect() as connection:
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        app_b.state.persistence.dispose()
