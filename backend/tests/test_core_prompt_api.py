"""Phase 5.67 public CORE prompt API coverage."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from ava.api.app import create_app
from ava.api.routes.core_prompts import router
from ava.configuration.settings import Settings
from ava.contracts.core_prompts import CreateCorePromptRequest
from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.repositories.core_prompt_assignment import CorePromptScopeType
from ava.repositories.project import ProjectRecord


def test_core_prompt_routes_are_registered_with_expected_methods() -> None:
    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    actual = {(route.path, method) for route in routes for method in route.methods or set()}
    assert {
        ("/core-prompts", "POST"),
        ("/core-prompts", "GET"),
        ("/core-prompts/{core_prompt_id}", "GET"),
        ("/core-prompts/{core_prompt_id}", "PATCH"),
        ("/core-prompts/{core_prompt_id}/enabled", "PATCH"),
        ("/core-prompts/{core_prompt_id}", "DELETE"),
        ("/core-prompts/{core_prompt_id}/assignments", "GET"),
        ("/core-prompts/{core_prompt_id}/assignments", "PUT"),
        ("/core-prompt-assignments", "GET"),
        ("/core-prompts/resolve", "POST"),
    } <= actual


@pytest.mark.parametrize("provider", ["memory", "relational"])
@pytest.mark.asyncio
async def test_prompt_preview_includes_unassigned_core_prompts_at_every_conversation_scope(
    provider: str, tmp_path: Path
) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider=provider,
            persistence_database_url=str(tmp_path / f"prompt-preview-global-{provider}.sqlite3"),
        )
    )
    try:
        persistence = app.state.persistence
        now = datetime.now(UTC)
        persistence.project_repository.create(ProjectRecord("project-1", "Project", now, now))
        persistence.conversation_folder_repository.create(ConversationFolderRecord("folder-1", "Folder", now, now))
        persistence.conversation_repository.create("plain", title="Plain")
        persistence.conversation_repository.create("project-chat", title="Project", project_id="project-1")
        persistence.conversation_repository.create("folder-chat", title="Folder", folder_id="folder-1")
        prompt = app.state.core_prompt_service.create_core_prompt(
            CreateCorePromptRequest(
                name="AVA PRIME DIRECTIVES",
                prompt_text="Protect agency and preserve truth.",
                category="core",
            )
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            responses = [
                await client.get("/prompt-preview"),
                await client.get("/conversations/plain/prompt-preview"),
                await client.get("/conversations/project-chat/prompt-preview"),
                await client.get("/conversations/folder-chat/prompt-preview"),
            ]
        for response in responses:
            assert response.status_code == 200
            assert [item["id"] for item in response.json()["resolved_core_prompts"]] == [prompt.id]
            assert response.json()["resolved_core_prompts"][0]["prompt_text"] == prompt.prompt_text
    finally:
        app.state.persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
@pytest.mark.asyncio
async def test_prompt_resolution_preview_derives_membership_and_is_read_only(provider: str, tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider=provider,
            persistence_database_url=str(tmp_path / f"prompt-resolution-{provider}.sqlite3"),
        )
    )
    try:
        persistence = app.state.persistence
        now = datetime.now(UTC)
        persistence.project_repository.create(ProjectRecord("project-1", "Project", now, now))
        persistence.conversation_folder_repository.create(ConversationFolderRecord("folder-1", "Folder", now, now))
        persistence.conversation_repository.create("conversation-1", title="Chat", project_id="project-1")
        persistence.conversation_repository.set_folder("conversation-1", "folder-1")
        prompt = app.state.core_prompt_service.create_core_prompt(
            CreateCorePromptRequest(name="Architecture", prompt_text="Be clear.", category="architecture")
        )
        app.state.core_prompt_assignment_service.set_assignment(prompt.id, CorePromptScopeType.GLOBAL, None, "enable")
        app.state.core_prompt_assignment_service.set_assignment(
            prompt.id, CorePromptScopeType.FOLDER, "folder-1", "disable"
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/core-prompts/resolve",
                json={"conversation_id": "conversation-1", "runtime_key": "native", "capabilities": ["runs"]},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["context"] == {
                "conversation_id": "conversation-1",
                "project_id": "project-1",
                "folder_id": "folder-1",
                "runtime_key": "native",
                "capabilities": ["runs"],
            }
            assert body["enabled_prompts"] == []
            assert body["excluded_prompts"][0]["winning_scope_type"] == "folder"
            assert body["excluded_prompts"][0]["reason"] == "explicit_disable"
            no_conversation = await client.post("/core-prompts/resolve", json={})
            assert no_conversation.status_code == 200
            assert no_conversation.json()["context"]["conversation_id"] is None
            missing = await client.post("/core-prompts/resolve", json={"conversation_id": "missing"})
            assert missing.status_code == 404 and missing.json()["error_code"] == "conversation_not_found"
            unknown_runtime = await client.post("/core-prompts/resolve", json={"runtime_key": "missing"})
            assert unknown_runtime.status_code == 404 and unknown_runtime.json()["error_code"] == "runtime_not_found"
            contradictory_context = await client.post(
                "/core-prompts/resolve", json={"conversation_id": "conversation-1", "folder_id": "other-folder"}
            )
            assert contradictory_context.status_code == 422
        assert (
            app.state.core_prompt_assignment_service.get_assignment(
                prompt.id, CorePromptScopeType.FOLDER, "folder-1"
            ).mode.value
            == "disable"
        )
    finally:
        app.state.persistence.dispose()


@pytest.mark.parametrize("provider", ["memory", "relational"])
@pytest.mark.asyncio
async def test_core_prompt_crud_validation_enable_and_delete(provider: str, tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider=provider,
            persistence_database_url=str(tmp_path / f"core-prompts-api-{provider}.sqlite3"),
        )
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            text = "  # Exact\n\n- Keep  spaces\n- 日本語 → 🧭\n"
            response = await client.post(
                "/core-prompts",
                json={
                    "name": "  Engineering  ",
                    "description": "Metadata\nmultiline",
                    "prompt_text": text,
                    "category": "engineering",
                },
            )
            assert response.status_code == 201
            created = response.json()

            assigned = await client.put(
                f"/core-prompts/{created['id']}/assignments",
                json={"scope_type": "global", "scope_id": None, "state": "enable"},
            )
            assert assigned.status_code == 200
            assert assigned.json()["state"] == "enable"
            assert assigned.json()["assignment_id"]
            listed_assignments = await client.get(f"/core-prompts/{created['id']}/assignments")
            assert [item["state"] for item in listed_assignments.json()["assignments"]] == ["enable"]
            inherited = await client.put(
                f"/core-prompts/{created['id']}/assignments",
                json={"scope_type": "global", "scope_id": None, "state": "inherit"},
            )
            assert inherited.json()["state"] == "inherit"
            assert inherited.json()["assignment_id"] is None
            assert (await client.get(f"/core-prompts/{created['id']}/assignments")).json()["assignments"] == []
            assert created["name"] == "Engineering"
            assert created["description"] == "Metadata\nmultiline"
            assert created["prompt_text"] == text
            assert created["category"] == "engineering"
            assert created["is_enabled"] is True
            assert created["created_at"] == created["updated_at"]
            assert set(created) == {
                "id",
                "name",
                "description",
                "prompt_text",
                "category",
                "is_enabled",
                "created_at",
                "updated_at",
                "contract_version",
            }

            duplicate = await client.post(
                "/core-prompts", json={"name": "Engineering", "prompt_text": "Other", "category": "core"}
            )
            assert duplicate.status_code == 201
            assert duplicate.json()["id"] != created["id"]

            assert (await client.get(f"/core-prompts/{created['id']}")).json() == created
            listed = await client.get("/core-prompts")
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()["core_prompts"]] == [
                duplicate.json()["id"],
                created["id"],
            ]

            updated_response = await client.patch(
                f"/core-prompts/{created['id']}",
                json={"name": "Architecture", "prompt_text": "  Updated\ntext  ", "category": "architecture"},
            )
            assert updated_response.status_code == 200
            updated = updated_response.json()
            assert updated["id"] == created["id"]
            assert updated["created_at"] == created["created_at"]
            assert updated["updated_at"] > created["updated_at"]
            assert updated["description"] == created["description"]
            assert updated["prompt_text"] == "  Updated\ntext  "

            cleared = await client.patch(
                f"/core-prompts/{created['id']}",
                json={"name": "Architecture", "description": None, "prompt_text": "Text", "category": "core"},
            )
            assert cleared.json()["description"] is None
            empty = await client.patch(
                f"/core-prompts/{created['id']}",
                json={"name": "Architecture", "description": "", "prompt_text": "Text", "category": "core"},
            )
            assert empty.json()["description"] == ""

            disabled = await client.patch(f"/core-prompts/{created['id']}/enabled", json={"is_enabled": False})
            assert disabled.status_code == 200 and disabled.json()["is_enabled"] is False
            repeated = await client.patch(f"/core-prompts/{created['id']}/enabled", json={"is_enabled": False})
            assert repeated.json() == disabled.json()
            enabled = await client.patch(f"/core-prompts/{created['id']}/enabled", json={"is_enabled": True})
            assert enabled.json()["is_enabled"] is True

            blank_name = await client.post("/core-prompts", json={"name": " ", "prompt_text": "x", "category": "core"})
            blank_text = await client.post(
                "/core-prompts", json={"name": "x", "prompt_text": " \n", "category": "core"}
            )
            bad_category = await client.post(
                "/core-prompts", json={"name": "x", "prompt_text": "x", "category": "unknown"}
            )
            bad_enabled = await client.patch(f"/core-prompts/{created['id']}/enabled", json={"is_enabled": "false"})
            assert blank_name.status_code == blank_text.status_code == bad_category.status_code == 422
            assert bad_enabled.status_code == 422

            deleted = await client.delete(f"/core-prompts/{created['id']}")
            assert deleted.status_code == 204 and deleted.content == b""
            for method, url, payload in (
                ("get", f"/core-prompts/{created['id']}", None),
                (
                    "patch",
                    f"/core-prompts/{created['id']}",
                    {"name": "Missing", "prompt_text": "text", "category": "core"},
                ),
                ("patch", f"/core-prompts/{created['id']}/enabled", {"is_enabled": True}),
                ("delete", f"/core-prompts/{created['id']}", None),
            ):
                if payload:
                    missing = await getattr(client, method)(url, json=payload)
                else:
                    missing = await getattr(client, method)(url)
                assert missing.status_code == 404
                assert missing.json()["error_code"] == "core_prompt_not_found"
    finally:
        app.state.persistence.dispose()
