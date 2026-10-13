"""Conversation-owned attachment route, cleanup, and restart integration tests."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier

import httpx
import pytest

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.attachments import AttachmentOwnerType
from ava.repositories.attachment_repository import DuplicateConversationAttachmentNameError


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://ava.test",
    )


@pytest.mark.asyncio
async def test_conversation_attachment_isolation_duplicate_names_and_owner_scoped_delete() -> None:
    app = create_app()
    async with _client(app) as client:
        conversation_a = (await client.post("/conversations", json={"title": "A"})).json()["conversation_id"]
        conversation_b = (await client.post("/conversations", json={"title": "B"})).json()["conversation_id"]
        uploaded_a = await client.post(
            f"/conversations/{conversation_a}/attachments",
            files={"file": ("notes.md", b"A", "text/markdown")},
        )
        uploaded_b = await client.post(
            f"/conversations/{conversation_b}/attachments",
            files={"file": ("notes.md", b"B", "text/markdown")},
        )
        duplicate_a = await client.post(
            f"/conversations/{conversation_a}/attachments",
            files={"file": ("NOTES.md ", b"replacement", "text/markdown")},
        )
        duplicate_generic = await client.post(
            "/attachments",
            files={"file": ("notes.md", b"also replacement", "text/markdown")},
            data={"owner_type": "conversation", "owner_id": conversation_a},
        )
        assert uploaded_a.status_code == uploaded_b.status_code == 201
        attachment_a = uploaded_a.json()
        original_record = app.state.persistence.attachment_repository.get(attachment_a["attachment_id"])
        assert duplicate_a.status_code == 409
        assert duplicate_a.json()["error_code"] == "conversation_attachment_name_conflict"
        assert duplicate_a.json()["message"] == (
            'A file named "notes.md" is already attached to this conversation. '
            "Remove or rename the existing file before uploading another."
        )
        assert duplicate_generic.status_code == 409
        assert duplicate_generic.json()["error_code"] == "conversation_attachment_name_conflict"
        assert attachment_a["owner_type"] == "conversation"
        assert attachment_a["owner_id"] == conversation_a
        listed_a = (await client.get(f"/conversations/{conversation_a}/attachments")).json()["attachments"]
        assert [item["attachment_id"] for item in listed_a] == [attachment_a["attachment_id"]]
        stored_content = app.state.attachment_service.open_attachment_content(attachment_a["attachment_id"])
        assert stored_content is not None
        try:
            assert stored_content.stream.read() == b"A"
        finally:
            stored_content.stream.close()
        assert app.state.persistence.attachment_repository.get(attachment_a["attachment_id"]) == original_record
        assert len(app.state.attachment_content_store._contents) == 2
        listed_b = (await client.get(f"/conversations/{conversation_b}/attachments")).json()["attachments"]
        assert [item["file_name"] for item in listed_b] == ["notes.md"]

        wrong_owner = await client.delete(
            f"/conversations/{conversation_b}/attachments/{attachment_a['attachment_id']}"
        )
        removed = await client.delete(
            f"/conversations/{conversation_a}/attachments/{attachment_a['attachment_id']}"
        )
        reuploaded = await client.post(
            f"/conversations/{conversation_a}/attachments",
            files={"file": ("notes.md", b"after removal", "text/markdown")},
        )
        after_a = (await client.get(f"/conversations/{conversation_a}/attachments")).json()["attachments"]
        content_after_delete = await client.get(f"/attachments/{attachment_a['attachment_id']}/content")

    assert wrong_owner.status_code == 404
    assert removed.status_code == 204
    assert reuploaded.status_code == 201
    assert [item["attachment_id"] for item in after_a] == [reuploaded.json()["attachment_id"]]
    assert content_after_delete.status_code == 404
    assert len(app.state.persistence.attachment_repository.list_for_owner(
        AttachmentOwnerType.CONVERSATION, conversation_b
    )) == 1
    app.state.persistence.dispose()


@pytest.mark.asyncio
async def test_failed_upload_and_oversize_upload_leave_no_conversation_attachment() -> None:
    app = create_app()
    app.state.attachment_max_size_bytes = 3
    async with _client(app) as client:
        conversation_id = (await client.post("/conversations", json={"title": "A"})).json()["conversation_id"]
        oversized = await client.post(
            f"/conversations/{conversation_id}/attachments",
            files={"file": ("large.txt", b"four", "text/plain")},
        )
        app.state.attachment_content_store.exists = lambda _key: False
        failed = await client.post(
            f"/conversations/{conversation_id}/attachments",
            files={"file": ("broken.txt", b"bad", "text/plain")},
        )
        listed = (await client.get(f"/conversations/{conversation_id}/attachments")).json()["attachments"]

    assert oversized.status_code == 413
    assert oversized.json()["error_code"] == "attachment_too_large"
    assert failed.status_code == 500
    assert listed == []
    assert app.state.persistence.attachment_repository.list_for_owner(
        AttachmentOwnerType.CONVERSATION, conversation_id
    ) == []
    assert app.state.attachment_content_store._contents == {}
    app.state.persistence.dispose()


@pytest.mark.asyncio
async def test_conversation_attachments_survive_relational_and_local_storage_restart(tmp_path: Path) -> None:
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "ava.sqlite3"),
        attachment_storage="local",
        attachment_storage_root=str(tmp_path / "attachment-content"),
    )
    first_app = create_app(settings=settings)
    async with _client(first_app) as first:
        conversation_id = (await first.post("/conversations", json={"title": "Durable"})).json()["conversation_id"]
        uploaded = await first.post(
            f"/conversations/{conversation_id}/attachments",
            files={"file": ("restart.md", b"durable data", "text/markdown")},
        )
    assert uploaded.status_code == 201
    attachment_id = uploaded.json()["attachment_id"]
    first_app.state.persistence.dispose()

    second_app = create_app(settings=settings)
    async with _client(second_app) as second:
        restored = await second.get(f"/conversations/{conversation_id}/attachments")
        content = second_app.state.attachment_service.open_attachment_content(attachment_id)
        assert content is not None
        try:
            assert content.stream.read() == b"durable data"
        finally:
            content.stream.close()
        removed = await second.delete(
            f"/conversations/{conversation_id}/attachments/{attachment_id}"
        )
    assert restored.status_code == 200
    assert [item["attachment_id"] for item in restored.json()["attachments"]] == [attachment_id]
    assert removed.status_code == 204
    content = second_app.state.attachment_service.open_attachment_content(attachment_id)
    assert content is None
    assert not (tmp_path / "attachment-content" / "attachments").exists()
    second_app.state.persistence.dispose()


@pytest.mark.asyncio
async def test_project_file_and_conversation_attachment_may_share_a_filename() -> None:
    app = create_app()
    async with _client(app) as client:
        project = (await client.post("/projects", json={"name": "Workspace"})).json()
        conversation = (
            await client.post(f"/projects/{project['id']}/conversations", json={"title": "Chat"})
        ).json()
        project_file = await client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("SKILL.md", b"project data", "text/markdown")},
        )
        attachment = await client.post(
            f"/conversations/{conversation['conversation_id']}/attachments",
            files={"file": ("SKILL.md", b"conversation data", "text/markdown")},
        )
    assert project_file.status_code == attachment.status_code == 201
    assert app.state.attachment_content_store._contents
    app.state.persistence.dispose()


@pytest.mark.asyncio
async def test_concurrent_conversation_attachment_uploads_cannot_duplicate_filename(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider="relational",
            persistence_database_url=str(tmp_path / "attachment-race.sqlite3"),
        )
    )
    async with _client(app) as client:
        conversation_id = (await client.post("/conversations", json={"title": "Race"})).json()["conversation_id"]

    barrier = Barrier(2)

    def upload(payload: bytes):
        barrier.wait(timeout=5)
        return app.state.attachment_service.create_attachment(
            file_name="SKILL.md",
            media_type="text/markdown",
            source=BytesIO(payload),
            owner_type=AttachmentOwnerType.CONVERSATION,
            owner_id=conversation_id,
            retain_failed_record=False,
        )

    def result(payload: bytes):
        try:
            return upload(payload)
        except DuplicateConversationAttachmentNameError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(result, (b"first", b"second")))

    assert sum(isinstance(item, DuplicateConversationAttachmentNameError) for item in results) == 1
    records = app.state.persistence.attachment_repository.list_for_owner(
        AttachmentOwnerType.CONVERSATION, conversation_id
    )
    assert len(records) == 1
    assert len(app.state.attachment_content_store._contents) == 1
    stored = app.state.attachment_service.open_attachment_content(records[0].attachment_id)
    assert stored is not None
    try:
        assert stored.stream.read() in (b"first", b"second")
    finally:
        stored.stream.close()
    app.state.persistence.dispose()
