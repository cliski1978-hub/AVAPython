"""Project-file metadata/content lifecycle and public API coverage."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier

import pytest
from httpx import ASGITransport, AsyncClient

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.repositories.project_file import ProjectFileRecord
from ava.services.conversation_store import ConversationStore
from ava.services.project_file_content_store import InMemoryProjectFileContentStore
from ava.services.project_file_service import (
    ProjectFileAlreadyExistsError,
    ProjectFileService,
    ProjectFileStorageError,
)
from ava.services.project_file_store import ProjectFileStore
from ava.services.project_service import ProjectService
from ava.services.project_store import ProjectStore


class _FailingProjectFileRepository(ProjectFileStore):
    def create(self, record: ProjectFileRecord) -> ProjectFileRecord:
        self.content_ref = record.content_ref
        raise RuntimeError("metadata persistence failed")


class _FailingDeleteContentStore(InMemoryProjectFileContentStore):
    def delete(self, content_ref: str) -> bool:
        raise OSError("storage unavailable")


class _BarrierProjectFileContentStore(InMemoryProjectFileContentStore):
    def __init__(self, barrier: Barrier) -> None:
        super().__init__()
        self._barrier = barrier

    def write(self, content_ref: str, source: BytesIO) -> int:
        self._barrier.wait(timeout=5)
        return super().write(content_ref, source)


def test_upload_metadata_failure_rolls_back_written_content() -> None:
    projects = ProjectStore(ConversationStore())
    project = ProjectService(project_repository=projects).create_project(name="P")
    content = InMemoryProjectFileContentStore()
    repository = _FailingProjectFileRepository()
    service = ProjectFileService(projects=projects, files=repository, content=content)
    with pytest.raises(RuntimeError, match="metadata persistence failed"):
        service.create(project.id, file_name="same.txt", content_type=None, source=BytesIO(b"data"))
    assert not content.exists(repository.content_ref)


def test_content_cleanup_failure_is_reported_after_metadata_delete() -> None:
    projects = ProjectStore(ConversationStore())
    project = ProjectService(project_repository=projects).create_project(name="P")
    files = ProjectFileStore()
    content = _FailingDeleteContentStore()
    service = ProjectFileService(projects=projects, files=files, content=content)
    record = service.create(project.id, file_name="a.txt", content_type=None, source=BytesIO(b"x"))

    with pytest.raises(ProjectFileStorageError, match="content cleanup failed"):
        service.delete(project.id, record.id)
    assert files.get(record.id) is None
    assert content.exists(record.content_ref)


def test_project_content_cleanup_failure_is_reported_after_metadata_commit() -> None:
    conversations = ConversationStore()
    files = ProjectFileStore()
    projects = ProjectStore(conversations, files=files)
    content = _FailingDeleteContentStore()
    file_service = ProjectFileService(projects=projects, files=files, content=content)
    project_service = ProjectService(project_repository=projects, project_file_service=file_service)
    project = project_service.create_project(name="P")
    record = file_service.create(project.id, file_name="a.txt", content_type=None, source=BytesIO(b"x"))

    with pytest.raises(ProjectFileStorageError, match="content cleanup failed"):
        project_service.delete_project(project.id)
    assert projects.get(project.id) is None
    assert files.get(record.id) is None
    assert content.exists(record.content_ref)


@pytest.mark.parametrize("provider", ["memory", "relational"])
@pytest.mark.asyncio
async def test_project_file_upload_download_ownership_and_delete(provider: str, tmp_path: Path) -> None:
    settings = Settings(
        persistence_provider=provider,
        persistence_database_url=str(tmp_path / "project-files.sqlite3"),
        project_file_storage="local",
        project_file_storage_root=str(tmp_path / "content"),
    )
    app = create_app(settings=settings)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = (await client.post("/projects", json={"name": "First"})).json()
            second = (await client.post("/projects", json={"name": "Second"})).json()
            assert (await client.get(f"/projects/{first['id']}/files")).json()["files"] == []
            assert (await client.get("/projects/missing/files")).json()["error_code"] == "project_not_found"
            missing_upload = await client.post("/projects/missing/files", files={"file": ("x.txt", b"x")})
            assert missing_upload.status_code == 404
            assert missing_upload.json()["error_code"] == "project_not_found"
            raw = bytes([0, 255, 1, 128])
            uploaded = await client.post(
                f"/projects/{first['id']}/files",
                files={"file": ("設計仕様書.pdf", raw, "application/pdf")},
            )
            assert uploaded.status_code == 201, uploaded.text
            item = uploaded.json()
            assert item["file_name"] == "設計仕様書.pdf"
            assert item["content_type"] == "application/pdf"
            assert item["size_bytes"] == len(raw)
            assert "content_ref" not in item

            duplicate_upload = await client.post(
                f"/projects/{first['id']}/files",
                files={"file": ("設計仕様書.pdf", b"different bytes", "application/pdf")},
            )
            assert duplicate_upload.status_code == 409
            assert duplicate_upload.json()["error_code"] == "project_file_name_conflict"
            assert duplicate_upload.json()["message"] == (
                'A file named "設計仕様書.pdf" already exists in this Project. '
                "Delete or rename the existing file before uploading another."
            )
            assert (await client.get(f"/projects/{first['id']}/files/{item['id']}/content")).content == raw
            assert (await client.get(f"/projects/{first['id']}/files/{item['id']}")).json() == item
            assert len(app.state.persistence.project_file_repository.list_by_project(first["id"])) == 1

            other_project_copy = await client.post(
                f"/projects/{second['id']}/files",
                files={"file": ("設計仕様書.pdf", b"other project", "application/pdf")},
            )
            assert other_project_copy.status_code == 201

            skill = await client.post(
                f"/projects/{first['id']}/files", files={"file": ("SKILL.md", b"first", "text/markdown")}
            )
            assert skill.status_code == 201
            case_duplicate = await client.post(
                f"/projects/{first['id']}/files", files={"file": ("skill.md", b"different", "text/markdown")}
            )
            assert case_duplicate.status_code == 409
            whitespace_duplicate = await client.post(
                f"/projects/{first['id']}/files",
                data={"file_name": "SKILL.md "},
                files={"file": ("other.md", b"different", "text/markdown")},
            )
            assert whitespace_duplicate.status_code == 409
            assert (await client.delete(f"/projects/{first['id']}/files/{skill.json()['id']}")).status_code == 204
            replacement = await client.post(
                f"/projects/{first['id']}/files", files={"file": ("SKILL.md", b"replacement", "text/markdown")}
            )
            assert replacement.status_code == 201
            empty_upload = await client.post(
                f"/projects/{first['id']}/files", files={"file": ("empty.txt", b"", "text/plain")}
            )
            empty = empty_upload.json()
            assert empty["size_bytes"] == 0
            assert (await client.get(f"/projects/{first['id']}/files/{empty['id']}/content")).content == b""

            listed = await client.get(f"/projects/{first['id']}/files")
            listed_files = listed.json()["files"]
            assert {row["id"] for row in listed_files} == {item["id"], empty["id"], replacement.json()["id"]}
            assert [row["file_name"].casefold() for row in listed_files] == sorted(
                row["file_name"].casefold() for row in listed_files
            )
            assert (await client.get(f"/projects/{first['id']}/files/{item['id']}")).json() == item
            denied = await client.get(f"/projects/{second['id']}/files/{item['id']}")
            assert denied.status_code == 404 and denied.json()["error_code"] == "project_file_not_found"
            denied_download = await client.get(f"/projects/{second['id']}/files/{item['id']}/content")
            assert denied_download.status_code == 404
            denied_delete = await client.delete(f"/projects/{second['id']}/files/{item['id']}")
            assert denied_delete.status_code == 404
            assert app.state.project_file_content_store.exists(
                app.state.persistence.project_file_repository.get(item["id"]).content_ref
            )

            content = await client.get(f"/projects/{first['id']}/files/{item['id']}/content")
            assert content.content == raw
            assert content.headers["content-type"] == "application/pdf"
            assert content.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
            assert "%E8%A8%AD%E8%A8%88%E4%BB%95%E6%A7%98%E6%9B%B8.pdf" in content.headers["content-disposition"]

            if provider == "relational":
                content_ref = app.state.persistence.project_file_repository.get(item["id"]).content_ref
                app.state.persistence.dispose()
                app2 = create_app(settings=settings)
                try:
                    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://test") as reopened:
                        round_trip = await reopened.get(f"/projects/{first['id']}/files/{item['id']}/content")
                        assert round_trip.content == raw
                        reopened_files = (await reopened.get(f"/projects/{first['id']}/files")).json()["files"]
                        assert len(reopened_files) == 3
                        assert {row["file_name"] for row in reopened_files} == {
                            "設計仕様書.pdf",
                            "empty.txt",
                            "SKILL.md",
                        }
                        deleted = await reopened.delete(f"/projects/{first['id']}/files/{item['id']}")
                        assert deleted.status_code == 204
                        assert app2.state.persistence.project_file_repository.get(item["id"]) is None
                        assert not app2.state.project_file_content_store.exists(content_ref)
                finally:
                    app2.state.persistence.dispose()
                return

            deleted = await client.delete(f"/projects/{first['id']}/files/{item['id']}")
            assert deleted.status_code == 204
            assert (await client.get(f"/projects/{first['id']}/files/{item['id']}")).status_code == 404
    finally:
        app.state.persistence.dispose()


def test_concurrent_duplicate_uploads_allow_exactly_one_database_create(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider="relational",
            persistence_database_url=str(tmp_path / "project-file-race.sqlite3"),
            project_file_storage="local",
            project_file_storage_root=str(tmp_path / "content"),
        )
    )
    try:
        project = app.state.project_service.create_project(name="Race")
        barrier = Barrier(2)
        content = _BarrierProjectFileContentStore(barrier)
        service = ProjectFileService(
            projects=app.state.persistence.project_repository,
            files=app.state.persistence.project_file_repository,
            content=content,
        )

        def upload(payload: bytes):
            try:
                return service.create(
                    project.id, file_name="SKILL.md", content_type="text/markdown", source=BytesIO(payload)
                )
            except ProjectFileAlreadyExistsError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(upload, (b"first", b"second")))

        assert sum(not isinstance(result, ProjectFileAlreadyExistsError) for result in results) == 1
        assert sum(isinstance(result, ProjectFileAlreadyExistsError) for result in results) == 1
        stored = app.state.persistence.project_file_repository.list_by_project(project.id)
        assert len(stored) == 1
        assert len(content._content) == 1
        with content.read(stored[0].content_ref) as source:
            assert source.read() in {b"first", b"second"}
    finally:
        app.state.persistence.dispose()


@pytest.mark.asyncio
async def test_project_delete_cleans_project_file_metadata_and_content(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider="relational",
            persistence_database_url=str(tmp_path / "project-delete-files.sqlite3"),
            project_file_storage="local",
            project_file_storage_root=str(tmp_path / "content"),
        )
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            project = (await client.post("/projects", json={"name": "Delete me"})).json()
            uploaded = await client.post(f"/projects/{project['id']}/files", files={"file": ("a.txt", b"one")})
            first_file = uploaded.json()
            uploaded_second = await client.post(f"/projects/{project['id']}/files", files={"file": ("b.txt", b"two")})
            items = [first_file, uploaded_second.json()]
            content_refs = [app.state.persistence.project_file_repository.get(item["id"]).content_ref for item in items]
            assert all(app.state.project_file_content_store.exists(ref) for ref in content_refs)
            assert (await client.delete(f"/projects/{project['id']}")).status_code == 204
            assert all(app.state.persistence.project_file_repository.get(item["id"]) is None for item in items)
            assert all(not app.state.project_file_content_store.exists(ref) for ref in content_refs)
    finally:
        app.state.persistence.dispose()


def test_project_delete_database_failure_keeps_metadata_and_content(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            persistence_provider="relational",
            persistence_database_url=str(tmp_path / "project-delete-rollback.sqlite3"),
            project_file_storage="local",
            project_file_storage_root=str(tmp_path / "content"),
        )
    )
    try:
        project = app.state.project_service.create_project(name="Keep me")
        record = app.state.project_file_service.create(
            project.id, file_name="safe.txt", content_type=None, source=BytesIO(b"keep bytes")
        )
        with app.state.persistence.database.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER fail_project_delete BEFORE DELETE ON projects "
                "BEGIN SELECT RAISE(ABORT, 'injected deletion failure'); END"
            )

        with pytest.raises(ValueError):
            app.state.project_service.delete_project(project.id)

        assert app.state.project_service.get_project(project.id).id == project.id
        assert app.state.persistence.project_file_repository.get(record.id) == record
        assert app.state.project_file_content_store.exists(record.content_ref)
    finally:
        app.state.persistence.dispose()
