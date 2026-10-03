"""Phase 5.58 public Project API coverage."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.models.model_configurations import ModelConfiguration
from ava.models.provider_connections import ProviderConnection


@pytest.mark.parametrize("provider", ["memory", "relational"])
@pytest.mark.asyncio
async def test_project_crud_archive_and_errors(provider: str, tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider=provider,
            persistence_database_url=str(tmp_path / f"project-api-{provider}.sqlite3"),
        )
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created_response = await client.post(
                "/projects",
                json={
                    "name": "  AVA Engineering  ",
                    "description": "Engineering work",
                    "instructions": "Stored, not executed →\n- 日本語\n  Keep spacing.",
                },
            )
            assert created_response.status_code == 201
            created = created_response.json()
            assert created["name"] == "AVA Engineering"
            assert created["description"] == "Engineering work"
            assert created["instructions"] == "Stored, not executed →\n- 日本語\n  Keep spacing."
            assert created["is_archived"] is False
            assert created["created_at"] == created["updated_at"]
            assert set(created) == {
                "id",
                "name",
                "description",
                "instructions",
                "is_archived",
                "created_at",
                "updated_at",
                "contract_version",
            }

            duplicate = await client.post("/projects", json={"name": "AVA Engineering"})
            assert duplicate.status_code == 201
            assert duplicate.json()["id"] != created["id"]
            blank = await client.post("/projects", json={"name": " \t "})
            assert blank.status_code == 422

            project_id = created["id"]
            assert (await client.get(f"/projects/{project_id}")).json() == created
            assert (await client.get("/projects/missing")).json()["error_code"] == "project_not_found"
            assert (await client.patch("/projects/missing", json={"name": "Unknown"})).json()[
                "error_code"
            ] == "project_not_found"
            assert (
                await client.patch("/projects/missing/archive", json={"is_archived": True})
            ).json()["error_code"] == "project_not_found"
            missing_delete = await client.delete("/projects/missing")
            assert missing_delete.status_code == 404
            assert missing_delete.json()["error_code"] == "project_not_found"

            updated_response = await client.patch(f"/projects/{project_id}", json={"name": "Platform"})
            assert updated_response.status_code == 200
            updated = updated_response.json()
            assert updated["id"] == created["id"]
            assert updated["name"] == "Platform"
            assert updated["created_at"] == created["created_at"]
            assert updated["updated_at"] > created["updated_at"]
            assert updated["description"] == created["description"]
            assert updated["instructions"] == created["instructions"]

            cleared = await client.patch(
                f"/projects/{project_id}",
                json={"name": "Platform", "description": None, "instructions": "New inert data"},
            )
            assert cleared.json()["description"] is None
            assert cleared.json()["instructions"] == "New inert data"

            explicitly_cleared = await client.patch(
                f"/projects/{project_id}", json={"name": "Platform", "instructions": None}
            )
            assert explicitly_cleared.status_code == 200
            assert explicitly_cleared.json()["instructions"] is None
            assert explicitly_cleared.json()["description"] is None

            archived_response = await client.patch(
                f"/projects/{project_id}/archive", json={"is_archived": True}
            )
            archived = archived_response.json()
            assert archived_response.status_code == 200 and archived["is_archived"] is True
            repeated_archive = await client.patch(
                f"/projects/{project_id}/archive", json={"is_archived": True}
            )
            assert repeated_archive.json() == archived
            assert repeated_archive.json()["updated_at"] == archived["updated_at"]

            listed = await client.get("/projects")
            assert listed.status_code == 200
            projects = listed.json()["projects"]
            assert project_id in [item["id"] for item in projects]
            assert len(projects) == 2  # archived Projects remain listed
            assert projects[0]["is_archived"] is False
            assert projects[1]["id"] == project_id and projects[1]["is_archived"] is True

            restored_response = await client.patch(
                f"/projects/{project_id}/archive", json={"is_archived": False}
            )
            restored = restored_response.json()
            assert restored_response.status_code == 200 and restored["is_archived"] is False
            assert (
                await client.patch(f"/projects/{project_id}/archive", json={"is_archived": False})
            ).json() == restored

            deleted = await client.delete(f"/projects/{project_id}")
            assert deleted.status_code == 204 and deleted.content == b""
            assert (await client.get(f"/projects/{project_id}")).json()["error_code"] == "project_not_found"
            second_delete = await client.delete(f"/projects/{project_id}")
            assert second_delete.status_code == 404
            assert second_delete.json()["error_code"] == "project_not_found"
            remaining = await client.get("/projects")
            assert [item["id"] for item in remaining.json()["projects"]] == [duplicate.json()["id"]]
    finally:
        app.state.persistence.dispose()


@pytest.mark.asyncio
async def test_project_execution_defaults_api_preserves_omitted_fields_and_clears_explicit_null(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider="relational",
            persistence_database_url=str(tmp_path / "project-defaults-api.sqlite3"),
        )
    )
    persistence = app.state.persistence
    persistence.provider_connection_repository.create(ProviderConnection("connection-a", "provider-x", "Provider"))
    persistence.model_configuration_repository.create(
        ModelConfiguration(
            model_id="model-a",
            provider_connection_id="connection-a",
            provider_model_name="provider-model-a",
            display_name="Model A",
            hosting_mode=ModelHostingMode.COMPANY_HOSTED,
            capabilities=ModelCapabilities(chat=True),
        )
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            project = (await client.post("/projects", json={"name": "Execution Prefs"})).json()
            path = f"/projects/{project['id']}/execution-defaults"
            conversation = (
                await client.post(f"/projects/{project['id']}/conversations", json={"title": "Member"})
            ).json()
            project_conversations_before = (await client.get(f"/projects/{project['id']}/conversations")).json()
            global_defaults_before = (await client.get("/settings/defaults")).json()
            initial = await client.get(path)
            assert initial.status_code == 200
            assert initial.json()["runtime_key"] is None and initial.json()["model_id"] is None

            both = await client.patch(path, json={"runtime_key": "native", "model_id": "model-a"})
            assert both.status_code == 200
            assert (both.json()["runtime_key"], both.json()["model_id"]) == ("native", "model-a")
            assert (await client.get("/settings/defaults")).json() == global_defaults_before
            project_conversations_after = (await client.get(f"/projects/{project['id']}/conversations")).json()
            assert project_conversations_after == project_conversations_before
            assert project_conversations_after["conversations"][0]["conversation_id"] == conversation[
                "conversation_id"
            ]
            assert project_conversations_after["conversations"][0]["folder_id"] is None
            no_op = await client.patch(path, json={})
            assert (no_op.json()["runtime_key"], no_op.json()["model_id"]) == ("native", "model-a")

            runtime_cleared = await client.patch(path, json={"runtime_key": None})
            assert (runtime_cleared.json()["runtime_key"], runtime_cleared.json()["model_id"]) == (None, "model-a")
            model_cleared = await client.patch(path, json={"model_id": None})
            assert (model_cleared.json()["runtime_key"], model_cleared.json()["model_id"]) == (None, None)

            reset = await client.patch(path, json={"runtime_key": "native", "model_id": "model-a"})
            assert reset.status_code == 200
            only_model = await client.patch(path, json={"model_id": "model-a"})
            assert (only_model.json()["runtime_key"], only_model.json()["model_id"]) == ("native", "model-a")

            invalid_runtime = await client.patch(path, json={"runtime_key": "unknown-runtime"})
            invalid_model = await client.patch(path, json={"model_id": "unknown-model"})
            assert invalid_runtime.status_code == 422 and invalid_runtime.json()["error_code"] == "runtime_not_found"
            assert invalid_model.status_code == 422 and invalid_model.json()["error_code"] == "model_not_found"
            unchanged = (await client.get(path)).json()
            assert (unchanged["runtime_key"], unchanged["model_id"]) == ("native", "model-a")
            assert (await client.patch("/projects/missing/execution-defaults", json={"runtime_key": None})).json()[
                "error_code"
            ] == "project_not_found"
    finally:
        persistence.dispose()
