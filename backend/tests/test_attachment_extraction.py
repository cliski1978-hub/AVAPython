"""Stored-byte extraction, ownership, failure preservation, and cold-reopen tests."""

import ast
from collections.abc import Iterator
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.attachment_extraction import AttachmentExtractionStatus
from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus
from ava.repositories.attachment_repository import AttachmentRecord


def test_extraction_has_no_execution_storage_or_public_api_coupling() -> None:
    source = Path(__file__).parents[1] / "src" / "ava"
    extractor = source / "services" / "attachment_extraction_service.py"
    imports = {node.module for node in ast.walk(ast.parse(extractor.read_text())) if isinstance(node, ast.ImportFrom)}
    assert imports == {
        "ava.contracts.attachment_extraction",
        "ava.contracts.attachments",
        "ava.repositories.attachment_repository",
        "ava.repositories.conversation_repository",
        "ava.services.attachment_service",
    }
    for area in ("agents", "runtimes", "execution", "api/routes"):
        for file in (source / area).rglob("*.py"):
            assert "attachment_extraction" not in file.read_text(), file


@pytest.fixture(params=["memory", "relational"])
def app(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[FastAPI]:
    application = create_app(
        settings=Settings(
            persistence_provider=request.param,
            persistence_database_url=str(tmp_path / "extraction.sqlite3"),
            attachment_storage="local",
            attachment_storage_root=str(tmp_path / "content"),
            attachment_max_size_bytes=128,
        )
    )
    yield application
    application.state.persistence.dispose()


def upload(app: FastAPI, name: str, content: bytes, media_type: str = "application/octet-stream") -> AttachmentRecord:
    conversation = app.state.conversation_service.create_conversation("Extraction")
    record: AttachmentRecord = app.state.attachment_service.create_attachment(
        file_name=name,
        media_type=media_type,
        source=BytesIO(content),
        owner_type=AttachmentOwnerType.CONVERSATION,
        owner_id=conversation.conversation_id,
    )
    return record


def assert_preserved(app: FastAPI, record: AttachmentRecord, content: bytes) -> None:
    assert app.state.attachment_service.get_attachment(record.attachment_id) == record
    ref = app.state.attachment_service.open_attachment_content(record.attachment_id)
    assert ref is not None
    with ref.stream:
        assert ref.stream.read() == content


@pytest.mark.parametrize(
    ("name", "media_type", "content", "expected"),
    [
        ("notes.txt", "text/plain", b"hello world", "hello world"),
        ("SKILL.md", "application/octet-stream", b"# Skill\n\n**full Markdown**\n", "# Skill\n\n**full Markdown**\n"),
        ("data.json", "application/json", b'{ "key": [1, 2] }\n', '{ "key": [1, 2] }\n'),
        ("data.csv", "text/csv", b"a,b\r\n1,2\r\n", "a,b\r\n1,2\r\n"),
        ("BOM.TXT", "image/png", b"\xef\xbb\xbfhello", "hello"),
        ("empty.txt", "text/plain", b"", ""),
        ("Unicode.md", "text/markdown", "# café 日本語 😀".encode(), "# café 日本語 😀"),
        ("extensionless", "text/plain; charset=utf-8", b"MIME fallback", "MIME fallback"),
    ],
)
def test_text_extraction_preserves_authored_content(
    app: FastAPI,
    name: str,
    media_type: str,
    content: bytes,
    expected: str,
) -> None:
    record = upload(app, name, content, media_type)
    result = app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id)
    assert result is not None
    assert result.status is AttachmentExtractionStatus.SUCCESS
    assert result.text == expected
    assert (result.attachment_id, result.file_name, result.media_type) == (
        record.attachment_id,
        name,
        media_type,
    )
    assert result.error_code is result.error_message is None
    assert_preserved(app, record, content)


@pytest.mark.parametrize(
    "name",
    ["diagram.png", "archive.zip", "program.exe", "unknown.bin", "report.pdf", "report.docx"],
)
def test_unsupported_extension_cannot_be_overridden_by_mime(app: FastAPI, name: str) -> None:
    record = upload(app, name, b"binary\x00", "text/plain")
    with patch.object(app.state.attachment_content_store, "open", side_effect=AssertionError("must not open")):
        result = app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id)
    assert result.status is AttachmentExtractionStatus.UNSUPPORTED
    assert result.text is None
    assert result.error_code == "attachment_type_unsupported"
    assert_preserved(app, record, b"binary\x00")


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"invalid\xff", "attachment_text_decode_failed"),
        (b"a\x00b", "attachment_binary_content"),
        (b"PK\x03\x04archive", "attachment_binary_content"),
        (b"\xff\xfeh\x00i\x00", "attachment_text_decode_failed"),
    ],
)
def test_invalid_text_fails_without_mutating_attachment(app: FastAPI, content: bytes, code: str) -> None:
    record = upload(app, "invalid.txt", content)
    result = app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id)
    assert result.status is AttachmentExtractionStatus.FAILED
    assert result.error_code == code
    assert result.text is None
    assert_preserved(app, record, content)


def test_ownership_is_checked_before_content_access(app: FastAPI) -> None:
    record = upload(app, "private.md", b"private")
    other = app.state.conversation_service.create_conversation("Other")
    with patch.object(app.state.attachment_content_store, "open", side_effect=AssertionError("must not open")):
        assert app.state.attachment_extraction_service.extract(other.conversation_id, record.attachment_id) is None
        assert app.state.attachment_extraction_service.extract("missing", record.attachment_id) is None
        assert app.state.attachment_extraction_service.extract(record.owner_id, "missing") is None
        for owner_type in (None, AttachmentOwnerType.MESSAGE, AttachmentOwnerType.DOCUMENT):
            with patch.object(
                app.state.attachment_service,
                "get_attachment",
                return_value=replace(
                    record,
                    owner_type=owner_type,
                ),
            ):
                assert app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id) is None
    assert_preserved(app, record, b"private")


def test_missing_content_and_read_errors_are_normalized(app: FastAPI) -> None:
    record = upload(app, "missing.txt", b"stored")
    for error in (
        FileNotFoundError("private path"),
        OSError("private path"),
        ValueError("private key"),
        RuntimeError("private adapter details"),
    ):
        with patch.object(app.state.attachment_content_store, "open", side_effect=error):
            result = app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id)
        assert result.status is AttachmentExtractionStatus.FAILED
        assert result.error_code == "attachment_content_read_failed"
        assert "private" not in result.error_message
    app.state.attachment_content_store.delete(record.storage_key)
    result = app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id)
    assert result.error_code == "attachment_content_read_failed"
    assert app.state.attachment_service.get_attachment(record.attachment_id) == record


def test_read_failure_closes_stream_and_other_attachments_still_extract(app: FastAPI) -> None:
    record = upload(app, "broken.txt", b"stored")
    healthy = upload(app, "healthy.txt", b"healthy")

    class BrokenStream(BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise OSError("private storage details")

    stream = BrokenStream(b"stored")
    with patch.object(app.state.attachment_content_store, "open", return_value=stream):
        result = app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id)
    assert result.error_code == "attachment_content_read_failed"
    assert stream.closed
    assert_preserved(app, record, b"stored")
    assert app.state.attachment_extraction_service.extract(healthy.owner_id, healthy.attachment_id).text == "healthy"


@pytest.mark.parametrize("status", [AttachmentStatus.PENDING, AttachmentStatus.FAILED])
def test_unavailable_lifecycle_does_not_open_content(app: FastAPI, status: AttachmentStatus) -> None:
    record = upload(app, "pending.txt", b"stored")
    app.state.persistence.attachment_repository.update_state(record.attachment_id, size_bytes=6, status=status)
    with patch.object(app.state.attachment_content_store, "open", side_effect=AssertionError("must not open")):
        result = app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id)
    assert result.error_code == "attachment_content_unavailable"
    assert app.state.attachment_service.get_attachment(record.attachment_id).status is status


def test_size_limit_checks_metadata_and_actual_bytes_and_closes_stream(app: FastAPI) -> None:
    record = upload(app, "large.txt", b"x" * 129)
    with patch.object(app.state.attachment_content_store, "open", side_effect=AssertionError("must not open")):
        result = app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id)
    assert result.error_code == "attachment_too_large"
    app.state.persistence.attachment_repository.update_state(
        record.attachment_id,
        size_bytes=1,
        status=AttachmentStatus.AVAILABLE,
    )
    stream = BytesIO(b"x" * 1000)
    with patch.object(app.state.attachment_content_store, "open", return_value=stream):
        result = app.state.attachment_extraction_service.extract(record.owner_id, record.attachment_id)
    assert result.error_code == "attachment_too_large"
    assert stream.closed
    exact = upload(app, "exact.txt", b"x" * 128)
    assert app.state.attachment_extraction_service.extract(exact.owner_id, exact.attachment_id).text == "x" * 128


@pytest.mark.asyncio
async def test_real_upload_extract_and_cold_restart(tmp_path: Path) -> None:
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=str(tmp_path / "durable.sqlite3"),
        attachment_storage="local",
        attachment_storage_root=str(tmp_path / "content"),
    )
    first = create_app(settings=settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=first), base_url="http://ava.test") as client:
        conversation_id = (await client.post("/conversations", json={"title": "Extraction"})).json()["conversation_id"]
        attachment = (
            await client.post(
                f"/conversations/{conversation_id}/attachments",
                files={"file": ("test.md", b"AVA-ATTACHMENT-EXTRACTION-7319", "text/markdown")},
            )
        ).json()
    before = first.state.attachment_extraction_service.extract(conversation_id, attachment["attachment_id"])
    assert before.text == "AVA-ATTACHMENT-EXTRACTION-7319"
    first.state.persistence.dispose()
    second = create_app(settings=settings)
    try:
        after = second.state.attachment_extraction_service.extract(conversation_id, attachment["attachment_id"])
        assert after == before
    finally:
        second.state.persistence.dispose()
